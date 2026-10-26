"""Tests for the Session 2 renderer additions (highlight/render.py):
segment filtergraphs, the effects ffmpeg command, caption/callout
rasterization — plus one end-to-end render through real ffmpeg.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import (
    Beat,
    Callout,
    CaptionCue,
    ClipWindow,
    HighlightProject,
    Keyframe,
    VoiceoverSettings,
    VoiceoverTake,
)
from highlight.render import (
    build_effects_ffmpeg_command,
    build_segment_audio_filters,
    build_segment_video_filters,
    callout_layout,
    overlay_frame_rgba,
    render_duration,
    render_project,
)
from highlight.timeline import build_timeline

W, H, FPS = 320, 180, 30


def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.5, 0.5)],
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


BEATS = [Beat("slowmo", 110.0, 114.0, rate=0.5), Beat("freeze", 120.0, duration=1.0)]


def beats_project(**overrides):
    overrides.setdefault("beats", list(BEATS))
    return make_project(**overrides)


def beats_timeline(project):
    return build_timeline(
        project.window.start, project.window.end, project.freeze_intro_s, project.beats
    )


# ── duration ─────────────────────────────────────────────────────────

def test_render_duration_without_beats_is_session1_length():
    assert render_duration(make_project()) == pytest.approx(26.0)


def test_render_duration_with_beats_uses_timeline():
    # intro 1 + play 10 + slowmo 4/0.5=8 + play 6 + freeze 1 + play 5
    assert render_duration(beats_project()) == pytest.approx(31.0)


# ── segment filtergraphs ─────────────────────────────────────────────

def test_segment_video_filters_structure():
    project = beats_project()
    graph = ";".join(build_segment_video_filters(project, beats_timeline(project), W, H, FPS))
    assert "split=6" in graph  # intro freeze + 2 play + slowmo + freeze + play
    assert "concat=n=6:v=1:a=0[base]" in graph
    assert "setpts=(PTS-STARTPTS)/0.5000" in graph       # the slow-mo segment
    assert "tpad=stop_mode=clone:stop_duration=" in graph  # freeze holds
    assert "trim=start_frame=600:end_frame=601" in graph    # freeze at rel 20s, 30fps


def test_segment_audio_filters_structure():
    project = beats_project()
    graph = ";".join(build_segment_audio_filters(project, beats_timeline(project)))
    assert "atempo=0.5000" in graph          # slow-mo audio follows the picture
    assert "anullsrc" in graph              # silence under freeze holds
    assert "anullsink" in graph             # freeze segments' audio drained
    assert "concat=n=6:v=0:a=1" in graph
    assert graph.rstrip().endswith("[game_a]")


def test_atempo_chain_for_quarter_speed():
    project = make_project(beats=[Beat("slowmo", 110.0, 114.0, rate=0.25)])
    graph = ";".join(build_segment_audio_filters(project, beats_timeline(project)))
    assert "atempo=0.5,atempo=0.5000" in graph


# ── effects command ──────────────────────────────────────────────────

def vo_project(**overrides):
    overrides.setdefault(
        "voiceover",
        VoiceoverSettings(takes=[VoiceoverTake("/tmp/vo.wav", 3.0)]),
    )
    return beats_project(**overrides)


def test_effects_command_with_vo_and_game_audio():
    project = vo_project()
    cmd = build_effects_ffmpeg_command(
        project, "/tmp/frames", "/tmp/out.mp4", W, H, FPS,
        beats_timeline(project), has_audio=True, take_durations=[4.0],
    )
    joined = " ".join(cmd)
    assert cmd[cmd.index("-t") + 1] == "31.000" or "31.000" in joined
    # inputs: source, overlay frames, then the take
    i_positions = [i for i, a in enumerate(cmd) if a == "-i"]
    assert len(i_positions) == 3
    assert cmd[i_positions[2] + 1] == "/tmp/vo.wav"
    assert "-map" in cmd and "[aout]" in cmd
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=2:duration=first:normalize=0" in graph
    assert "loudnorm=I=-16.000" in graph


def test_effects_command_vo_without_game_audio_uses_silence_bed():
    project = vo_project()
    cmd = build_effects_ffmpeg_command(
        project, "/tmp/frames", "/tmp/out.mp4", W, H, FPS,
        beats_timeline(project), has_audio=False, take_durations=[4.0],
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "anullsrc=r=48000:cl=stereo,atrim=0:31.000" in graph  # the bed
    assert "[aout]" in cmd


def test_effects_command_beats_no_vo_maps_game_audio():
    project = beats_project()
    cmd = build_effects_ffmpeg_command(
        project, "/tmp/frames", "/tmp/out.mp4", W, H, FPS,
        beats_timeline(project), has_audio=True, take_durations=[],
    )
    assert "[game_a]" in cmd
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm" not in graph  # clean game audio, no mix without VO


# ── caption / callout rasterization ──────────────────────────────────

def test_caption_pixels_appear_only_while_cue_active():
    project = make_project(captions=[CaptionCue(0.0, 5.0, "She buries it top shelf")])
    band = slice(int(H * 0.84), H)
    active = overlay_frame_rgba(project, 15, W, H, FPS)   # t_out = 0.5s
    inactive = overlay_frame_rgba(project, 200, W, H, FPS)  # t_out = 6.7s

    def white_text_pixels(frame):
        region = frame[band]
        return int(((region[..., 0] > 200) & (region[..., 1] > 200)
                    & (region[..., 2] > 200) & (region[..., 3] == 255)).sum())

    assert white_text_pixels(active) > 50
    assert white_text_pixels(inactive) == 0


def test_callout_box_pixels_appear_only_in_window():
    project = make_project(callouts=[Callout("forces her weak hand", 110.0, 112.0, 0)])

    def box_pixels(frame):
        # The box fill is exactly (0, 0, 0, 170); a stray anti-aliased
        # text pixel can land near that alpha, so compare magnitudes.
        return int(((frame[..., 3] == 170) & (frame[..., 0] == 0)
                    & (frame[..., 1] == 0)).sum())

    inside = overlay_frame_rgba(project, 330, W, H, FPS)   # source t ~110
    outside = overlay_frame_rgba(project, 30, W, H, FPS)   # source t ~101
    assert box_pixels(inside) > 500
    assert box_pixels(outside) < 5


def test_callout_layout_quadrants_and_tip():
    # anchor in the left/top half -> box to the right and below
    box_x, box_y, _start, tip = callout_layout(40, 30, 100, 30, W, H, 5.0)
    assert box_x > 40 and box_y > 30
    # anchor bottom-right -> box to the left and above, clamped in frame
    box_x, box_y, _s, _t = callout_layout(300, 160, 100, 30, W, H, 5.0)
    assert box_x + 100 <= 300 + 1 and box_y + 30 <= 160 + 1
    assert box_x >= 0 and box_y >= 0
    # tip sits just outside the ring (ry*1.5 + 4 from the anchor)
    dist = np.hypot(tip[0] - 40, tip[1] - 30)
    assert dist == pytest.approx(5.0 * 1.5 + 4.0)


# ── end-to-end through real ffmpeg ───────────────────────────────────

ffmpeg_bin = shutil.which("ffmpeg")
ffprobe_bin = shutil.which("ffprobe")


@pytest.mark.skipif(not ffmpeg_bin or not ffprobe_bin, reason="ffmpeg not installed")
def test_render_effects_end_to_end(tmp_path):
    src = tmp_path / "src.mp4"
    vo = tmp_path / "vo.wav"
    subprocess.run(
        [ffmpeg_bin, "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
         "-shortest", str(src)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.8",
         "-c:a", "pcm_s16le", str(vo)],
        check=True, capture_output=True,
    )
    project = HighlightProject(
        source_video=str(src),
        window=ClipWindow(0.0, 2.0),
        keyframes=[Keyframe(0.0, 0.5, 0.5), Keyframe(2.0, 0.6, 0.5)],
        freeze_intro_s=0.5,
        beats=[Beat("slowmo", 0.8, 1.2, rate=0.5)],
        voiceover=VoiceoverSettings(takes=[VoiceoverTake(str(vo), 1.0)]),
        captions=[CaptionCue(1.0, 2.2, "Nice play by number twenty five")],
    )
    out = tmp_path / "out.mp4"
    render_project(project, out, width=160, height=90, fps=10)

    probe = subprocess.run(
        [ffprobe_bin, "-v", "error", "-show_entries",
         "stream=codec_type,width,height:format=duration",
         "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (160, 90)
    # 0.5 intro + 0.8 play + 0.4/0.5 slow-mo + 0.8 play = 2.9s
    assert float(info["format"]["duration"]) == pytest.approx(2.9, abs=0.4)

    from highlight.captions import read_srt
    sidecar = tmp_path / "out.srt"
    assert sidecar.exists()
    cues = read_srt(sidecar)
    assert len(cues) == 1 and cues[0].text == "Nice play by number twenty five"
