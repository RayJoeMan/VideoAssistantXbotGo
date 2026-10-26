"""Spotlight renderer — turn a HighlightProject into pixels (Tier 1).

Approach: per-frame RGBA overlay images + one ffmpeg overlay pass.

The ring must be a true ellipse with soft edges, the dim mask must fade
softly around it, and the "#25" tag must be typeset — none of which
ffmpeg's drawbox/geq expressions do cleanly for a *moving* target.  So
each output frame's overlay is rasterized in numpy/PIL from the
interpolated keyframe position (only the region around the ellipse is
computed; the rest of the frame is a flat dim alpha), written as a PNG
sequence, and composited by a single ffmpeg pass:

    [0:v] scale -> tpad (freeze-intro clone) -> fps -> [base]
    [base][1:v] overlay -> format=yuv420p

Separation of concerns, for testability:
  * ``build_ffmpeg_command`` is a pure function of the project.
  * ``overlay_frame_rgba`` is a pure function of (project, frame index).
  * Only ``render_project`` touches subprocess and the disk beyond the
    overlay frames themselves.

Ring positions come from a position provider (see
``build_position_provider``): telemetry-compensated interpolation
when the project names a Falcon .track file, plain frame-space
interpolation otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from telemetry.logging_setup import get_logger

from .project import HighlightProject, load_project
from .tracking import (
    DEFAULT_FOV_X_DEG,
    CameraCalibration,
    CompensatedInterpolator,
    load_camera_track,
    position_at,
)
from .audio import (
    SAMPLE_RATE,
    build_mix_filters,
    build_take_filter,
    probe_duration,
    silence_bed_filter,
    take_spans,
)
from .captions import wrap_caption_lines, write_srt
from .timeline import SEG_FREEZE, Timeline, build_timeline

log = get_logger(__name__)

RING_COLOR_RGB = (255, 199, 44)  # warm gold, reads on grass and turf
FRAME_NAME_PATTERN = "ring_%05d.png"

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)

# Dim mask geometry, in units of the ellipse radius r (1.0 = ring edge):
_DIM_CLEAR_R = 1.05   # inside this, no dimming at all
_DIM_FULL_R = 1.75    # outside this, full dim strength


# ══════════════════════════════════════════════════════════════════════════
# Frame timing (pure)
# ══════════════════════════════════════════════════════════════════════════

def freeze_frame_count(project: HighlightProject, fps: int) -> int:
    return int(round(project.freeze_intro_s * fps))


def output_frame_count(project: HighlightProject, fps: int) -> int:
    return int(round(project.output_duration * fps))


def frame_source_time(project: HighlightProject, frame_index: int, fps: int) -> float:
    """Source-video time shown by output frame *frame_index*.

    During the freeze intro the clock is pinned at the window start;
    afterward it advances 1/fps per frame, clamped at the window end.
    """
    clip_t = (frame_index - freeze_frame_count(project, fps)) / float(fps)
    clip_t = min(max(clip_t, 0.0), project.window.duration)
    return project.window.start + clip_t


# ══════════════════════════════════════════════════════════════════════════
# Position provider (telemetry load happens once, up front)
# ══════════════════════════════════════════════════════════════════════════

# A position provider maps source time -> (x, y, rel_scale): the ring
# center in normalized frame coordinates plus the magnification
# relative to the reference state (ring radii scale with it; 1.0 when
# uncompensated or when the camera carries no zoom channel).


def build_position_provider(project: HighlightProject, aspect: float):
    """Return ``(provider, mode)`` for *project*.

    Mode is ``"telemetry-compensated"`` when the project names a
    telemetry track that loads and syncs to the source video, else
    ``"frame-space"`` — plain keyframe interpolation, the pre-compensation
    behavior, used for phone clips and as the safe fallback whenever
    telemetry is missing, unreadable, or cannot be synced (wrong-clock
    compensation would be worse than none).
    """
    if project.telemetry is not None:
        camera = None
        try:
            camera = load_camera_track(
                project.telemetry.track_file, project.source_video
            )
        except Exception as exc:  # missing/corrupt track: fall back, loudly
            log.warning("telemetry track unusable (%s); falling back", exc)
        if camera is not None:
            fov = project.telemetry.pan_fov_deg or DEFAULT_FOV_X_DEG
            interp = CompensatedInterpolator(
                project.keyframes,
                camera,
                CameraCalibration(fov_x_deg=fov),
                aspect,
            )
            log.info(
                "position provider: telemetry-compensated (%d camera samples)",
                len(camera),
            )
            return (
                lambda t: (*interp.position_at(t), interp.scale_at(t)),
                "telemetry-compensated",
            )
        log.warning(
            "telemetry named but no sync could be built; falling back to "
            "frame-space interpolation"
        )
    return (
        lambda t: (*position_at(project.keyframes, t), 1.0),
        "frame-space",
    )


# ══════════════════════════════════════════════════════════════════════════
# Overlay rasterization (pure)
# ══════════════════════════════════════════════════════════════════════════

def _smoothstep_np(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


@lru_cache(maxsize=8)
def _load_font(size: int):
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def overlay_frame_rgba(
    project: HighlightProject,
    frame_index: int,
    width: int,
    height: int,
    fps: int,
    provider=None,
    timeline: Timeline = None,
) -> np.ndarray:
    """The (height, width, 4) uint8 RGBA overlay for one output frame.

    Contents: the dim mask (black, alpha = dim strength far from the
    player, fading to clear inside the ring), the gold ellipse ring at
    the interpolated ground position, and the tag text above the ring.

    Session 2 additions, drawn in the same pass: the burned-in caption
    whose cue covers this frame's OUTPUT time (lower third, max two
    lines), and any callouts whose window covers this frame's SOURCE
    time — a dark text box with a gold leader arrow to the annotated
    keyframe's position.

    *provider* maps source time -> (x, y, rel_scale) and defaults to
    plain frame-space keyframe interpolation; render_project passes a
    telemetry-compensated provider when the project names a track.
    *timeline*, when given, maps this frame through the project's
    beats instead of the Session 1 1:1 rule.
    """
    t_out = frame_index / float(fps)
    if timeline is not None:
        t = timeline.source_time_at_output(t_out)
    else:
        t = frame_source_time(project, frame_index, fps)
    if provider is None:
        nx, ny = position_at(project.keyframes, t)
        rel_scale = 1.0
    else:
        nx, ny, rel_scale = provider(t)
    cx, cy = nx * width, ny * height
    rx = project.ring.rx * width * rel_scale
    ry = project.ring.ry * height * rel_scale

    frame = np.zeros((height, width, 4), dtype=np.uint8)
    dim_alpha = project.dim.strength if project.dim.enabled else 0.0
    if dim_alpha > 0.0:
        frame[:, :, 3] = int(round(dim_alpha * 255))

    # Region of interest: the ellipse plus the dim falloff around it.
    reach_x, reach_y = rx * (_DIM_FULL_R + 0.6), ry * (_DIM_FULL_R + 0.6)
    x0 = max(0, int(math.floor(cx - reach_x)))
    x1 = min(width, int(math.ceil(cx + reach_x)) + 1)
    y0 = max(0, int(math.floor(cy - reach_y)))
    y1 = min(height, int(math.ceil(cy + reach_y)) + 1)
    if x1 > x0 and y1 > y0:
        yy, xx = np.mgrid[y0:y1, x0:x1]
        r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        alpha = np.full(r.shape, dim_alpha, dtype=np.float64)
        if dim_alpha > 0.0:
            clear = 1.0 - _smoothstep_np((r - _DIM_CLEAR_R) / (_DIM_FULL_R - _DIM_CLEAR_R))
            alpha = dim_alpha * (1.0 - clear)
        # Ring: solid core ~3 px, soft glow out to ~12 px (pixel distance
        # to the ellipse edge, approximated with the smaller radius).
        d = np.abs(r - 1.0) * min(rx, ry)
        core = np.clip(1.0 - d / 3.0, 0.0, 1.0)
        glow = np.clip(1.0 - d / 12.0, 0.0, 1.0) * 0.45
        ring_a = np.maximum(core, glow)
        region_rgb = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
        region_rgb[ring_a >= alpha] = RING_COLOR_RGB
        frame[y0:y1, x0:x1, 0:3] = region_rgb
        frame[y0:y1, x0:x1, 3] = (np.maximum(alpha, ring_a) * 255).round().astype(np.uint8)

    caption_lines: List[str] = []
    if project.captions:
        for cue in project.captions:
            if cue.start <= t_out < cue.end:
                caption_lines = wrap_caption_lines(cue.text)
                break
    active_callouts = [c for c in project.callouts if c.start <= t <= c.end]
    if project.tag_text or caption_lines or active_callouts:
        img = Image.fromarray(frame, "RGBA")
        draw = ImageDraw.Draw(img)
        if project.tag_text:
            font = _load_font(max(16, int(round(height * 0.034))))
            text = project.tag_text
            bbox = draw.textbbox((0, 0), text, font=font, stroke_width=3)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = min(max(cx - tw / 2.0, 4), max(4, width - tw - 4))
            ty = cy - ry - th - 14
            if ty < 4:
                ty = cy + ry + 10
            draw.text(
                (tx - bbox[0], ty - bbox[1]),
                text,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=3,
                stroke_fill=(0, 0, 0, 255),
            )
        if caption_lines:
            _draw_caption(draw, caption_lines, width, height)
        for callout in active_callouts:
            anchor_kf = project.keyframes[callout.keyframe]
            if provider is None:
                anchor_x, anchor_y = anchor_kf.x * width, anchor_kf.y * height
            else:
                ax, ay, _scale = provider(anchor_kf.t)
                anchor_x, anchor_y = ax * width, ay * height
            _draw_callout(draw, callout.text, anchor_x, anchor_y, width, height, ry)
        frame = np.asarray(img)
    return frame


def _draw_caption(draw: "ImageDraw.ImageDraw", lines: List[str], width: int, height: int) -> None:
    """Burned-in caption: bold white, black outline, lower third,
    lines stacked upward from a bottom safe margin."""
    font = _load_font(max(18, int(round(height * 0.040))))
    stroke = max(2, int(round(height * 0.006)))
    line_h = int(round(height * 0.054))
    bottom = height - int(round(height * 0.05))
    for i, line in enumerate(reversed(lines)):
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
        tw = bbox[2] - bbox[0]
        x = (width - tw) / 2.0 - bbox[0]
        y = bottom - line_h * (i + 1) - bbox[1]
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 255),
        )


def callout_layout(
    anchor_x: float,
    anchor_y: float,
    box_w: float,
    box_h: float,
    width: int,
    height: int,
    ring_ry_px: float,
):
    """Place a callout's text box away from its anchor point.

    Returns ``(box_x, box_y, line_start, tip)``: the box goes into the
    frame quadrant opposite the anchor (clamped inside the frame),
    ``line_start`` is the point on the box nearest the anchor, and
    ``tip`` is where the leader arrow lands — just outside the
    spotlight ring, on the line from the anchor toward the box.
    """
    pad = 12.0
    gap_x = max(30.0, width * 0.14)
    gap_y = max(24.0, height * 0.12)
    if anchor_x <= width / 2.0:
        box_x = anchor_x + gap_x
    else:
        box_x = anchor_x - gap_x - box_w
    if anchor_y <= height / 2.0:
        box_y = anchor_y + gap_y
    else:
        box_y = anchor_y - gap_y - box_h
    box_x = min(max(box_x, pad), max(pad, width - box_w - pad))
    box_y = min(max(box_y, pad), max(pad, height - box_h - pad))
    center_x, center_y = box_x + box_w / 2.0, box_y + box_h / 2.0
    dx, dy = center_x - anchor_x, center_y - anchor_y
    dist = math.hypot(dx, dy) or 1.0
    reach = ring_ry_px * 1.5 + 4.0
    tip = (anchor_x + dx / dist * reach, anchor_y + dy / dist * reach)
    line_start = (
        min(max(tip[0], box_x), box_x + box_w),
        min(max(tip[1], box_y), box_y + box_h),
    )
    return box_x, box_y, line_start, tip


def _draw_callout(
    draw: "ImageDraw.ImageDraw",
    text: str,
    anchor_x: float,
    anchor_y: float,
    width: int,
    height: int,
    ring_ry_px: float,
) -> None:
    """One callout: dark rounded text box + gold leader arrow."""
    font = _load_font(max(15, int(round(height * 0.030))))
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 10, 6
    box_w, box_h = tw + 2 * pad_x, th + 2 * pad_y
    box_x, box_y, line_start, tip = callout_layout(
        anchor_x, anchor_y, box_w, box_h, width, height, ring_ry_px
    )
    gold = RING_COLOR_RGB + (255,)
    draw.line([line_start, tip], fill=gold, width=3)
    angle = math.atan2(tip[1] - line_start[1], tip[0] - line_start[0])
    head = max(7.0, height * 0.012)
    for spread in (0.45, -0.45):
        barb = (
            tip[0] - head * math.cos(angle + spread),
            tip[1] - head * math.sin(angle + spread),
        )
        draw.line([tip, barb], fill=gold, width=3)
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=6,
        fill=(0, 0, 0, 170),
    )
    draw.text(
        (box_x + pad_x - bbox[0], box_y + pad_y - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )


def write_overlay_frames(
    project: HighlightProject,
    frames_dir,
    width: int,
    height: int,
    fps: int,
    provider=None,
    timeline: Timeline = None,
) -> int:
    """Rasterize every output frame into *frames_dir*; returns the count.

    Without an explicit *provider*, one is built from the project
    (telemetry-compensated when a usable track is named, else
    frame-space) at the render's aspect ratio.  When the project has
    beats and no *timeline* is passed, one is built here; the frame
    count and the per-frame clock then follow the beats.
    """
    out_dir = Path(frames_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if provider is None:
        provider, mode = build_position_provider(project, width / float(height))
        log.info("overlay position mode: %s", mode)
    if timeline is None and project.beats:
        timeline = build_timeline(
            project.window.start,
            project.window.end,
            project.freeze_intro_s,
            project.beats,
        )
    if timeline is not None:
        count = int(round(timeline.duration * fps))
    else:
        count = output_frame_count(project, fps)
    for i in range(count):
        rgba = overlay_frame_rgba(
            project, i, width, height, fps, provider=provider, timeline=timeline
        )
        Image.fromarray(rgba, "RGBA").save(out_dir / (FRAME_NAME_PATTERN % i))
    return count


# ══════════════════════════════════════════════════════════════════════════
# ffmpeg command construction (pure)
# ══════════════════════════════════════════════════════════════════════════

def build_filtergraph(project: HighlightProject, width: int, height: int, fps: int) -> str:
    """Scale the trimmed clip, clone-pad the freeze intro, overlay rings."""
    return (
        f"[0:v]scale={width}:{height}:flags=lanczos,"
        f"tpad=start_mode=clone:start_duration={project.freeze_intro_s:.3f},"
        f"fps={fps},setsar=1[base];"
        f"[base][1:v]overlay=0:0:format=auto,format=yuv420p[vout]"
    )


def build_ffmpeg_command(
    project: HighlightProject,
    frames_dir,
    output_path,
    width: int,
    height: int,
    fps: int,
    has_audio: bool,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """The full argv for one render.  Game audio (when present) is delayed
    by the freeze length so it re-syncs once the clip starts rolling."""
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{project.window.start:.3f}",
        "-t", f"{project.window.duration:.3f}",
        "-i", str(project.source_video),
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", str(Path(frames_dir) / FRAME_NAME_PATTERN),
        "-filter_complex", build_filtergraph(project, width, height, fps),
        "-map", "[vout]",
    ]
    if has_audio:
        delay_ms = int(round(project.freeze_intro_s * 1000))
        cmd += [
            "-map", "0:a?",
            "-af", f"adelay={delay_ms}:all=1",
            "-c:a", "aac", "-b:a", "128k",
        ]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-t", f"{project.output_duration:.3f}",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd



# ══════════════════════════════════════════════════════════════════════════
# Session 2: beats / voiceover graph construction (pure)
# ══════════════════════════════════════════════════════════════════════════

def render_duration(
    project: HighlightProject, timeline: Timeline = None
) -> float:
    """Rendered length in seconds: the beats timeline's when the
    project has beats, else the Session 1 freeze + window length."""
    if project.beats:
        tl = timeline or build_timeline(
            project.window.start,
            project.window.end,
            project.freeze_intro_s,
            project.beats,
        )
        return tl.duration
    return project.output_duration


def build_segment_video_filters(
    project: HighlightProject, timeline: Timeline, width: int, height: int, fps: int
) -> List[str]:
    """Per-segment video chains + concat, yielding ``[base]``.

    The input is the window-trimmed source (clip-relative clock), fps
    normalized up front so freeze segments can address exact frames.
    Play segments trim + re-zero (stretching by 1/rate for slow-mo);
    freeze segments take one frame and clone-pad it for the hold.
    """
    segs = timeline.segments
    parts = [
        f"[0:v]scale={width}:{height}:flags=lanczos,fps={fps},setsar=1,"
        f"split={len(segs)}" + "".join(f"[sv{i}]" for i in range(len(segs)))
    ]
    for i, seg in enumerate(segs):
        rel_start = seg.src_start - project.window.start
        if seg.kind == SEG_FREEZE:
            frame_no = int(round(rel_start * fps))
            hold = max(seg.out_duration - 1.0 / fps, 0.0)
            parts.append(
                f"[sv{i}]trim=start_frame={frame_no}:end_frame={frame_no + 1},"
                f"setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={hold:.3f},"
                f"settb=AVTB[sv{i}o]"
            )
        else:
            rel_end = seg.src_end - project.window.start
            chain = (
                f"[sv{i}]trim=start={rel_start:.3f}:end={rel_end:.3f},"
                f"setpts=(PTS-STARTPTS)"
            )
            if seg.rate != 1.0:
                chain += f"/{seg.rate:.4f}"
            chain += f",settb=AVTB[sv{i}o]"
            parts.append(chain)
    parts.append(
        "".join(f"[sv{i}o]" for i in range(len(segs)))
        + f"concat=n={len(segs)}:v=1:a=0[base]"
    )
    return parts


def _atempo_chain(rate: float) -> str:
    """atempo stages for *rate* (one stage only covers 0.5..100)."""
    if rate >= 0.5:
        return f"atempo={rate:.4f}"
    return f"atempo=0.5,atempo={rate / 0.5:.4f}"


def build_segment_audio_filters(
    project: HighlightProject, timeline: Timeline
) -> List[str]:
    """Per-segment game-audio chains + concat, yielding ``[game_a]``.

    Mirrors the video segments: play segments are trimmed (and
    tempo-shifted for slow-mo); freeze segments contribute generated
    silence (holding game audio under a held frame sounds broken).
    The freeze segments' split outputs are drained to anullsink.
    """
    segs = timeline.segments
    parts = [
        "[0:a]asplit=" + str(len(segs))
        + "".join(f"[sa{i}]" for i in range(len(segs)))
    ]
    for i, seg in enumerate(segs):
        if seg.kind == SEG_FREEZE:
            parts.append(f"[sa{i}]anullsink")
            parts.append(
                f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
                f"atrim=0:{seg.out_duration:.3f},asetpts=PTS-STARTPTS[sa{i}o]"
            )
        else:
            rel_start = seg.src_start - project.window.start
            rel_end = seg.src_end - project.window.start
            chain = (
                f"[sa{i}]atrim=start={rel_start:.3f}:end={rel_end:.3f},"
                f"asetpts=PTS-STARTPTS"
            )
            if seg.rate != 1.0:
                chain += "," + _atempo_chain(seg.rate)
            chain += f",aresample={SAMPLE_RATE}[sa{i}o]"
            parts.append(chain)
    parts.append(
        "".join(f"[sa{i}o]" for i in range(len(segs)))
        + f"concat=n={len(segs)}:v=0:a=1,aresample={SAMPLE_RATE}[game_a]"
    )
    return parts


def build_effects_ffmpeg_command(
    project: HighlightProject,
    frames_dir,
    output_path,
    width: int,
    height: int,
    fps: int,
    timeline: Timeline,
    has_audio: bool,
    take_durations,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """The full argv for a Session 2 render (beats and/or voiceover).

    Inputs: 0 = window-trimmed source, 1 = overlay PNG sequence,
    2.. = the VO takes in project order.  Video comes from the
    per-segment chains when beats are present, else from the Session
    1 filtergraph head.  Audio, when produced, ends at ``[aout]``
    (VO mix: ducked game chain + takes + loudnorm) or at
    ``[game_a]`` (beats-retimed game audio with no VO).
    """
    takes = project.voiceover.takes if project.voiceover is not None else []
    graph: List[str] = []
    if project.beats:
        graph += build_segment_video_filters(project, timeline, width, height, fps)
        graph.append("[base][1:v]overlay=0:0:format=auto,format=yuv420p[vout]")
        if has_audio:
            graph += build_segment_audio_filters(project, timeline)
    else:
        graph.append(build_filtergraph(project, width, height, fps))
        if has_audio:
            delay_ms = int(round(project.freeze_intro_s * 1000))
            graph.append(
                f"[0:a]adelay={delay_ms}:all=1,aresample={SAMPLE_RATE}[game_a]"
            )

    audio_out = None
    if takes:
        if not has_audio:
            graph.append(silence_bed_filter(timeline.duration, "game_a"))
        vo_labels = []
        for i, take in enumerate(takes):
            label = f"vo{i}"
            graph.append(build_take_filter(2 + i, take, label))
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
        audio_out = "aout"
    elif has_audio and project.beats:
        audio_out = "game_a"

    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{project.window.start:.3f}",
        "-t", f"{project.window.duration:.3f}",
        "-i", str(project.source_video),
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", str(Path(frames_dir) / FRAME_NAME_PATTERN),
    ]
    for take in takes:
        cmd += ["-i", str(take.file)]
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", "[vout]",
    ]
    if audio_out is not None:
        cmd += ["-map", f"[{audio_out}]", "-c:a", "aac", "-b:a", "128k"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-t", f"{timeline.duration:.3f}",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


# ══════════════════════════════════════════════════════════════════════════
# Render runner (thin shell over the pure pieces)
# ══════════════════════════════════════════════════════════════════════════

def probe_has_audio(source_video, ffprobe_bin: str = "ffprobe") -> bool:
    """True when ffprobe finds an audio stream in *source_video*."""
    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "json",
                str(source_video),
            ],
            capture_output=True, text=True, check=True,
        )
        return bool(json.loads(result.stdout).get("streams"))
    except Exception:
        return False


def render_project(
    project: HighlightProject,
    output_path,
    preset_name: str = "recruiting",
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: int = 30,
    keep_frames: bool = False,
    frames_dir=None,
) -> Path:
    """Render *project* to *output_path* at the named preset's size.

    Dispatch: a project with beats or voiceover takes renders through
    the Session 2 effects graph (segment trims, VO mix); anything
    else takes the Session 1 path untouched.  Either way, a project
    with caption cues also writes a .srt sidecar beside the output.
    """
    if (width is None) != (height is None):
        raise ValueError("width and height must be given together")
    if width is None:
        preset = project.preset(preset_name)
        width, height = preset.width, preset.height

    from export.ffmpeg import resolve_tool  # lazy: keeps builder imports light

    ffmpeg_bin = resolve_tool("ffmpeg")
    ffprobe_bin = resolve_tool("ffprobe")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    own_frames_dir = frames_dir is None
    work_dir = Path(frames_dir) if frames_dir else Path(
        tempfile.mkdtemp(prefix="lva_highlight_frames_")
    )
    timeline = None
    if project.beats:
        timeline = build_timeline(
            project.window.start,
            project.window.end,
            project.freeze_intro_s,
            project.beats,
        )
    takes = project.voiceover.takes if project.voiceover is not None else []
    try:
        count = write_overlay_frames(
            project, work_dir, width, height, fps, timeline=timeline
        )
        log.info("rasterized %d overlay frames at %dx%d", count, width, height)
        has_audio = probe_has_audio(project.source_video, ffprobe_bin)
        if timeline is not None or takes:
            tl = timeline or build_timeline(
                project.window.start,
                project.window.end,
                project.freeze_intro_s,
                project.beats,
            )
            take_durations = []
            for take in takes:
                if not Path(take.file).exists():
                    raise ValueError(f"voiceover take file not found: {take.file}")
                take_durations.append(probe_duration(take.file, ffprobe_bin))
            cmd = build_effects_ffmpeg_command(
                project, work_dir, out, width, height, fps,
                tl, has_audio, take_durations, ffmpeg_bin,
            )
        else:
            cmd = build_ffmpeg_command(
                project, work_dir, out, width, height, fps, has_audio, ffmpeg_bin
            )
        log.info("rendering: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            tail = "\n".join(result.stderr.splitlines()[-15:])
            raise RuntimeError(f"ffmpeg render failed (rc={result.returncode}):\n{tail}")
    finally:
        if own_frames_dir and not keep_frames:
            shutil.rmtree(work_dir, ignore_errors=True)
    if project.captions:
        srt_path = write_srt(project.captions, out.with_suffix(".srt"))
        log.info("caption sidecar written: %s", srt_path)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lva-highlight",
        description="Render a highlight project's spotlight cut (Tier 1).",
    )
    parser.add_argument("project", help="path to project.json")
    parser.add_argument("output", help="output .mp4 path")
    parser.add_argument("--preset", default="recruiting")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--keep-frames", action="store_true",
                        help="keep the rasterized overlay PNG sequence")
    parser.add_argument("--frames-dir", default=None,
                        help="write overlay frames here (kept; implies a stable location)")
    args = parser.parse_args(argv)

    project = load_project(args.project)
    out = render_project(
        project,
        args.output,
        preset_name=args.preset,
        width=args.width,
        height=args.height,
        fps=args.fps,
        keep_frames=args.keep_frames or bool(args.frames_dir),
        frames_dir=args.frames_dir,
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
