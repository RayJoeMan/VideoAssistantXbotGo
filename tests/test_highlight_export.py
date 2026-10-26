"""Tests for the Session 3 dual-export driver (highlight/export.py):
probe/verify, the vertical crop path, the command builders, the
overlay reframe hook — plus end-to-end exports through real ffmpeg.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.cards import END_CARD_S, TITLE_CARD_S
from highlight.export import (
    build_concat_card_command,
    build_vertical_command,
    crop_dimensions,
    export_project,
    probe_media,
    subject_crop_offsets,
    verify_output,
    write_crop_commands,
)
from highlight.project import (
    CaptionCue,
    ClipWindow,
    ExportPreset,
    HighlightProject,
    Keyframe,
    PlayerInfo,
    VoiceoverSettings,
    VoiceoverTake,
)
from highlight.render import CropReframe, overlay_frame_rgba
from highlight.timeline import build_timeline

ffmpeg_bin = shutil.which("ffmpeg")
ffprobe_bin = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_bin or not ffprobe_bin, reason="ffmpeg not installed"
)


def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.5, 0.5)],
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


# ── crop math (pure) ─────────────────────────────────────────────────

def test_crop_dimensions():
    assert crop_dimensions(3840, 2160, 1080, 1920) == (1216, 2160)
    assert crop_dimensions(1080, 1920, 1080, 1920) == (1080, 1920)
    assert crop_dimensions(320, 180, 108, 192) == (102, 180)
    w, h = crop_dimensions(321, 181, 1080, 1920)
    assert w % 2 == 0 and h % 2 == 0 and w <= 321 and h <= 181


def _timeline(project):
    return build_timeline(
        project.window.start, project.window.end, project.freeze_intro_s, []
    )


def test_subject_crop_offsets_clamp_to_subject():
    project = make_project(freeze_intro_s=0.0)
    timeline = _timeline(project)
    provider = lambda t: (0.9, 0.5, 1.0)  # noqa: E731
    offsets, (crop_w, crop_h) = subject_crop_offsets(
        project, timeline, provider, 1000, 500, 90, 160, fps=10
    )
    assert (crop_w, crop_h) == (282, 500)
    assert len(offsets) == 250
    # Subject center 900 - half crop 141 = 759, clamped to 1000-282=718.
    assert all(o == (718, 0) for o in offsets)


def test_subject_crop_offsets_track_motion():
    project = make_project(freeze_intro_s=0.0)
    timeline = _timeline(project)
    span = project.window.duration

    def provider(t):
        u = (t - project.window.start) / span
        return (0.1 + 0.8 * u, 0.5, 1.0)

    offsets, _ = subject_crop_offsets(
        project, timeline, provider, 1000, 500, 90, 160, fps=10, smooth_s=0.3
    )
    xs = [o[0] for o in offsets]
    assert xs[0] == 0                      # clamped at the left edge
    assert xs[-1] == 1000 - 282            # clamped at the right edge
    assert all(b >= a for a, b in zip(xs, xs[1:]))  # never moves backwards


def test_write_crop_commands_only_on_change(tmp_path):
    path = write_crop_commands([(10, 0)] * 5, fps=10, path=tmp_path / "c.txt")
    assert path.read_text().splitlines() == ["0.000 crop x 10;", "0.000 crop y 0;"]
    path2 = write_crop_commands([(0, 0), (0, 0), (4, 0)], fps=10, path=tmp_path / "d.txt")
    lines = path2.read_text().splitlines()
    assert lines[-1] == "0.200 crop x 4;"
    assert len(lines) == 3


# ── overlay reframe hook ─────────────────────────────────────────────

def test_overlay_reframe_moves_ring_with_crop():
    project = make_project(
        window=ClipWindow(0.0, 10.0),
        keyframes=[Keyframe(0.0, 0.625, 0.5), Keyframe(10.0, 0.625, 0.5)],
        freeze_intro_s=0.0,
        tag_text="",
    )
    reframe = CropReframe(400, 200, 100, 200, [(200, 0)] * 30)
    frame = overlay_frame_rgba(project, 0, 200, 200, 30, reframe=reframe)
    gold = (
        (frame[:, :, 0] == 255)
        & (frame[:, :, 1] == 199)
        & (frame[:, :, 2] == 44)
        & (frame[:, :, 3] > 200)
    )
    assert gold.any()
    cols = np.nonzero(gold.any(axis=0))[0]
    # Subject at source x=250; crop offset 200, crop width 100 ->
    # reframed center = (250-200)/100 * 200 = 100.
    assert abs(cols.mean() - 100) < 8


# ── command builders (pure) ──────────────────────────────────────────

def test_concat_card_command_audio_variants():
    with_audio = build_concat_card_command(
        "c.mp4", "card.png", "o.mp4", 1920, 1080, 30, 2.0, 30.0, True
    )
    joined = " ".join(with_audio)
    assert "concat=n=2:v=1:a=0" in joined
    assert "concat=n=2:v=0:a=1" in joined
    assert "[aout]" in with_audio
    without = build_concat_card_command(
        "c.mp4", "card.png", "o.mp4", 1920, 1080, 30, 2.0, 30.0, False
    )
    assert "[0:a]" not in " ".join(without)


def test_vertical_command_structure(tmp_path):
    project = make_project(
        voiceover=VoiceoverSettings(
            takes=[VoiceoverTake(file="vo.wav", start=1.0)]
        )
    )
    timeline = _timeline(project)
    cmd = build_vertical_command(
        project, tmp_path, tmp_path / "cmds.txt", "t.png", "e.png", "o.mp4",
        1920, 1080, 1080, 1920, 30, timeline, 608, 1080, (100, 0),
        True, [0.8],
    )
    joined = " ".join(cmd)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "sendcmd=f=" in graph and "crop=608:1080:100:0" in graph
    assert "concat=n=3:v=1:a=0" in graph
    assert "[4:a]" in graph  # first VO take is input 4 (after title/end cards)
    assert cmd.count("-loop") == 2
    total = TITLE_CARD_S + timeline.duration + END_CARD_S
    assert cmd[cmd.index("-t") + 1] == f"{total:.3f}" or f"{total:.3f}" in cmd


# ── probe / verify (real ffmpeg) ─────────────────────────────────────

def _make_tiny_video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True, capture_output=True,
    )
    return path


@needs_ffmpeg
def test_probe_and_verify(tmp_path):
    video = _make_tiny_video(tmp_path / "tiny.mp4")
    info = probe_media(video, ffprobe_bin)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (160, 90)
    assert info.duration == pytest.approx(2.0, abs=0.3)
    assert verify_output(video, width=160, height=90, duration=2.0,
                         need_audio=True, ffprobe_bin=ffprobe_bin) == []
    problems = verify_output(video, width=320, ffprobe_bin=ffprobe_bin)
    assert any("width" in p for p in problems)
    problems = verify_output(video, need_audio=False, ffprobe_bin=ffprobe_bin)
    assert any("audio" in p for p in problems)
    assert verify_output(tmp_path / "nope.mp4", ffprobe_bin=ffprobe_bin)


# ── end-to-end exports (real ffmpeg) ─────────────────────────────────

def _make_split_source(path: Path, seconds: float = 4.0) -> Path:
    """Left half black, right half white, plus a tone — so a test can
    tell which side of the frame a crop landed on by brightness."""
    subprocess.run(
        [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", f"color=black:s=160x180:r=10:duration={seconds}",
            "-f", "lavfi", "-i", f"color=white:s=160x180:r=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-filter_complex", "[0][1]hstack=2[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True, capture_output=True,
    )
    return path


def _frame_brightness(video: Path, at_s: float) -> float:
    frame = Path(str(video) + ".frame.png")
    subprocess.run(
        [ffmpeg_bin, "-y", "-ss", str(at_s), "-i", str(video),
         "-frames:v", "1", str(frame)],
        check=True, capture_output=True,
    )
    from PIL import Image

    return float(np.asarray(Image.open(frame).convert("L"), dtype=float).mean())


def _e2e_project(source: Path, take: Path, subject_x: float) -> HighlightProject:
    return HighlightProject(
        source_video=str(source),
        window=ClipWindow(1.0, 3.0),
        keyframes=[Keyframe(1.0, subject_x, 0.5), Keyframe(3.0, subject_x, 0.5)],
        freeze_intro_s=1.0,
        export_presets=[
            ExportPreset("recruiting", 320, 180),
            ExportPreset("vertical", 108, 192),
            ExportPreset("clean", 320, 180),
        ],
        voiceover=VoiceoverSettings(takes=[VoiceoverTake(file=str(take), start=1.2)]),
        captions=[CaptionCue(1.2, 2.2, "Test caption")],
        player=PlayerInfo(name="Test Player", position="Defense", handle="@test"),
        play_title="Test play",
    )


@needs_ffmpeg
def test_export_project_end_to_end(tmp_path):
    source = _make_split_source(tmp_path / "game.mp4")
    take = tmp_path / "vo.wav"
    subprocess.run(
        [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.8",
         str(take)],
        check=True, capture_output=True,
    )
    project = _e2e_project(source, take, subject_x=0.85)
    report = export_project(project, tmp_path / "out", stem="proj", fps=10)
    assert report.ok, report.summary_lines()

    recruiting = probe_media(tmp_path / "out" / "proj-recruiting.mp4", ffprobe_bin)
    assert (recruiting.width, recruiting.height) == (320, 180)
    assert recruiting.duration == pytest.approx(3.0 + END_CARD_S, abs=0.6)
    assert (tmp_path / "out" / "proj-recruiting.srt").exists()

    clean = probe_media(tmp_path / "out" / "proj-clean.mp4", ffprobe_bin)
    assert (clean.width, clean.height) == (320, 180)
    assert clean.duration == pytest.approx(4.0, abs=2.0)  # the FULL game

    vertical = probe_media(tmp_path / "out" / "proj-vertical.mp4", ffprobe_bin)
    assert (vertical.width, vertical.height) == (108, 192)
    assert vertical.has_audio
    expected = TITLE_CARD_S + 3.0 + END_CARD_S
    assert vertical.duration == pytest.approx(expected, abs=0.6)
    # The crop followed the subject onto the white (right) half.
    assert _frame_brightness(tmp_path / "out" / "proj-vertical.mp4", 2.5) > 100
    # The vertical sidecar's cues are shifted past the title card.
    srt = (tmp_path / "out" / "proj-vertical.srt").read_text()
    assert "00:00:02,200" in srt


@needs_ffmpeg
def test_export_vertical_follows_subject_left(tmp_path):
    source = _make_split_source(tmp_path / "game.mp4")
    take = tmp_path / "vo.wav"
    subprocess.run(
        [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.8",
         str(take)],
        check=True, capture_output=True,
    )
    project = _e2e_project(source, take, subject_x=0.15)
    report = export_project(
        project, tmp_path / "out", stem="proj", names=["vertical"], fps=10
    )
    assert report.ok, report.summary_lines()
    assert _frame_brightness(tmp_path / "out" / "proj-vertical.mp4", 2.5) < 60


@needs_ffmpeg
def test_export_failures_are_reported_not_raised(tmp_path):
    project = make_project(source_video=str(tmp_path / "missing.mp4"))
    report = export_project(project, tmp_path / "out", stem="proj")
    assert not report.ok
    assert len(report.results) == 3
    assert all(not r.ok and r.problems for r in report.results)
