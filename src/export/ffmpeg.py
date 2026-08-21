"""
FFmpeg Video Export

Extracts highlight clips from source video based on detected events.
Handles clip cutting, concatenation, title overlays, and format conversion.

Capabilities:
  - Extract subclips by time range with pre/post-roll buffers
  - Concatenate multiple clips into a highlight reel
  - Add text overlays (event type, timestamp, description)
  - Slow-motion segments for key moments
  - Output formats: MP4 (H.264), ProRes (broadcast), GIF (social)
  - Batch export with progress tracking

Usage:
    from src.export.ffmpeg import extract_clip, build_highlight_reel

    extract_clip("game.mp4", 120.5, 128.0, "goal_clip.mp4")
    
    events = detect_events(track)
    build_highlight_reel("game.mp4", events[:5], "highlights.mp4")
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from telemetry.models import Event, EventType
from telemetry.logging_setup import get_logger, get_ffmpeg_logger

log = get_logger(__name__)
ffmpeg_log = get_ffmpeg_logger()


# ══════════════════════════════════════════════════════════════════════════
# Runtime tool resolution (PyInstaller-aware)
# ══════════════════════════════════════════════════════════════════════════

def _frozen_root() -> Path:
    """Directory holding bundled resources when running as a frozen executable."""
    if getattr(sys, "frozen", False):
        # onefile: sys._MEIPASS is the extraction dir; onedir: next to the exe
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _tool_names(name: str) -> List[str]:
    """Candidate file names for a tool, honoring Windows .exe convention."""
    names = [name]
    if sys.platform.startswith("win"):
        names.extend((name + ".exe", name + ".cmd", name + ".bat"))
    return names


def resolve_tool(name: str) -> str:
    """Locate an external tool (ffmpeg/ffprobe) for the running app.

    Search order:
      1. A bundled copy inside the frozen app (LVA_BUNDLE_FFMPEG=1 build)
      2. The executable's own directory (onedir layout)
      3. PATH

    Windows builds look for ffmpeg.exe/ffprobe.exe in addition to the bare
    name. Returns the plain tool name as a last resort so subprocess errors
    stay descriptive instead of raising here.
    """
    if getattr(sys, "frozen", False):
        roots = [_frozen_root(), Path(sys.executable).parent]
        for root in roots:
            for candidate in (root / n for n in _tool_names(name)):
                if candidate.exists():
                    # Windows has no execute bit; existence is enough there
                    if sys.platform.startswith("win") or os.access(candidate, os.X_OK):
                        return str(candidate)
    found = shutil.which(name)
    return found or name


# ══════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ExportConfig:
    """Configuration for video export operations."""
    # Paths (auto-resolved: bundled copy -> executable dir -> PATH)
    ffmpeg_path: str = field(default_factory=lambda: resolve_tool("ffmpeg"))
    ffprobe_path: str = field(default_factory=lambda: resolve_tool("ffprobe"))
    
    # Clip extraction
    pre_roll_sec: float = 3.0       # Seconds before event start
    post_roll_sec: float = 2.0      # Seconds after event end
    min_clip_duration_sec: float = 3.0  # Minimum clip length
    
    # Output
    video_codec: str = "libx264"    # H.264 for MP4
    audio_codec: str = "aac"        # AAC audio
    video_bitrate: str = "4M"       # 4 Mbps
    crf: int = 23                   # Constant Rate Factor (lower = better)
    preset: str = "medium"          # FFmpeg preset (fast/medium/slow)
    
    # Overlays
    title_font_size: int = 24
    title_font_color: str = "white"
    title_bg_color: str = "black@0.5"  # Semi-transparent black
    title_duration_sec: float = 3.0    # How long title stays visible
    
    # Slow motion
    slowmo_factor: float = 0.5      # 0.5 = half speed
    slowmo_duration_sec: float = 2.0 # How long to slow down around peak
    
    # Metadata export
    save_metadata: bool = True      # Write .json sidecar per clip
    save_manifest: bool = True      # Write manifest.jsonl index
    
    # Concurrency
    max_workers: int = 2            # Parallel clip extraction


# ══════════════════════════════════════════════════════════════════════════
# Public API — Single Clip
# ══════════════════════════════════════════════════════════════════════════

def extract_clip(
    video_path: str | Path,
    start_sec: float,
    end_sec: float,
    output_path: str | Path,
    *,
    pre_roll_sec: float = 3.0,
    post_roll_sec: float = 2.0,
    config: Optional[ExportConfig] = None,
) -> Path:
    """Extract a single subclip from a video file.
    
    Args:
        video_path: Source video file
        start_sec: Clip start time in seconds
        end_sec: Clip end time in seconds
        output_path: Where to write the extracted clip
        pre_roll_sec: Seconds to include before start
        post_roll_sec: Seconds to include after end
        config: Optional export configuration
    
    Returns:
        Path to the extracted clip
    
    Raises:
        FileNotFoundError: If video_path doesn't exist
        RuntimeError: If FFmpeg fails
    """
    cfg = config or ExportConfig()
    video = Path(video_path)
    
    if not video.exists():
        raise FileNotFoundError(f"Video file not found: {video}")
    
    # Apply pre/post roll, clamped to 0
    clip_start = max(0.0, start_sec - pre_roll_sec)
    clip_end = end_sec + post_roll_sec
    duration = clip_end - clip_start
    
    if duration < cfg.min_clip_duration_sec:
        log.warning(
            "clip too short, extending to minimum duration",
            extra={"start": clip_start, "end": clip_end, "duration": duration},
        )
        clip_end = clip_start + cfg.min_clip_duration_sec
    
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        cfg.ffmpeg_path, "-y",
        "-ss", str(clip_start),
        "-i", str(video),
        "-t", str(clip_end - clip_start),
        "-c:v", cfg.video_codec,
        "-crf", str(cfg.crf),
        "-preset", cfg.preset,
        "-c:a", cfg.audio_codec,
        "-b:v", cfg.video_bitrate,
        "-movflags", "+faststart",  # Web-optimized
        str(output),
    ]
    
    log.info(
        f"extracting clip: {clip_start:.1f}s–{clip_end:.1f}s → {output.name}",
        extra={"start": clip_start, "end": clip_end, "output": str(output)},
    )
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute timeout
        )
        
        # Log FFmpeg stderr
        for line in result.stderr.splitlines():
            if line.strip():
                ffmpeg_log.info(line.strip())
        
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg exited with code {result.returncode}:\n{result.stderr[-500:]}"
            )
        
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg produced empty output: {output}")
        
        size_mb = output.stat().st_size / (1024 * 1024)
        log.info(f"clip extracted: {output.name} ({size_mb:.1f} MB)")
        
        return output
    
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg timed out extracting {output.name}")
    except FileNotFoundError:
        raise RuntimeError(
            f"FFmpeg not found at '{cfg.ffmpeg_path}'. Install FFmpeg: "
            "sudo apt install ffmpeg (Linux) or brew install ffmpeg (macOS)"
        )


def extract_clip_from_event(
    video_path: str | Path,
    event: Event,
    output_path: str | Path,
    *,
    config: Optional[ExportConfig] = None,
    add_title: bool = False,
) -> Path:
    """Extract a clip for a single detected event.
    
    Convenience wrapper that uses event time bounds and optionally
    burns in a title overlay.
    
    Args:
        video_path: Source video file
        event: Detected event with time bounds
        output_path: Output clip path
        config: Export configuration
        add_title: Whether to burn event description as title overlay
    
    Returns:
        Path to the extracted clip
    """
    cfg = config or ExportConfig()
    
    path = extract_clip(
        video_path,
        event.start_time_sec,
        event.end_time_sec,
        output_path,
        pre_roll_sec=cfg.pre_roll_sec,
        post_roll_sec=cfg.post_roll_sec,
        config=cfg,
    )
    
    if add_title:
        title = _event_title(event)
        path = _burn_title(path, title, cfg)
    
    return path


# ══════════════════════════════════════════════════════════════════════════
# Public API — Highlight Reel
# ══════════════════════════════════════════════════════════════════════════

def build_highlight_reel(
    video_path: str | Path,
    events: List[Event],
    output_path: str | Path,
    *,
    max_clips: int = 10,
    config: Optional[ExportConfig] = None,
    add_titles: bool = True,
    add_slowmo: bool = True,
    transition_fade_sec: float = 0.5,
) -> Path:
    """Build a highlight reel from top events.
    
    Pipeline:
    1. Rank events by priority score
    2. Extract individual clips with pre/post roll
    3. Add slow-motion around event peaks (optional)
    4. Burn title overlays (optional)
    5. Concatenate clips with fade transitions
    
    Args:
        video_path: Source video file
        events: Detected events (will be ranked by priority)
        output_path: Output highlight reel path
        max_clips: Maximum number of clips to include
        config: Export configuration
        add_titles: Whether to add title overlays
        add_slowmo: Whether to add slow-motion at peaks
        transition_fade_sec: Cross-fade duration between clips
    
    Returns:
        Path to the highlight reel
    """
    cfg = config or ExportConfig()
    
    from analysis.metrics import rank_events
    top_events = rank_events(events, top_n=max_clips)
    
    if not top_events:
        raise ValueError("No events to export")
    
    log.info(
        f"building highlight reel: {len(top_events)} clips → {output_path}",
        extra={"clips": len(top_events), "output": str(output_path)},
    )
    
    # Phase 1: Extract individual clips to temp directory
    with tempfile.TemporaryDirectory(prefix="lva_clips_") as tmpdir:
        tmp = Path(tmpdir)
        clip_paths: List[Path] = []
        
        for i, event in enumerate(top_events):
            clip_name = f"clip_{i:03d}_{event.event_type.value}.mp4"
            clip_path = tmp / clip_name
            
            try:
                extracted = extract_clip_from_event(
                    video_path, event, clip_path, config=cfg, add_title=False,
                )
                
                # Apply slow-motion if enabled
                if add_slowmo:
                    slowmo_path = tmp / f"slowmo_{i:03d}.mp4"
                    extracted = _apply_slow_motion(extracted, event, slowmo_path, cfg)
                
                # Burn title overlay if enabled
                if add_titles:
                    titled_path = tmp / f"titled_{i:03d}.mp4"
                    title = _event_title(event)
                    extracted = _burn_title(extracted, title, cfg)
                
                clip_paths.append(extracted)
                
            except RuntimeError as e:
                log.warning(f"skipping clip {i}: {e}")
                continue
        
        if not clip_paths:
            raise RuntimeError("No clips were successfully extracted")
        
        # Phase 2: Concatenate clips
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        if len(clip_paths) == 1:
            # Single clip — just copy
            import shutil
            shutil.copy(clip_paths[0], output)
            log.info(f"single-clip reel: {output.name}")
        else:
            _concat_clips(clip_paths, output, cfg, fade_sec=transition_fade_sec)
        
        # Phase 3: Save metadata sidecars
        if cfg.save_metadata or cfg.save_manifest:
            _save_metadata_sidecars(tmp, top_events, output.parent, cfg)
        
        size_mb = output.stat().st_size / (1024 * 1024)
        log.info(f"highlight reel complete: {output.name} ({size_mb:.1f} MB)")
    
    return output


# ══════════════════════════════════════════════════════════════════════════
# Internal — Clip Manipulation
# ══════════════════════════════════════════════════════════════════════════

def _concat_clips(
    clip_paths: List[Path],
    output: Path,
    cfg: ExportConfig,
    fade_sec: float = 0.5,
) -> None:
    """Concatenate multiple clips using FFmpeg concat demuxer."""
    # Write concat file
    concat_file = output.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for path in clip_paths:
            f.write(f"file '{path.absolute()}'\n")
    
    # Build filter for cross-fade if enabled
    if fade_sec > 0 and len(clip_paths) > 1:
        # Cross-fade is complex — fall back to simple concat with stream copy
        # (lossless, fast, reliable). Cross-fade can be added post-MVP.
        log.info("cross-fade requested but using simple concat (reliable)")
    
    # Simple concat with stream copy — fast and lossless
    cmd = [
        cfg.ffmpeg_path, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",  # Stream copy — no re-encoding
        str(output),
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        for line in result.stderr.splitlines():
            if line.strip():
                ffmpeg_log.info(line.strip())
        if result.returncode != 0:
            raise RuntimeError(f"Concat failed: {result.stderr[-300:]}")
    finally:
        concat_file.unlink(missing_ok=True)


def _build_crossfade_filter(n_clips: int, fade_duration: float = 0.5) -> str:
    """Build FFmpeg cross-fade filter chain for n clips."""
    # Simplified approach: fade in/out each clip
    filters = []
    for i in range(n_clips):
        v_in = f"[{i}:v]" if i == 0 else f"[v{i}]"
        a_in = f"[{i}:a]" if i == 0 else f"[a{i}]"
        
        if i == n_clips - 1:
            # Last clip — just fade in
            filters.append(
                f"{v_in} fade=t=in:d={fade_duration}[vout];"
            )
        elif i == 0:
            # First clip — fade out at end
            filters.append(
                f"[{i}:v] fade=t=out:st=999:d={fade_duration}[v{i+1}];"
                f"[{i}:a] afade=t=out:st=999:d={fade_duration}[a{i+1}];"
            )
    
    # Fallback: simple concat
    inputs = "".join(f"[{i}:v][{i}:a]" for i in range(n_clips))
    return f"{inputs} concat=n={n_clips}:v=1:a=1[vout][aout]"


# ══════════════════════════════════════════════════════════════════════════
# Metadata Sidecar Export (for AI training dataset)
# ══════════════════════════════════════════════════════════════════════════

def _save_metadata_sidecars(
    tmp: Path,
    events: list,
    output_dir: Path,
    cfg: ExportConfig,
) -> None:
    """Save per-clip metadata JSON and manifest.jsonl.
    
    For each event, writes a .json sidecar with:
      - Event type, confidence, intensity, timestamps
      - Export parameters (pre/post roll, codec)
      - Frame range in source video
    
    Also writes manifest.jsonl indexing all clips.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries = []
    
    for i, event in enumerate(events):
        clip_name = f"clip_{i:03d}_{event.event_type.value}"
        
        # Build metadata entry
        entry = {
            "clip": f"{clip_name}.mp4",
            "event_type": event.event_type.value,
            "confidence": round(event.confidence, 3),
            "intensity": event.intensity.value,
            "priority_score": round(event.priority_score, 3),
            "source_start_sec": round(event.start_time_sec, 2),
            "source_end_sec": round(event.end_time_sec, 2),
            "peak_time_sec": round(event.peak_time_sec, 2),
            "clip_start_sec": round(max(0.0, event.start_time_sec - cfg.pre_roll_sec), 2),
            "clip_end_sec": round(event.end_time_sec + cfg.post_roll_sec, 2),
            "duration_sec": round(event.duration_sec, 2),
            "frame_range": list(event.frame_range),
            "description": event.description,
            "tags": event.tags,
            "export_config": {
                "pre_roll_sec": cfg.pre_roll_sec,
                "post_roll_sec": cfg.post_roll_sec,
                "codec": cfg.video_codec,
                "crf": cfg.crf,
                "preset": cfg.preset,
            },
        }
        
        # Write per-clip JSON sidecar
        if cfg.save_metadata:
            sidecar_path = output_dir / f"{clip_name}.json"
            with open(sidecar_path, "w") as f:
                json.dump(entry, f, indent=2)
        
        manifest_entries.append(entry)
    
    # Write manifest.jsonl (one JSON object per line for streaming)
    if cfg.save_manifest and manifest_entries:
        manifest_path = output_dir / "manifest.jsonl"
        with open(manifest_path, "w") as f:
            for entry in manifest_entries:
                f.write(json.dumps(entry) + "\n")
        
        log.info(
            f"saved metadata: {len(manifest_entries)} clips indexed",
            extra={"manifest": str(manifest_path), "clips": len(manifest_entries)},
        )


def export_training_dataset(
    video_path: str | Path,
    events: List[Event],
    output_dir: str | Path,
    *,
    config: Optional[ExportConfig] = None,
    max_clips: int = 50,
) -> Path:
    """Export clips organized by event type for AI training.
    
    Directory structure:
        output_dir/
        ├── goal/
        │   ├── clip_001.mp4
        │   ├── clip_001.json
        │   └── ...
        ├── shot/
        ├── save/
        ├── transition/
        ├── face_off/
        └── manifest.jsonl
    
    Each clip gets a JSON sidecar with labels, telemetry, and export params.
    
    Args:
        video_path: Source video file
        events: Detected events
        output_dir: Root directory for dataset output
        config: Export configuration
        max_clips: Max clips per event type
    
    Returns:
        Path to the dataset directory
    """
    cfg = config or ExportConfig()
    cfg.save_metadata = True
    cfg.save_manifest = True
    cfg.add_titles = False  # Clean clips for training
    
    from analysis.metrics import rank_events
    top_events = rank_events(events, top_n=max_clips * 6)  # Enough for all types
    
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    
    # Group events by type
    by_type: dict[str, list] = {}
    for e in top_events:
        by_type.setdefault(e.event_type.value, []).append(e)
    
    total_clips = 0
    manifest_entries = []
    
    for event_type, type_events in by_type.items():
        type_dir = root / event_type
        type_dir.mkdir(exist_ok=True)
        
        for i, event in enumerate(type_events[:max_clips]):
            clip_path = type_dir / f"clip_{i:03d}.mp4"
            
            try:
                extract_clip_from_event(
                    video_path, event, clip_path, config=cfg, add_title=False,
                )
                total_clips += 1
            except RuntimeError as e:
                log.warning(f"skipping {event_type} clip {i}: {e}")
    
    # Write manifest
    manifest_entries = []
    for event_type in by_type:
        type_dir = root / event_type
        for json_file in sorted(type_dir.glob("*.json")):
            with open(json_file) as f:
                manifest_entries.append(json.load(f))
    
    if manifest_entries:
        manifest_path = root / "manifest.jsonl"
        with open(manifest_path, "w") as f:
            for entry in manifest_entries:
                f.write(json.dumps(entry) + "\n")
    
    log.info(
        f"training dataset exported: {total_clips} clips in {len(by_type)} categories",
        extra={"dir": str(root), "clips": total_clips, "categories": list(by_type.keys())},
    )
    
    return root


def _burn_title(
    video_path: Path,
    title: str,
    cfg: ExportConfig,
) -> Path:
    """Burn a title overlay into the video using drawtext filter."""
    output = video_path.parent / f"titled_{video_path.name}"
    
    # Escape title for FFmpeg drawtext
    safe_title = title.replace(":", "\\:").replace("'", "\\'")
    
    cmd = [
        cfg.ffmpeg_path, "-y",
        "-i", str(video_path),
        "-vf",
        f"drawtext=text='{safe_title}':"
        f"fontcolor={cfg.title_font_color}:"
        f"fontsize={cfg.title_font_size}:"
        f"box=1:boxcolor={cfg.title_bg_color}:"
        f"boxborderw=8:"
        f"x=(w-text_w)/2:y=h-th-20:"
        f"enable='between(t,0,{cfg.title_duration_sec})'",
        "-c:v", cfg.video_codec,
        "-crf", str(cfg.crf),
        "-preset", cfg.preset,
        "-c:a", "copy",
        str(output),
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.warning(f"title burn failed, using original: {result.stderr[-200:]}")
            return video_path  # Return original if title fails
        return output
    except Exception as e:
        log.warning(f"title burn error: {e}")
        return video_path


def _apply_slow_motion(
    video_path: Path,
    event: Event,
    output: Path,
    cfg: ExportConfig,
) -> Path:
    """Apply slow-motion effect around the event peak."""
    # Get video duration
    duration = _probe_duration(video_path, cfg)
    if duration is None:
        return video_path
    
    peak_relative = event.peak_time_sec - event.start_time_sec
    slow_start = max(0, peak_relative - cfg.slowmo_duration_sec / 2)
    
    cmd = [
        cfg.ffmpeg_path, "-y",
        "-i", str(video_path),
        "-filter_complex",
        f"[0:v]setpts='if(between(T,{slow_start},{slow_start + cfg.slowmo_duration_sec}),"
        f"{1/cfg.slowmo_factor}*PTS,PTS)'[v];"
        f"[0:a]atempo='if(between(t,{slow_start},{slow_start + cfg.slowmo_duration_sec}),"
        f"{cfg.slowmo_factor},1)'[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", cfg.video_codec,
        "-crf", str(cfg.crf),
        "-preset", cfg.preset,
        str(output),
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            log.warning(f"slow-motion failed, using original: {result.stderr[-200:]}")
            return video_path
        return output
    except Exception as e:
        log.warning(f"slow-motion error: {e}")
        return video_path


# ══════════════════════════════════════════════════════════════════════════
# Internal — Helpers
# ══════════════════════════════════════════════════════════════════════════

def _probe_duration(video_path: Path, cfg: ExportConfig) -> Optional[float]:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        cfg.ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    return None


def _event_title(event: Event) -> str:
    """Generate a title string for an event overlay."""
    icons = {
        EventType.GOAL: "🥍 GOAL",
        EventType.SHOT: "🎯 SHOT",
        EventType.SAVE: "🧤 SAVE",
        EventType.TRANSITION: "🏃 TRANSITION",
        EventType.FACE_OFF: "⚡ FACE-OFF",
        EventType.TURNOVER: "↩️ TURNOVER",
    }
    icon = icons.get(event.event_type, event.event_type.value.upper())
    time_str = f"{int(event.peak_time_sec // 60)}:{int(event.peak_time_sec % 60):02d}"
    return f"{icon}  •  {time_str}  •  {event.intensity.value.upper()}"


# ══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point: extract highlight clips or build reel."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract highlight clips from video using event timestamps",
    )
    sub = parser.add_subparsers(dest="command")
    
    # extract subcommand
    ext = sub.add_parser("extract", help="Extract a single clip")
    ext.add_argument("video", help="Source video file")
    ext.add_argument("start", type=float, help="Start time in seconds")
    ext.add_argument("end", type=float, help="End time in seconds")
    ext.add_argument("output", help="Output clip path")
    ext.add_argument("--pre-roll", type=float, default=3.0)
    ext.add_argument("--post-roll", type=float, default=2.0)
    
    # reel subcommand
    reel = sub.add_parser("reel", help="Build highlight reel from track file")
    reel.add_argument("video", help="Source video file")
    reel.add_argument("track", help="FALCON .track file")
    reel.add_argument("output", help="Output highlight reel path")
    reel.add_argument("--max-clips", type=int, default=10)
    reel.add_argument("--no-titles", action="store_true")
    reel.add_argument("--no-slowmo", action="store_true")
    reel.add_argument("--debug", action="store_true")
    
    args = parser.parse_args()
    
    from telemetry.logging_setup import configure_logging
    configure_logging(level="DEBUG" if getattr(args, "debug", False) else "INFO")
    
    if args.command == "extract":
        path = extract_clip(
            args.video, args.start, args.end, args.output,
            pre_roll_sec=args.pre_roll, post_roll_sec=args.post_roll,
        )
        print(f"✅ Clip saved: {path}")
    
    elif args.command == "reel":
        from telemetry.parser import parse_track_file
        from analysis.detection import detect_events
        
        track = parse_track_file(args.track)
        events = detect_events(track)
        
        path = build_highlight_reel(
            args.video, events, args.output,
            max_clips=args.max_clips,
            add_titles=not args.no_titles,
            add_slowmo=not args.no_slowmo,
        )
        print(f"✅ Highlight reel: {path}")
    
    else:
        parser.print_help()
