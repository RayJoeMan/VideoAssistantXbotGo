"""Tests for the Falcon Player marker bridge (analysis/markers.py).

The format expectations here encode the interop contract derived from
the player's public page: a JSON array of {"type", "time"} objects,
2-space indent, sorted by time, at .data/<stem>.mark.fp beside the
video, with <stem> stripping .mp4 and then a trailing .h264.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analysis.markers import (
    camera_mark_path,
    event_to_marker,
    load_marker_file,
    mark_fp_path,
    marker_stem,
    markers_from_events,
    markers_from_nominations,
    merge_markers,
    nomination_to_marker,
    parse_markers,
    serialize_markers,
    write_mark_fp,
)
from telemetry.models import Event, EventType


# ── stem + path rules ────────────────────────────────────────────────

def test_marker_stem_plain():
    assert marker_stem("20260614_085233.mp4") == "20260614_085233"


def test_marker_stem_converted_copy_shares_stem():
    assert marker_stem("20260614_085233.h264.mp4") == "20260614_085233"


def test_marker_stem_case_insensitive():
    assert marker_stem("GAME.H264.MP4") == "GAME"
    assert marker_stem("GAME.MP4") == "GAME"


def test_mark_fp_path_lives_in_data_folder():
    p = mark_fp_path(Path("/games/20260614/game.mp4"))
    assert p == Path("/games/20260614/.data/game.mark.fp")


# ── serialization / parsing round-trip ───────────────────────────────

SAMPLE = [
    {"type": "fp_goal", "time": 1254.3, "label": "goal", "score": 0.91},
    {"type": "click", "time": 12},
    {"type": "fp_nomination", "time": 60.25, "label": "nomination: surge",
     "score": 0.5, "start": 55.0, "end": 68.0},
]


def test_serialize_sorts_by_time_and_indents_two_spaces():
    text = serialize_markers(SAMPLE)
    lines = text.splitlines()
    assert lines[0] == "["
    assert lines[1] == "  {"
    assert '"time": 12' in text  # click first after sorting
    times = [m["time"] for m in json.loads(text)]
    assert times == sorted(times)


def test_serialize_integral_time_has_no_fraction():
    # JSON.stringify(12) is "12", not "12.0" — match the player's bytes.
    assert '"time": 12' in serialize_markers([{"type": "click", "time": 12.0}])


def test_core_fields_come_first():
    text = serialize_markers([{"label": "x", "time": 3.5, "type": "fp_goal"}])
    body = text.splitlines()[2]
    assert body.strip().startswith('"type": "fp_goal",')


def test_round_trip_preserves_entries_and_extras():
    parsed = parse_markers(serialize_markers(SAMPLE))
    assert [ (m["type"], m["time"]) for m in parsed ] == [
        ("click", 12), ("fp_nomination", 60.25), ("fp_goal", 1254.3),
    ]
    goal = next(m for m in parsed if m["type"] == "fp_goal")
    assert goal["label"] == "goal" and goal["score"] == 0.91


@pytest.mark.parametrize("bad", [
    "not json",
    '{"type": "click"}',                       # not an array
    '[{"time": 3}]',                            # missing type
    '[{"type": "click"}]',                      # missing time
    '[{"type": "click", "time": "soon"}]',      # time not numeric
    '[{"type": "click", "time": true}]',        # bool is not a number here
    '[42]',                                     # entry not an object
])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_markers(bad)


def test_parse_empty_array_ok():
    assert parse_markers("[]") == []


# ── event conversion ─────────────────────────────────────────────────

def _event(type_, peak=100.0, conf=0.8, desc=""):
    return Event(event_type=type_, start_time_sec=peak - 5,
                 end_time_sec=peak + 5, peak_time_sec=peak,
                 confidence=conf, description=desc)


def test_event_type_codes():
    assert event_to_marker(_event(EventType.GOAL))["type"] == "fp_goal"
    assert event_to_marker(_event(EventType.SHOT))["type"] == "fp_shot"
    assert event_to_marker(_event(EventType.SAVE))["type"] == "fp_save"
    assert event_to_marker(_event(EventType.FACE_OFF))["type"] == "fp_faceoff"
    assert event_to_marker(_event(EventType.TRANSITION))["type"] == "fp_transition"
    assert event_to_marker(_event(EventType.TURNOVER))["type"] == "fp_turnover"
    assert event_to_marker(_event(EventType.UNKNOWN))["type"] == "fp_event"


def test_event_never_uses_score_types():
    for type_ in EventType:
        assert event_to_marker(_event(type_))["type"] not in (
            "fp_home_score", "fp_away_score")


def test_event_marker_time_label_score():
    m = event_to_marker(_event(EventType.GOAL, peak=1254.34567, conf=0.876,
                               desc="goal — celebration spike"))
    assert m["time"] == 1254.346  # rounded to 3 decimals like the player
    assert m["score"] == 0.876
    assert m["label"] == "goal — celebration spike"


def test_event_marker_label_falls_back_to_type_name():
    m = event_to_marker(_event(EventType.FACE_OFF))
    assert m["label"] == "face off"


def test_markers_from_events_maps_all():
    out = markers_from_events([_event(EventType.SHOT, 10), _event(EventType.SAVE, 20)])
    assert [m["type"] for m in out] == ["fp_shot", "fp_save"]


# ── nomination conversion ────────────────────────────────────────────

NOM = {"start_sec": 55.0, "peak_sec": 60.25, "end_sec": 68.0,
       "reasons": ["whistle", "surge"], "score": 0.5}


def test_nomination_marker_from_dict():
    m = nomination_to_marker(NOM)
    assert m["type"] == "fp_nomination"
    assert m["time"] == 60.25
    assert m["score"] == 0.5
    assert m["start"] == 55 and m["end"] == 68
    assert "whistle" in m["label"] and "surge" in m["label"]


def test_nomination_marker_from_object():
    from analysis.no_track import Nomination
    m = nomination_to_marker(Nomination(55.0, 60.25, 68.0, ["settle_burst"], 0.7))
    assert m["type"] == "fp_nomination" and m["time"] == 60.25
    assert "settle_burst" in m["label"]


def test_markers_from_nominations_maps_all():
    out = markers_from_nominations([NOM, NOM])
    assert len(out) == 2 and all(m["type"] == "fp_nomination" for m in out)


def test_negative_time_clamped_to_zero():
    assert nomination_to_marker({**NOM, "peak_sec": -2.0})["time"] == 0


# ── merging ──────────────────────────────────────────────────────────

def test_merge_drops_same_type_within_half_second():
    base = [{"type": "fp_goal", "time": 100.0}]
    new = [{"type": "fp_goal", "time": 100.4}, {"type": "fp_goal", "time": 101.0}]
    merged = merge_markers(base, new)
    assert [m["time"] for m in merged] == [100.0, 101.0]


def test_merge_keeps_different_type_at_same_time():
    base = [{"type": "click", "time": 100.0}]
    merged = merge_markers(base, [{"type": "fp_goal", "time": 100.0}])
    assert len(merged) == 2


def test_merge_sorts_and_preserves_camera_markers():
    base = [{"type": "click", "time": 300.0}, {"type": "start", "time": 0.0}]
    merged = merge_markers(base, [{"type": "fp_shot", "time": 150.0}])
    assert [m["type"] for m in merged] == ["start", "fp_shot", "click"]


# ── write_mark_fp against a fake game folder ─────────────────────────

def _game(tmp_path: Path, with_camera_mark=True) -> Path:
    video = tmp_path / "20260614_085233.mp4"
    video.write_bytes(b"\x00" * 16)
    if with_camera_mark:
        data = tmp_path / ".data"
        data.mkdir()
        (data / "20260614_085233.mark").write_text(
            json.dumps([{"type": "start", "time": 0},
                        {"type": "click", "time": 1255.0}]),
            encoding="utf-8")
    return video


def test_write_creates_data_folder_and_merges_camera(tmp_path):
    video = _game(tmp_path)
    out = write_mark_fp(video, markers_from_events([_event(EventType.GOAL, 1254.3)]))
    assert out == tmp_path / ".data" / "20260614_085233.mark.fp"
    entries = load_marker_file(out)
    types = [m["type"] for m in entries]
    assert types == ["start", "fp_goal", "click"]  # camera markers carried in
    # The camera .mark itself is never modified.
    cam = load_marker_file(tmp_path / ".data" / "20260614_085233.mark")
    assert [m["type"] for m in cam] == ["start", "click"]


def test_write_is_idempotent(tmp_path):
    video = _game(tmp_path)
    marks = markers_from_nominations([NOM])
    write_mark_fp(video, marks)
    first = load_marker_file(mark_fp_path(video))
    write_mark_fp(video, marks)
    second = load_marker_file(mark_fp_path(video))
    assert first == second
    assert sum(1 for m in second if m["type"] == "fp_nomination") == 1


def test_existing_mark_fp_is_the_base_not_camera_mark(tmp_path):
    video = _game(tmp_path)
    write_mark_fp(video, [{"type": "fp_marker", "time": 42.0}])
    # Player edits land in .mark.fp only; a stale .mark must not resurrect.
    out = write_mark_fp(video, [{"type": "fp_shot", "time": 50.0}])
    types = [m["type"] for m in load_marker_file(out)]
    assert types.count("start") == 1  # from the first write's merge, not doubled
    assert "fp_marker" in types and "fp_shot" in types


def test_write_without_camera_mark(tmp_path):
    video = _game(tmp_path, with_camera_mark=False)
    out = write_mark_fp(video, [{"type": "fp_goal", "time": 9.5}])
    assert [m["type"] for m in load_marker_file(out)] == ["fp_goal"]


def test_camera_mark_path_prefers_data_folder(tmp_path):
    video = _game(tmp_path)
    (tmp_path / "20260614_085233.mark").write_text("[]", encoding="utf-8")
    assert camera_mark_path(video) == tmp_path / ".data" / "20260614_085233.mark"
