"""Tests for the spotlight renderer (highlight/render.py).

The command builder and the frame rasterizer are pure functions, so
everything here runs without ffmpeg or a real video.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import (
    ClipWindow,
    DimSettings,
    HighlightProject,
    Keyframe,
    RingSettings,
)
from highlight.render import (
    build_ffmpeg_command,
    build_filtergraph,
    frame_source_time,
    freeze_frame_count,
    output_frame_count,
    overlay_frame_rgba,
    write_overlay_frames,
)

W, H, FPS = 320, 180, 30


def make_render_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.5, 0.5)],
        ring=RingSettings(0.05, 0.10),  # rx=16px, ry=18px on the test canvas
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


# ── frame timing ─────────────────────────────────────────────────────

def test_frame_count_includes_freeze():
    project = make_render_project()
    assert freeze_frame_count(project, FPS) == 30
    assert output_frame_count(project, FPS) == 780  # (1s freeze + 25s clip) * 30


def test_frame_source_time_freezes_then_advances_then_clamps():
    project = make_render_project()
    assert frame_source_time(project, 0, FPS) == 100.0
    assert frame_source_time(project, 29, FPS) == 100.0
    assert frame_source_time(project, 30, FPS) == 100.0
    assert frame_source_time(project, 330, FPS) == pytest.approx(110.0)
    assert frame_source_time(project, 100_000, FPS) == 125.0


# ── filtergraph / command construction ───────────────────────────────

def test_filtergraph_pieces():
    graph = build_filtergraph(make_render_project(), W, H, FPS)
    assert "scale=320:180" in graph
    assert "tpad=start_mode=clone:start_duration=1.000" in graph
    assert "overlay=0:0" in graph
    assert graph.endswith("[vout]")


def test_command_with_audio_delays_game_audio_by_freeze():
    project = make_render_project()
    cmd = build_ffmpeg_command(project, "/tmp/frames", "/tmp/out.mp4", W, H, FPS, has_audio=True)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "100.000"
    assert cmd[cmd.index("-t") + 1] == "25.000"  # first -t is the input trim
    assert cmd[cmd.index("-start_number") + 1] == "0"
    assert "0:a?" in cmd
    assert cmd[cmd.index("-af") + 1] == "adelay=1000:all=1"
    assert cmd[-1] == "/tmp/out.mp4"


def test_command_without_audio_has_no_audio_args():
    project = make_render_project()
    cmd = build_ffmpeg_command(project, "/tmp/frames", "/tmp/out.mp4", W, H, FPS, has_audio=False)
    assert "0:a?" not in cmd
    assert not any("adelay" in arg for arg in cmd)


# ── overlay rasterization ────────────────────────────────────────────

def test_overlay_shape_and_dtype():
    frame = overlay_frame_rgba(make_render_project(), 0, W, H, FPS)
    assert frame.shape == (H, W, 4)
    assert frame.dtype == np.uint8


def test_overlay_dim_corner_and_clear_center():
    frame = overlay_frame_rgba(make_render_project(), 0, W, H, FPS)
    assert frame[0, 0, 3] == 89  # 0.35 * 255, far from the player
    assert frame[90, 160, 3] == 0  # inside the ring: fully clear


def test_overlay_ring_pixel_is_gold_and_opaque():
    frame = overlay_frame_rgba(make_render_project(), 0, W, H, FPS)
    pixel = frame[90, 176]  # cx + rx, cy: exactly on the ellipse edge
    assert tuple(pixel[:3]) == (255, 199, 44)
    assert pixel[3] == 255


def test_overlay_glow_fades_inside_ring():
    frame = overlay_frame_rgba(make_render_project(), 0, W, H, FPS)
    alpha = frame[90, 168, 3]  # halfway from center to ring edge
    assert 10 < alpha < 100


def test_overlay_dim_disabled_leaves_corners_transparent():
    project = make_render_project(dim=DimSettings(enabled=False))
    frame = overlay_frame_rgba(project, 0, W, H, FPS)
    assert frame[0, 0, 3] == 0
    assert frame[90, 176, 3] == 255  # ring still drawn


def test_overlay_tag_text_is_drawn_above_ring():
    frame = overlay_frame_rgba(make_render_project(), 0, W, H, FPS)
    patch = frame[25:75, 120:200, :3].astype(int)
    white = (patch[:, :, 0] > 200) & (patch[:, :, 1] > 200) & (patch[:, :, 2] > 200)
    assert white.any()  # the "#25" glyphs, white with black stroke


def test_freeze_frames_hold_first_position():
    project = make_render_project(
        keyframes=[Keyframe(100.0, 0.3, 0.5), Keyframe(125.0, 0.7, 0.5)]
    )
    first = overlay_frame_rgba(project, 0, W, H, FPS)
    still_frozen = overlay_frame_rgba(project, 29, W, H, FPS)
    rolling = overlay_frame_rgba(project, 90, W, H, FPS)
    assert np.array_equal(first, still_frozen)
    assert not np.array_equal(first, rolling)


def test_overlay_frames_written_as_png_sequence(tmp_path):
    project = HighlightProject(
        source_video="game.mp4",
        window=ClipWindow(100.0, 100.5),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(100.5, 0.6, 0.5)],
        freeze_intro_s=0.2,
    )
    count = write_overlay_frames(project, tmp_path, 64, 36, fps=10)
    assert count == 7  # (0.2 freeze + 0.5 clip) * 10 fps
    files = sorted(p.name for p in tmp_path.glob("*.png"))
    assert files == [f"ring_{i:05d}.png" for i in range(7)]
    with Image.open(tmp_path / "ring_00000.png") as img:
        assert img.size == (64, 36)
        assert img.mode == "RGBA"
