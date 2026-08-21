"""
FALCON .track File Parser

Parses the proprietary FALCON AI camera tracking format into
the domain models defined in src.telemetry.models.

.track format (SDK V1.2.0+):
  Frame{N} SZ{N} Yaw{N} Pit{N} fps{N}
  [AF]FilterP{N} mot{N} Deque{N}(V{v},x{p})...
  Fast{0-4} Crowdx{N}
  FIN:x{N} V{N}
  Zoom:CPSz{N}

Usage:
    python -m src.telemetry.parser <track_file>
    
    from src.telemetry.parser import parse_track_file
    track = parse_track_file("game1.track")
    print(f"Parsed {len(track.points)} frames over {track.metadata.total_duration_sec:.1f}s")
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .models import (
    TrackPoint, GameMetadata, TrackSummary, ActivityWindow,
)
from .logging_setup import get_logger, log_parse_error

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# Regex Patterns
# ══════════════════════════════════════════════════════════════════════════

RE_HEADER = re.compile(r'SDK(V[\d.]+)-(\w+)-Type(\d+)')
RE_LACROSSE = re.compile(r'Lacrosse\s+yawLim([\d.]+)\s+areaTH(\d+)\s+pitchInit([\d.]+)')
RE_FRAME = re.compile(r'Frame(\d+)\s+SZ(\d+)\s+Yaw([-\d.]+)\s+Pit([-\d.]+)\s+fps([\d.]+)')
RE_AFILTER = re.compile(r'[AF]FilterP(\d+)\s+mot(\d+)')
RE_DEQUE = re.compile(
    r'Deque(\d+)\(V([-\d.]+),x([-\d.]+)\)'
    r'\(V([-\d.]+),x([-\d.]+)\)'
    r'\(V([-\d.]+),x([-\d.]+)\)'
)
RE_FAST = re.compile(r'Fast(\d+)')
RE_CROWDX = re.compile(r'Crowdx([-\d.]+)')
RE_FIN = re.compile(r'FIN:x([-\d.]+)\s+V([-\d.]+)')
RE_CENTER = re.compile(r'(?:centerResX|autoCenterX)([-\d.]+)')
RE_ZOOM = re.compile(r'Zoom:CPSz(\d+)')
RE_TIMESTAMP = re.compile(r'UTC(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)')


# ══════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedTrack:
    """Result of parsing a FALCON .track file.
    
    Contains the structured point list and derived metadata/summary.
    """
    points: List[TrackPoint] = field(default_factory=list)
    metadata: GameMetadata = field(default_factory=GameMetadata)
    summary: Optional[TrackSummary] = None
    
    def __repr__(self) -> str:
        n = len(self.points)
        dur = self.metadata.total_duration_sec
        return f"ParsedTrack(frames={n}, duration={dur:.1f}s, sport={self.metadata.sport})"


def parse_track_file(filepath: Path | str, *, compute_summary: bool = True) -> ParsedTrack:
    """Parse a FALCON .track file into structured domain models.
    
    Args:
        filepath: Path to the .track file
        compute_summary: Whether to compute aggregate statistics (default True)
    
    Returns:
        ParsedTrack with points list, metadata, and optional summary
    
    Raises:
        FileNotFoundError: If filepath doesn't exist
        ValueError: If the file contains no parseable frames
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Track file not found: {path}")
    
    log.info(f"parsing track file: {path.name}", extra={"file": str(path)})
    
    points: List[TrackPoint] = []
    metadata = GameMetadata(track_file=str(path))
    
    with open(path, 'r') as f:
        lines = f.readlines()
    
    # ── Parse header (first ~20 lines) ──
    _parse_header(lines[:20], metadata)
    
    # ── Parse frames ──
    t0_sec: Optional[float] = None
    last_utc = ""
    current: Optional[TrackPoint] = None
    
    for line_num, line in enumerate(lines, start=1):
        # UTC timestamp line — marks start of a new frame block
        utc_match = RE_TIMESTAMP.search(line)
        if utc_match:
            if current is not None:
                points.append(current)
            
            utc_str = utc_match.group(1)
            current = TrackPoint(frame_num=0, timestamp_sec=0.0, raw_utc=utc_str)
            
            # Parse UTC → seconds offset
            try:
                dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S.%f")
                if t0_sec is None:
                    t0_sec = dt.timestamp()
                current.timestamp_sec = dt.timestamp() - t0_sec
            except ValueError:
                pass
            continue
        
        if current is None:
            continue
        
        # Frame line: Frame{N} SZ{N} Yaw{N} Pit{N} fps{N}
        fm = RE_FRAME.search(line)
        if fm:
            try:
                current.frame_num = int(fm.group(1))
                current.zoom_level = int(fm.group(2))
                current.yaw = float(fm.group(3))
                current.pitch = float(fm.group(4))
                current.fps = float(fm.group(5))
            except (ValueError, IndexError) as e:
                log_parse_error(log, current.frame_num, "frame_header",
                                "Frame{N} SZ{N} Yaw{N} Pit{N} fps{N}", line.strip(), line)
            continue
        
        # [AF]FilterP{N} mot{N}
        am = RE_AFILTER.search(line)
        if am:
            try:
                current.objects_detected = int(am.group(1))
                current.motion_objects = int(am.group(2))
            except (ValueError, IndexError):
                pass
            continue
        
        # Deque{N}(V{v},x{x})(V{v},x{x})(V{v},x{x})
        dm = RE_DEQUE.search(line)
        if dm:
            # Store raw fields for debugging; we don't model individual
            # tracked objects in TrackPoint yet (Phase 2 expansion point)
            current.raw_fields["deque_count"] = dm.group(1)
            current.raw_fields["obj1_v"] = dm.group(2)
            current.raw_fields["obj1_x"] = dm.group(3)
            current.raw_fields["obj2_v"] = dm.group(4)
            current.raw_fields["obj2_x"] = dm.group(5)
            current.raw_fields["obj3_v"] = dm.group(6)
            current.raw_fields["obj3_x"] = dm.group(7)
            continue
        
        # Fast{N} — activity level 0-4
        fm_fast = RE_FAST.search(line)
        if fm_fast and 'Fast' in line[:10]:
            try:
                fast_val = int(fm_fast.group(1))
                current.activity_score = fast_val / 4.0  # Normalize 0-4 → 0.0-1.0
            except ValueError:
                pass
            continue
        
        # Crowdx{N}
        cm = RE_CROWDX.search(line)
        if cm:
            try:
                current.crowd_x = float(cm.group(1))
            except ValueError:
                pass
            continue
        
        # FIN:x{N} V{N}
        fin_m = RE_FIN.search(line)
        if fin_m:
            try:
                current.center_speed = float(fin_m.group(2))  # Velocity
                current.raw_fields["fin_x"] = fin_m.group(1)
            except ValueError:
                pass
            continue
        
        # centerResX or autoCenterX
        cen_m = RE_CENTER.search(line)
        if cen_m:
            try:
                current.center_x = float(cen_m.group(1))
            except ValueError:
                pass
            continue
        
        # Zoom:CPSz{N}
        zm = RE_ZOOM.search(line)
        if zm:
            try:
                current.zoom_level = int(zm.group(1))
            except ValueError:
                pass
            continue
    
    # Don't forget the last frame
    if current is not None:
        points.append(current)
    
    if not points:
        raise ValueError(f"No frames found in track file: {path}")
    
    # ── Compute metadata ──
    metadata.total_frames = len(points)
    metadata.total_duration_sec = points[-1].timestamp_sec
    if points[0].fps > 0:
        metadata.video_fps = points[0].fps
    
    result = ParsedTrack(points=points, metadata=metadata)
    
    # ── Compute summary ──
    if compute_summary:
        result.summary = _compute_summary(points, metadata)
    
    log.info(
        f"parsed {len(points)} frames in {metadata.total_duration_sec:.1f}s",
        extra={
            "file": str(path),
            "frames": len(points),
            "duration_sec": metadata.total_duration_sec,
            "version": metadata.track_version,
        },
    )
    
    return result


# ══════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ══════════════════════════════════════════════════════════════════════════

def _parse_header(header_lines: List[str], metadata: GameMetadata) -> None:
    """Extract metadata from the track file header."""
    for line in header_lines:
        hm = RE_HEADER.search(line)
        if hm:
            metadata.track_version = f"{hm.group(1)}-{hm.group(2)}-Type{hm.group(3)}"
        
        lm = RE_LACROSSE.search(line)
        if lm:
            metadata.sport = "lacrosse"
            metadata.extra["yaw_limit"] = lm.group(1)
            metadata.extra["area_threshold"] = lm.group(2)
            metadata.extra["pitch_init"] = lm.group(3)


def _compute_summary(points: List[TrackPoint], metadata: GameMetadata) -> TrackSummary:
    """Compute aggregate statistics from parsed track points."""
    total = len(points)
    
    active = sum(1 for p in points if p.activity_score >= 0.5)
    intense = sum(1 for p in points if p.activity_score >= 0.75)
    
    avg_objects = sum(p.objects_detected for p in points) / max(total, 1)
    max_objects = max((p.objects_detected for p in points), default=0)
    avg_speed = sum(abs(p.center_speed) for p in points) / max(total, 1)
    
    # Detect activity windows
    windows = _detect_activity_windows(points)
    
    return TrackSummary(
        total_frames=total,
        duration_sec=metadata.total_duration_sec,
        active_frames=active,
        intense_frames=intense,
        activity_pct=round(active / max(total, 1) * 100, 1),
        avg_objects_per_frame=round(avg_objects, 1),
        max_objects=max_objects,
        avg_center_speed=round(avg_speed, 1),
        active_windows=windows,
        camera_version=metadata.track_version,
        metadata=metadata.extra,
    )


def _detect_activity_windows(
    points: List[TrackPoint],
    threshold: float = 0.5,
    min_duration_sec: float = 1.5,
) -> List[ActivityWindow]:
    """Segment track into active/inactive windows based on activity threshold.
    
    Args:
        points: Track points in temporal order
        threshold: Activity score threshold for considering a frame "active"
        min_duration_sec: Minimum duration for a window to be included
    
    Returns:
        List of ActivityWindow objects for periods exceeding threshold
    """
    windows: List[ActivityWindow] = []
    
    in_active = False
    win_start = 0.0
    win_frames: List[TrackPoint] = []
    
    for p in points:
        is_active = p.activity_score >= threshold
        
        if is_active and not in_active:
            win_start = p.timestamp_sec
            win_frames = [p]
            in_active = True
        elif is_active and in_active:
            win_frames.append(p)
        elif not is_active and in_active:
            duration = p.timestamp_sec - win_start
            if duration >= min_duration_sec:
                scores = [f.activity_score for f in win_frames]
                peak_idx = scores.index(max(scores)) if scores else 0
                windows.append(ActivityWindow(
                    start_time_sec=win_start,
                    end_time_sec=p.timestamp_sec,
                    peak_time_sec=win_frames[peak_idx].timestamp_sec if win_frames else win_start,
                    peak_score=max(scores) if scores else 0.0,
                    avg_score=sum(scores) / len(scores) if scores else 0.0,
                    frame_count=len(win_frames),
                ))
            in_active = False
            win_frames = []
    
    # Handle window that extends to end of track
    if in_active and win_frames:
        end_time = points[-1].timestamp_sec
        duration = end_time - win_start
        if duration >= min_duration_sec:
            scores = [f.activity_score for f in win_frames]
            peak_idx = scores.index(max(scores)) if scores else 0
            windows.append(ActivityWindow(
                start_time_sec=win_start,
                end_time_sec=end_time,
                peak_time_sec=win_frames[peak_idx].timestamp_sec if win_frames else win_start,
                peak_score=max(scores) if scores else 0.0,
                avg_score=sum(scores) / len(scores) if scores else 0.0,
                frame_count=len(win_frames),
            ))
    
    return windows


# ══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point: parse a .track file and print summary."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Parse a FALCON .track file and print summary",
    )
    parser.add_argument("track_file", help="Path to .track file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--no-summary", action="store_true", help="Skip summary computation")
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")
    args = parser.parse_args()
    
    from telemetry.logging_setup import configure_logging
    configure_logging(level="DEBUG" if args.debug else "INFO")
    
    result = parse_track_file(args.track_file, compute_summary=not args.no_summary)
    
    if args.json and result.summary:
        import json
        from dataclasses import asdict
        print(json.dumps(asdict(result.summary), indent=2, default=str))
    else:
        print(f"Frames: {len(result.points)}")
        print(f"Duration: {result.metadata.total_duration_sec:.1f}s")
        print(f"Version: {result.metadata.track_version}")
        if result.summary:
            print(f"Active: {result.summary.activity_pct}% ({result.summary.active_frames}/{result.summary.total_frames} frames)")
            print(f"Intense: {result.summary.intense_frames} frames")
            print(f"Activity windows: {len(result.summary.active_windows)}")
            print(f"Avg objects/frame: {result.summary.avg_objects_per_frame}")
            print(f"Max objects: {result.summary.max_objects}")
            print(f"Avg center speed: {result.summary.avg_center_speed:.1f}")


if __name__ == "__main__":
    main()
