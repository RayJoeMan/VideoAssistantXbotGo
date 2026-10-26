"""Dual-export driver — one project, every deliverable (Session 3).

    python -m highlight.export project.json OUTDIR [--only a,b] [--fps N]

renders, from the one project file (spec Feature 6):

  * ``<stem>-recruiting.mp4`` — the Session 1+2 spotlight cut at the
    "recruiting" preset's size (ring, beats, VO mix, burned
    captions), plus the player end card when the project carries
    player info;
  * ``<stem>-clean.mp4`` — the untouched FULL source game for
    SportsRecruits: no window trim, no overlays, no VO, no cards.
    Stream-copied; re-encoded only when a straight copy does not
    probe sane.  (The "clean" preset's stored size is nominal — a
    clean copy keeps the source's own dimensions by definition.)
  * ``<stem>-vertical.mp4`` — the "Lacrosse IQ with Abby" short at
    the "vertical" preset's size: a 1 s title card, the play
    reframed by a moving 9:16 crop that follows the spotlight
    subject, and a series end card.

The vertical reframe reuses the renderer's machinery: the crop path
comes from the same position provider that places the ring
(telemetry-compensated when the project names a track), sampled on
the OUTPUT timeline so slow-mo and freezes hold the crop where the
play holds, then box-smoothed — a crop that chases every frame's
jitter looks seasick.  ffmpeg executes the path with sendcmd-driven
crop updates (one command per offset change); the overlay frames are
rasterized in cropped coordinates via render.CropReframe.

Every output is ffprobe-verified by the driver itself (dimensions,
duration, streams) and reported per export; a failure in one export
is reported in its result and makes the CLI exit non-zero — a broken
export never passes silently.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from telemetry.logging_setup import get_logger

from .audio import (
    SAMPLE_RATE,
    build_mix_filters,
    build_take_filter,
    probe_duration,
    silence_bed_filter,
    take_spans,
)
from .captions import write_srt
from .cards import (
    END_CARD_S,
    TITLE_CARD_S,
    recruiting_end_card_lines,
    render_card_png,
    vertical_end_card_lines,
    vertical_title_card_lines,
)
from .project import CaptionCue, HighlightProject, load_project
from .render import (
    FRAME_NAME_PATTERN,
    CropReframe,
    build_position_provider,
    build_segment_audio_filters,
    build_segment_video_filters,
    probe_has_audio,
    render_duration,
    render_project,
    write_overlay_frames,
)
from .timeline import Timeline, build_timeline

log = get_logger(__name__)

RECRUITING = "recruiting"
CLEAN = "clean"
VERTICAL = "vertical"
EXPORT_NAMES = (RECRUITING, CLEAN, VERTICAL)

DURATION_TOLERANCE_S = 0.6        # rendered outputs vs their timeline math
CLEAN_DURATION_TOLERANCE_S = 2.0  # stream-copy container durations wobble
SMOOTH_S = 0.75                   # crop-path smoothing window, seconds


# ══════════════════════════════════════════════════════════════════════════
# Probing + verification
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class MediaInfo:
    """The ffprobe facts the driver verifies against."""

    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    video_codec: Optional[str] = None
    has_video: bool = False
    has_audio: bool = False


def probe_media(path, ffprobe_bin: str = "ffprobe") -> MediaInfo:
    """Probe *path*; an unprobeable file yields an all-empty MediaInfo."""
    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "error",
                "-show_entries", "stream=codec_type,codec_name,width,height",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)
    except Exception:
        return MediaInfo()
    info = MediaInfo()
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = stream.get("codec_name")
            info.width = stream.get("width")
            info.height = stream.get("height")
        elif stream.get("codec_type") == "audio":
            info.has_audio = True
    try:
        info.duration = float(data["format"]["duration"])
    except Exception:
        info.duration = None
    return info


def verify_output(
    path,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[float] = None,
    duration_tol: float = DURATION_TOLERANCE_S,
    need_audio: Optional[bool] = None,
    ffprobe_bin: str = "ffprobe",
) -> List[str]:
    """Problems found in the output at *path* (empty list = verified).

    Only the expectations given are checked.  ``need_audio`` True
    requires an audio stream, False forbids one, None skips the
    audio check.
    """
    out = Path(path)
    if not out.exists() or out.stat().st_size == 0:
        return ["output file missing or empty"]
    info = probe_media(out, ffprobe_bin)
    problems: List[str] = []
    if not info.has_video:
        problems.append("no video stream")
    if width is not None and info.width != width:
        problems.append(f"width {info.width} != expected {width}")
    if height is not None and info.height != height:
        problems.append(f"height {info.height} != expected {height}")
    if duration is not None:
        if info.duration is None:
            problems.append("duration could not be probed")
        elif abs(info.duration - duration) > duration_tol:
            problems.append(
                f"duration {info.duration:.2f}s != expected "
                f"{duration:.2f}s (±{duration_tol:.1f}s)"
            )
    if need_audio is True and not info.has_audio:
        problems.append("expected an audio stream, found none")
    if need_audio is False and info.has_audio:
        problems.append("unexpected audio stream")
    return problems


# ══════════════════════════════════════════════════════════════════════════
# Vertical crop path (pure)
# ══════════════════════════════════════════════════════════════════════════

def crop_dimensions(
    src_width: int, src_height: int, out_width: int, out_height: int
):
    """Largest (crop_w, crop_h) of the output's aspect inside the source.

    Dimensions are even (4:2:0 chroma) and never exceed the source.
    """
    target = out_width / float(out_height)
    if src_width / float(src_height) > target:
        crop_h = src_height - (src_height % 2)
        crop_w = int(round(crop_h * target / 2.0)) * 2
    else:
        crop_w = src_width - (src_width % 2)
        crop_h = int(round(crop_w / target / 2.0)) * 2
    crop_w = min(crop_w, src_width - (src_width % 2))
    crop_h = min(crop_h, src_height - (src_height % 2))
    if crop_w <= 0 or crop_h <= 0:
        raise ValueError(
            f"source {src_width}x{src_height} too small for a "
            f"{out_width}x{out_height} crop"
        )
    return crop_w, crop_h


def _smooth_centers(centers, window: int):
    """Box-average (x, y) centers over ±window//2 samples, edges clamped."""
    if window <= 1 or len(centers) < 3:
        return list(centers)
    half = window // 2
    n = len(centers)
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        sx = sum(c[0] for c in centers[lo:hi])
        sy = sum(c[1] for c in centers[lo:hi])
        out.append((sx / (hi - lo), sy / (hi - lo)))
    return out


def subject_crop_offsets(
    project: HighlightProject,
    timeline: Timeline,
    provider,
    src_width: int,
    src_height: int,
    out_width: int,
    out_height: int,
    fps: int,
    smooth_s: float = SMOOTH_S,
):
    """Per-output-frame crop offsets following the spotlight subject.

    Returns ``(offsets, (crop_w, crop_h))``; offsets are (x, y)
    top-lefts in source pixels, even-snapped and clamped so the
    window never leaves the frame.  Subject positions are the
    position provider's, sampled through the output timeline (beats
    included) and box-smoothed over ±``smooth_s`` seconds.
    """
    crop_w, crop_h = crop_dimensions(src_width, src_height, out_width, out_height)
    count = int(round(timeline.duration * fps))
    centers = []
    for i in range(count):
        t_src = timeline.source_time_at_output(i / float(fps))
        nx, ny, _scale = provider(t_src)
        centers.append(
            (
                min(max(nx, 0.0), 1.0) * src_width,
                min(max(ny, 0.0), 1.0) * src_height,
            )
        )
    smoothed = _smooth_centers(centers, max(1, int(round(smooth_s * fps))))
    offsets = []
    for cx, cy in smoothed:
        x = min(max(cx - crop_w / 2.0, 0.0), max(src_width - crop_w, 0))
        y = min(max(cy - crop_h / 2.0, 0.0), max(src_height - crop_h, 0))
        offsets.append((int(round(x / 2.0)) * 2, int(round(y / 2.0)) * 2))
    return offsets, (crop_w, crop_h)


def write_crop_commands(offsets: Sequence, fps: int, path) -> Path:
    """Write the sendcmd file that executes a crop path in ffmpeg.

    One line per component change (frames where the window holds
    still emit nothing), in the form ``12.033 crop x 512;`` — the
    crop filter picks each command up at its timestamp.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    prev = None
    for i, (x, y) in enumerate(offsets):
        t = i / float(fps)
        if prev is None or x != prev[0]:
            lines.append(f"{t:.3f} crop x {x};")
        if prev is None or y != prev[1]:
            lines.append(f"{t:.3f} crop y {y};")
        prev = (x, y)
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out


# ══════════════════════════════════════════════════════════════════════════
# ffmpeg command construction (pure)
# ══════════════════════════════════════════════════════════════════════════

def build_concat_card_command(
    content_path,
    card_png,
    output_path,
    width: int,
    height: int,
    fps: int,
    card_s: float,
    content_duration: float,
    has_audio: bool,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """Append a still card (PNG, looped for *card_s*) to a rendered cut.

    When the content has audio, the card's span gets a silence bed so
    the concat keeps one continuous audio stream.
    """
    graph = [
        f"[0:v]fps={fps},setsar=1,format=yuv420p[v0]",
        f"[1:v]fps={fps},scale={width}:{height},setsar=1,format=yuv420p[v1]",
        "[v0][v1]concat=n=2:v=1:a=0[vout]",
    ]
    if has_audio:
        graph += [
            f"[0:a]aresample={SAMPLE_RATE}[a0]",
            f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
            f"atrim=0:{card_s:.3f},asetpts=PTS-STARTPTS[a1]",
            "[a0][a1]concat=n=2:v=0:a=1[aout]",
        ]
    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(content_path),
        "-loop", "1", "-t", f"{card_s:.3f}", "-i", str(card_png),
        "-filter_complex", ";".join(graph),
        "-map", "[vout]",
    ]
    if has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-t", f"{content_duration + card_s:.3f}",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


def build_vertical_command(
    project: HighlightProject,
    frames_dir,
    crop_cmds_path,
    title_png,
    end_png,
    output_path,
    src_width: int,
    src_height: int,
    out_width: int,
    out_height: int,
    fps: int,
    timeline: Timeline,
    crop_w: int,
    crop_h: int,
    first_offset,
    has_audio: bool,
    take_durations,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """The full argv for the vertical short.

    Inputs: 0 = window-trimmed source, 1 = overlay PNG sequence,
    2 = title card (looped 1 s), 3 = end card (looped), 4.. = the VO
    takes in project order.  Video: [title][content][end] concat;
    the content is the Session 1/2 base (segment chains when beats
    are present, the freeze-intro head otherwise) run through the
    sendcmd-driven moving crop, scaled to the preset, with the
    overlay composited in cropped coordinates.  Audio mirrors
    render.build_effects_ffmpeg_command's mix, padded with silence
    under both cards, so the short always carries one audio stream.
    """
    takes = project.voiceover.takes if project.voiceover is not None else []
    graph: List[str] = []
    if project.beats:
        graph += build_segment_video_filters(
            project, timeline, src_width, src_height, fps
        )
        if has_audio:
            graph += build_segment_audio_filters(project, timeline)
    else:
        graph.append(
            f"[0:v]tpad=start_mode=clone:start_duration={project.freeze_intro_s:.3f},"
            f"fps={fps},setsar=1[base]"
        )
        if has_audio:
            delay_ms = int(round(project.freeze_intro_s * 1000))
            graph.append(
                f"[0:a]adelay={delay_ms}:all=1,aresample={SAMPLE_RATE}[game_a]"
            )
    x0, y0 = first_offset
    graph.append(
        f"[base]sendcmd=f={crop_cmds_path},crop={crop_w}:{crop_h}:{x0}:{y0}[cropped]"
    )
    graph.append(
        f"[cropped]scale={out_width}:{out_height}:flags=lanczos,setsar=1[vcrop]"
    )
    graph.append("[vcrop][1:v]overlay=0:0:format=auto,format=yuv420p[vcontent]")
    graph.append(
        f"[2:v]fps={fps},scale={out_width}:{out_height},setsar=1,"
        f"format=yuv420p[titlev]"
    )
    graph.append(
        f"[3:v]fps={fps},scale={out_width}:{out_height},setsar=1,"
        f"format=yuv420p[endv]"
    )
    graph.append("[titlev][vcontent][endv]concat=n=3:v=1:a=0[vfinal]")

    content_audio = None
    if takes:
        if not has_audio:
            graph.append(silence_bed_filter(timeline.duration, "game_a"))
        vo_labels = []
        for i, take in enumerate(takes):
            label = f"vo{i}"
            graph.append(build_take_filter(4 + i, take, label))
            vo_labels.append(label)
        spans = take_spans(takes, take_durations, timeline.duration)
        graph.append(
            build_mix_filters(
                "game_a",
                vo_labels,
                spans,
                project.voiceover.duck_db,
                project.voiceover.target_lufs,
            )
        )
        content_audio = "aout"
    elif has_audio:
        content_audio = "game_a"

    graph.append(
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
        f"atrim=0:{TITLE_CARD_S:.3f},asetpts=PTS-STARTPTS[asil_t]"
    )
    if content_audio is None:
        graph.append(
            f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
            f"atrim=0:{timeline.duration:.3f},asetpts=PTS-STARTPTS[asil_c]"
        )
        content_audio = "asil_c"
    graph.append(
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
        f"atrim=0:{END_CARD_S:.3f},asetpts=PTS-STARTPTS[asil_e]"
    )
    graph.append(f"[asil_t][{content_audio}][asil_e]concat=n=3:v=0:a=1[afinal]")

    total = TITLE_CARD_S + timeline.duration + END_CARD_S
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{project.window.start:.3f}",
        "-t", f"{project.window.duration:.3f}",
        "-i", str(project.source_video),
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", str(Path(frames_dir) / FRAME_NAME_PATTERN),
        "-loop", "1", "-t", f"{TITLE_CARD_S:.3f}", "-i", str(title_png),
        "-loop", "1", "-t", f"{END_CARD_S:.3f}", "-i", str(end_png),
    ]
    for take in takes:
        cmd += ["-i", str(take.file)]
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", "[vfinal]",
        "-map", "[afinal]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


# ══════════════════════════════════════════════════════════════════════════
# Export renderers (subprocess)
# ══════════════════════════════════════════════════════════════════════════

def _run_ffmpeg(cmd: List[str], what: str) -> None:
    log.info("%s: %s", what, " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.splitlines()[-15:])
        raise RuntimeError(f"{what} failed (rc={result.returncode}):\n{tail}")


def render_clean(
    project: HighlightProject,
    output_path,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> str:
    """The clean full-game export; returns the method that verified.

    Tries a stream copy first (the honest untouched game); if the
    copy errors or does not probe as the same game, falls back to a
    re-encode.  Raises RuntimeError when neither produces output.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = probe_media(project.source_video, ffprobe_bin)

    def _verified() -> bool:
        return not verify_output(
            out,
            width=src.width,
            height=src.height,
            duration=src.duration,
            duration_tol=CLEAN_DURATION_TOLERANCE_S,
            need_audio=src.has_audio,
            ffprobe_bin=ffprobe_bin,
        )

    copy_cmd = [
        ffmpeg_bin, "-y",
        "-i", str(project.source_video),
        "-map", "0:v:0", "-map", "0:a?",
        "-c", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    result = subprocess.run(copy_cmd, capture_output=True, text=True)
    if result.returncode == 0 and _verified():
        return "stream copy"
    if result.returncode != 0:
        log.warning(
            "clean stream copy failed (rc=%s); falling back to re-encode",
            result.returncode,
        )
    reencode_cmd = [
        ffmpeg_bin, "-y",
        "-i", str(project.source_video),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]
    _run_ffmpeg(reencode_cmd, "clean re-encode")
    return "re-encode"


def _render_recruiting(
    project: HighlightProject,
    out_path,
    work_dir: Path,
    fps: int,
    ffprobe_bin: str,
    ffmpeg_bin: str,
) -> str:
    content = work_dir / "recruiting-content.mp4"
    render_project(project, content, preset_name=RECRUITING, fps=fps)
    info = probe_media(content, ffprobe_bin)
    lines = recruiting_end_card_lines(project)
    if not lines:
        shutil.move(str(content), str(out_path))
        detail = "no end card (project carries no player info)"
    else:
        preset = project.preset(RECRUITING)
        card_png = render_card_png(
            lines, work_dir / "recruiting-end-card.png", preset.width, preset.height
        )
        cmd = build_concat_card_command(
            content,
            card_png,
            out_path,
            preset.width,
            preset.height,
            fps,
            END_CARD_S,
            info.duration or render_duration(project),
            bool(info.has_audio),
            ffmpeg_bin,
        )
        _run_ffmpeg(cmd, "recruiting end-card concat")
        detail = "spotlight cut + end card"
    sidecar = content.with_suffix(".srt")
    if sidecar.exists():
        shutil.move(str(sidecar), str(Path(out_path).with_suffix(".srt")))
    return detail


def _render_vertical(
    project: HighlightProject,
    out_path,
    work_dir: Path,
    fps: int,
    ffprobe_bin: str,
    ffmpeg_bin: str,
) -> str:
    preset = project.preset(VERTICAL)
    out_w, out_h = preset.width, preset.height
    src = probe_media(project.source_video, ffprobe_bin)
    if not src.has_video or src.width is None or src.height is None:
        raise ValueError(
            f"source video could not be probed: {project.source_video}"
        )
    timeline = build_timeline(
        project.window.start,
        project.window.end,
        project.freeze_intro_s,
        project.beats,
    )
    provider, mode = build_position_provider(project, src.width / float(src.height))
    offsets, (crop_w, crop_h) = subject_crop_offsets(
        project, timeline, provider, src.width, src.height, out_w, out_h, fps
    )
    reframe = CropReframe(src.width, src.height, crop_w, crop_h, offsets)
    frames_dir = work_dir / "vertical-frames"
    count = write_overlay_frames(
        project, frames_dir, out_w, out_h, fps,
        provider=provider, timeline=timeline, reframe=reframe,
    )
    log.info("vertical: rasterized %d overlay frames at %dx%d", count, out_w, out_h)
    cmds_path = write_crop_commands(offsets, fps, work_dir / "crop-commands.txt")
    title_png = render_card_png(
        vertical_title_card_lines(project), work_dir / "title-card.png", out_w, out_h
    )
    end_png = render_card_png(
        vertical_end_card_lines(project), work_dir / "end-card.png", out_w, out_h
    )
    has_audio = probe_has_audio(project.source_video, ffprobe_bin)
    takes = project.voiceover.takes if project.voiceover is not None else []
    take_durations = []
    for take in takes:
        if not Path(take.file).exists():
            raise ValueError(f"voiceover take file not found: {take.file}")
        take_durations.append(probe_duration(take.file, ffprobe_bin))
    cmd = build_vertical_command(
        project, frames_dir, cmds_path, title_png, end_png, out_path,
        src.width, src.height, out_w, out_h, fps, timeline,
        crop_w, crop_h, offsets[0] if offsets else (0, 0),
        has_audio, take_durations, ffmpeg_bin,
    )
    _run_ffmpeg(cmd, "vertical render")
    if project.captions:
        shifted = [
            CaptionCue(c.start + TITLE_CARD_S, c.end + TITLE_CARD_S, c.text)
            for c in project.captions
        ]
        write_srt(shifted, Path(out_path).with_suffix(".srt"))
    return f"title card + subject-follow reframe ({mode}) + end card"


# ══════════════════════════════════════════════════════════════════════════
# Driver + report
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ExportResult:
    """One export's outcome: verified, or the problems found."""

    name: str
    path: Path
    ok: bool
    problems: List[str] = field(default_factory=list)
    info: Optional[MediaInfo] = None
    detail: str = ""


@dataclass
class ExportReport:
    """Every export's result; ``ok`` only when all of them verified."""

    results: List[ExportResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def result(self, name: str) -> ExportResult:
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(name)

    def summary_lines(self) -> List[str]:
        lines = []
        for r in self.results:
            status = "OK  " if r.ok else "FAIL"
            dims = (
                f"{r.info.width}x{r.info.height}"
                if r.info and r.info.width
                else "?x?"
            )
            dur = f"{r.info.duration:.2f}s" if r.info and r.info.duration else "?s"
            line = f"{r.name}: {status} {r.path} ({dims}, {dur})"
            if r.detail:
                line += f" — {r.detail}"
            lines.append(line)
            for problem in r.problems:
                lines.append(f"  ! {problem}")
        return lines


def _verify_export(
    name: str,
    project: HighlightProject,
    path,
    src_info: MediaInfo,
    ffprobe_bin: str,
) -> List[str]:
    if name == RECRUITING:
        preset = project.preset(RECRUITING)
        expected = render_duration(project)
        if recruiting_end_card_lines(project):
            expected += END_CARD_S
        takes = project.voiceover.takes if project.voiceover is not None else []
        need_audio = True if (src_info.has_audio or takes) else None
        return verify_output(
            path,
            width=preset.width,
            height=preset.height,
            duration=expected,
            need_audio=need_audio,
            ffprobe_bin=ffprobe_bin,
        )
    if name == CLEAN:
        return verify_output(
            path,
            width=src_info.width,
            height=src_info.height,
            duration=src_info.duration,
            duration_tol=CLEAN_DURATION_TOLERANCE_S,
            need_audio=src_info.has_audio,
            ffprobe_bin=ffprobe_bin,
        )
    preset = project.preset(VERTICAL)
    return verify_output(
        path,
        width=preset.width,
        height=preset.height,
        duration=TITLE_CARD_S + render_duration(project) + END_CARD_S,
        need_audio=True,
        ffprobe_bin=ffprobe_bin,
    )


def export_project(
    project: HighlightProject,
    out_dir,
    stem: str = "project",
    names: Optional[Sequence[str]] = None,
    fps: int = 30,
    keep_work: bool = False,
    ffmpeg_bin: Optional[str] = None,
    ffprobe_bin: Optional[str] = None,
) -> ExportReport:
    """Render + verify the selected exports of *project* into *out_dir*.

    Files land as ``<stem>-<export>.mp4``.  Each export runs in its
    own try/except: one export's failure is recorded in its result
    (and fails the report) without taking the others down.
    """
    from export.ffmpeg import resolve_tool  # lazy: keeps builder imports light

    ffmpeg_bin = ffmpeg_bin or resolve_tool("ffmpeg")
    ffprobe_bin = ffprobe_bin or resolve_tool("ffprobe")
    selected = list(names) if names else list(EXPORT_NAMES)
    unknown = [n for n in selected if n not in EXPORT_NAMES]
    if unknown:
        raise ValueError(
            f"unknown export(s) {unknown}; have {list(EXPORT_NAMES)}"
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="lva_export_"))
    report = ExportReport()
    try:
        src_info = probe_media(project.source_video, ffprobe_bin)
        for name in selected:
            path = out / f"{stem}-{name}.mp4"
            try:
                if name == RECRUITING:
                    detail = _render_recruiting(
                        project, path, work_dir, fps, ffprobe_bin, ffmpeg_bin
                    )
                elif name == CLEAN:
                    detail = render_clean(project, path, ffmpeg_bin, ffprobe_bin)
                else:
                    detail = _render_vertical(
                        project, path, work_dir, fps, ffprobe_bin, ffmpeg_bin
                    )
                problems = _verify_export(name, project, path, src_info, ffprobe_bin)
                report.results.append(
                    ExportResult(
                        name, path, not problems, problems,
                        probe_media(path, ffprobe_bin), detail,
                    )
                )
            except Exception as exc:  # one export must not sink the others
                report.results.append(
                    ExportResult(
                        name, path, False,
                        [f"{type(exc).__name__}: {exc}"],
                        probe_media(path, ffprobe_bin),
                    )
                )
    finally:
        if not keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lva-highlight-export",
        description="Render every export of a highlight project in one command.",
    )
    parser.add_argument("project", help="path to project.json")
    parser.add_argument("out_dir", help="directory for the exported .mp4 files")
    parser.add_argument(
        "--only",
        default=None,
        help="comma-separated subset of: " + ",".join(EXPORT_NAMES),
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--keep-work", action="store_true",
        help="keep the intermediate work directory (frames, cards, content)",
    )
    args = parser.parse_args(argv)

    project = load_project(args.project)
    names = (
        [n.strip() for n in args.only.split(",") if n.strip()]
        if args.only
        else None
    )
    report = export_project(
        project,
        args.out_dir,
        stem=Path(args.project).stem,
        names=names,
        fps=args.fps,
        keep_work=args.keep_work,
    )
    for line in report.summary_lines():
        print(line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
