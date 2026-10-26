"""Tests for the highlight project model (highlight/project.py)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import (
    ClipWindow,
    ExportPreset,
    HighlightProject,
    Keyframe,
    load_project,
    save_project,
)


def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[
            Keyframe(100.0, 0.40, 0.60),
            Keyframe(112.0, 0.55, 0.62),
            Keyframe(125.0, 0.70, 0.58),
        ],
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


# ── round trip ───────────────────────────────────────────────────────

def test_round_trip_through_disk(tmp_path):
    project = make_project()
    path = save_project(project, tmp_path / "nested" / "project.json")
    loaded = load_project(path)
    assert loaded == project
    assert loaded.to_dict() == project.to_dict()


def test_saved_file_is_pretty_json_with_trailing_newline(tmp_path):
    path = save_project(make_project(), tmp_path / "project.json")
    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw)["version"] == 1
    assert '\n  "source_video"' in raw  # 2-space indent


def test_defaults_match_spec():
    project = make_project()
    assert project.tag_text == "#25"
    assert project.freeze_intro_s == 1.0
    assert project.dim.enabled is True
    assert project.dim.strength == 0.35
    presets = {p.name: (p.width, p.height) for p in project.export_presets}
    assert presets["recruiting"] == (1920, 1080)
    assert presets["vertical"] == (1080, 1920)
    assert project.output_duration == 26.0


def test_from_dict_ignores_unknown_keys_and_fills_defaults():
    data = make_project().to_dict()
    data["future_field"] = {"anything": True}
    del data["tag_text"]
    loaded = HighlightProject.from_dict(data)
    assert loaded.tag_text == "#25"


def test_relative_source_resolves_beside_project_file(tmp_path):
    video = tmp_path / "game.mp4"
    video.write_bytes(b"not really a video")
    path = save_project(make_project(), tmp_path / "project.json")
    loaded = load_project(path)
    assert loaded.source_video == str(video)


def test_preset_lookup_and_unknown_preset():
    project = make_project()
    assert project.preset("vertical").height == 1920
    with pytest.raises(ValueError, match="no export preset"):
        project.preset("square")


# ── validation ───────────────────────────────────────────────────────

def test_window_must_be_forward():
    with pytest.raises(ValueError, match="must be after"):
        ClipWindow(10.0, 10.0)
    with pytest.raises(ValueError, match="must be after"):
        ClipWindow(10.0, 9.0)


def test_keyframe_coords_bounded():
    with pytest.raises(ValueError, match="keyframe.x"):
        Keyframe(0.0, 1.2, 0.5)
    with pytest.raises(ValueError, match="keyframe.y"):
        Keyframe(0.0, 0.5, -0.1)


def test_keyframes_required_and_inside_window():
    with pytest.raises(ValueError, match="at least one keyframe"):
        make_project(keyframes=[])
    with pytest.raises(ValueError, match="outside the clip window"):
        make_project(keyframes=[Keyframe(99.0, 0.5, 0.5)])
    with pytest.raises(ValueError, match="outside the clip window"):
        make_project(keyframes=[Keyframe(126.0, 0.5, 0.5)])


def test_keyframe_times_strictly_increasing():
    with pytest.raises(ValueError, match="strictly increasing"):
        make_project(keyframes=[Keyframe(110.0, 0.5, 0.5), Keyframe(110.0, 0.6, 0.5)])
    with pytest.raises(ValueError, match="strictly increasing"):
        make_project(keyframes=[Keyframe(112.0, 0.5, 0.5), Keyframe(110.0, 0.6, 0.5)])


def test_freeze_intro_bounded():
    with pytest.raises(ValueError, match="freeze_intro_s"):
        make_project(freeze_intro_s=3.5)
    with pytest.raises(ValueError, match="freeze_intro_s"):
        make_project(freeze_intro_s=-0.5)


def test_dim_and_ring_ranges():
    project = make_project()
    with pytest.raises(ValueError, match="dim.strength"):
        type(project.dim)(strength=1.5)
    with pytest.raises(ValueError, match="ring.rx"):
        type(project.ring)(rx=0.0)


def test_preset_validation():
    with pytest.raises(ValueError, match="positive int"):
        ExportPreset("bad", 0, 1080)
    with pytest.raises(ValueError, match="non-empty"):
        ExportPreset("  ", 1920, 1080)
    with pytest.raises(ValueError, match="unique"):
        make_project(export_presets=[ExportPreset("a", 1, 1), ExportPreset("a", 2, 2)])


def test_bad_version_and_missing_fields():
    data = make_project().to_dict()
    data["version"] = 99
    with pytest.raises(ValueError, match="version"):
        HighlightProject.from_dict(data)
    data = make_project().to_dict()
    del data["window"]
    with pytest.raises(ValueError, match="missing field"):
        HighlightProject.from_dict(data)
    with pytest.raises(ValueError, match="must be a JSON object"):
        HighlightProject.from_dict([1, 2, 3])
