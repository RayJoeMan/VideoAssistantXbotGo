"""Tests for the Session 2 project-model additions (highlight/project.py):
voiceover takes, caption cues, callouts and beats.

The dataclasses validate eagerly, so everything here is pure Python —
no ffmpeg, no files beyond tmp_path round-trips.
"""

import sys
from pathlib import Path

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
    load_project,
    save_project,
)

LEGACY_KEYS = {
    "version", "source_video", "window", "tag_text", "dim",
    "freeze_intro_s", "ring", "keyframes", "export_presets",
}


def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.4, 0.6), Keyframe(112.0, 0.5, 0.6),
                   Keyframe(125.0, 0.6, 0.6)],
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


def full_session2_project() -> HighlightProject:
    return make_project(
        voiceover=VoiceoverSettings(
            takes=[
                VoiceoverTake("vo1.m4a", 3.0),
                VoiceoverTake("vo2.wav", 9.5, gain_db=-3.0),
            ],
            duck_db=14.0,
            target_lufs=-15.0,
        ),
        captions=[
            CaptionCue(3.0, 5.5, "She wins the draw clean."),
            CaptionCue(9.5, 12.0, "And buries it top shelf."),
        ],
        callouts=[Callout("forces her weak hand", 110.0, 116.0, 1)],
        beats=[
            Beat("slowmo", 110.0, 114.0, rate=0.5),
            Beat("freeze", 120.0, duration=1.2),
        ],
    )


# ── legacy shape ─────────────────────────────────────────────────────

def test_legacy_project_serializes_without_session2_keys():
    project = make_project()
    assert set(project.to_dict()) == LEGACY_KEYS
    assert project.voiceover is None
    assert project.captions == [] and project.callouts == [] and project.beats == []


def test_session2_keys_appear_only_when_populated():
    data = full_session2_project().to_dict()
    assert set(data) == LEGACY_KEYS | {"voiceover", "captions", "callouts", "beats"}


# ── round trip ───────────────────────────────────────────────────────

def test_full_project_round_trips_through_json(tmp_path):
    project = full_session2_project()
    path = save_project(project, tmp_path / "project.json")
    loaded = load_project(path)
    assert loaded.voiceover.duck_db == 14.0
    assert loaded.voiceover.target_lufs == -15.0
    assert [t.file for t in loaded.voiceover.takes] == ["vo1.m4a", "vo2.wav"]
    assert loaded.voiceover.takes[1].gain_db == -3.0
    assert loaded.captions[1].text == "And buries it top shelf."
    assert loaded.callouts[0].keyframe == 1
    assert loaded.beats[0].kind == "slowmo" and loaded.beats[0].rate == 0.5
    assert loaded.beats[1].kind == "freeze" and loaded.beats[1].start == 120.0
    assert loaded.beats[1].duration == 1.2


def test_take_file_resolves_beside_project(tmp_path):
    (tmp_path / "vo1.m4a").write_bytes(b"fake")
    project = make_project(
        voiceover=VoiceoverSettings(takes=[VoiceoverTake("vo1.m4a", 1.0)])
    )
    path = save_project(project, tmp_path / "project.json")
    loaded = load_project(path)
    assert loaded.voiceover.takes[0].file == str(tmp_path / "vo1.m4a")


def test_freeze_beat_json_uses_at():
    beat = Beat("freeze", 120.0, duration=1.2)
    assert beat.to_dict() == {"kind": "freeze", "at": 120.0, "duration": 1.2}
    assert Beat.from_dict(beat.to_dict()) == beat
    slow = Beat("slowmo", 110.0, 114.0, rate=0.5)
    assert Beat.from_dict(slow.to_dict()) == slow


def test_empty_voiceover_block_round_trips():
    project = make_project(voiceover=VoiceoverSettings(duck_db=9.0))
    data = project.to_dict()
    assert data["voiceover"]["takes"] == []
    assert HighlightProject.from_dict(data).voiceover.duck_db == 9.0


# ── voiceover validation ─────────────────────────────────────────────

def test_take_start_must_be_non_negative():
    with pytest.raises(ValueError):
        VoiceoverTake("vo.m4a", -1.0)


def test_takes_must_be_ordered_by_start():
    with pytest.raises(ValueError):
        VoiceoverSettings(
            takes=[VoiceoverTake("a.m4a", 9.0), VoiceoverTake("b.m4a", 3.0)]
        )


def test_voiceover_defaults_match_spec():
    settings = VoiceoverSettings()
    assert settings.duck_db == 12.0
    assert settings.target_lufs == -16.0


# ── caption validation ───────────────────────────────────────────────

def test_caption_end_must_follow_start():
    with pytest.raises(ValueError):
        CaptionCue(5.0, 5.0, "nope")


def test_caption_text_must_be_non_empty():
    with pytest.raises(ValueError):
        CaptionCue(1.0, 2.0, "   ")


# ── callout validation ───────────────────────────────────────────────

def test_callout_keyframe_index_checked_against_project():
    with pytest.raises(ValueError):
        make_project(callouts=[Callout("too far", 110.0, 112.0, 3)])


def test_callout_must_stay_inside_window():
    with pytest.raises(ValueError):
        make_project(callouts=[Callout("early", 90.0, 112.0, 0)])


# ── beat validation ──────────────────────────────────────────────────

def test_overlapping_slowmo_beats_rejected():
    with pytest.raises(ValueError):
        make_project(beats=[Beat("slowmo", 110.0, 115.0),
                            Beat("slowmo", 114.0, 118.0)])


def test_freeze_inside_slowmo_rejected():
    with pytest.raises(ValueError):
        make_project(beats=[Beat("slowmo", 110.0, 115.0),
                            Beat("freeze", 112.0, duration=1.0)])


def test_two_beats_same_start_rejected():
    with pytest.raises(ValueError):
        make_project(beats=[Beat("freeze", 112.0, duration=1.0),
                            Beat("slowmo", 112.0, 116.0)])


def test_beat_outside_window_rejected():
    with pytest.raises(ValueError):
        make_project(beats=[Beat("slowmo", 120.0, 130.0)])


def test_slowmo_rate_bounds():
    with pytest.raises(ValueError):
        Beat("slowmo", 110.0, 114.0, rate=0.1)
    with pytest.raises(ValueError):
        Beat("slowmo", 110.0, 114.0, rate=1.5)
    assert Beat("slowmo", 110.0, 114.0, rate=0.25).rate == 0.25


def test_freeze_duration_bounds():
    with pytest.raises(ValueError):
        Beat("freeze", 112.0, duration=9.0)


def test_unknown_beat_kind_rejected():
    with pytest.raises(ValueError):
        Beat("fastmo", 110.0, 114.0)
    with pytest.raises(ValueError):
        Beat.from_dict({"kind": "fastmo", "start": 1.0, "end": 2.0})
