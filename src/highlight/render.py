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
from .tracking import position_at

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
    project: HighlightProject, frame_index: int, width: int, height: int, fps: int
) -> np.ndarray:
    """The (height, width, 4) uint8 RGBA overlay for one output frame.

    Contents: the dim mask (black, alpha = dim strength far from the
    player, fading to clear inside the ring), the gold ellipse ring at
    the interpolated ground position, and the tag text above the ring.
    """
    t = frame_source_time(project, frame_index, fps)
    nx, ny = position_at(project.keyframes, t)
    cx, cy = nx * width, ny * height
    rx = project.ring.rx * width
    ry = project.ring.ry * height

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

    if project.tag_text:
        img = Image.fromarray(frame, "RGBA")
        draw = ImageDraw.Draw(img)
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
        frame = np.asarray(img)
    return frame


def write_overlay_frames(
    project: HighlightProject, frames_dir, width: int, height: int, fps: int
) -> int:
    """Rasterize every output frame into *frames_dir*; returns the count."""
    out_dir = Path(frames_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = output_frame_count(project, fps)
    for i in range(count):
        rgba = overlay_frame_rgba(project, i, width, height, fps)
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
    """Render *project* to *output_path* at the named preset's size."""
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
    try:
        count = write_overlay_frames(project, work_dir, width, height, fps)
        log.info("rasterized %d overlay frames at %dx%d", count, width, height)
        has_audio = probe_has_audio(project.source_video, ffprobe_bin)
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
