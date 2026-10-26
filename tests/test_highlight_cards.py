"""Tests for the Session 3 card wording + rasterization
(highlight/cards.py) and the player-info project model additions."""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.cards import (
    CARD_BG_RGB,
    SERIES_NAME,
    recruiting_end_card_lines,
    render_card_png,
    vertical_end_card_lines,
    vertical_title_card_lines,
)
from highlight.project import (
    ClipWindow,
    HighlightProject,
    Keyframe,
    PlayerInfo,
)


def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.5, 0.5)],
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


FULL_PLAYER = PlayerInfo(
    name="Abby Raymond",
    class_year="2028",
    position="Defense",
    team="Test Team",
    contact="coach@example.com",
    handle="@abbylax",
)


# ── PlayerInfo model ─────────────────────────────────────────────────

def test_player_info_strips_and_validates():
    player = PlayerInfo(name="  Abby Raymond  ", position=" Defense ")
    assert player.name == "Abby Raymond"
    assert player.position == "Defense"
    with pytest.raises(ValueError):
        PlayerInfo(name="   ")
    with pytest.raises(ValueError):
        PlayerInfo(name="Abby", class_year=2028)


def test_player_info_dict_omits_empty_fields():
    assert PlayerInfo(name="Abby").to_dict() == {"name": "Abby"}
    assert PlayerInfo(name="Abby", position="Defense").to_dict() == {
        "name": "Abby",
        "position": "Defense",
    }
    assert PlayerInfo.from_dict(FULL_PLAYER.to_dict()) == FULL_PLAYER


def test_project_round_trips_player_and_title():
    project = make_project(player=FULL_PLAYER, play_title="Crease stand")
    data = project.to_dict()
    assert data["player"]["name"] == "Abby Raymond"
    assert data["play_title"] == "Crease stand"
    assert HighlightProject.from_dict(data) == project


def test_project_without_player_serializes_absent():
    data = make_project().to_dict()
    assert "player" not in data
    assert "play_title" not in data


# ── Card wording ─────────────────────────────────────────────────────

def test_recruiting_end_card_lines_full():
    project = make_project(player=FULL_PLAYER)
    assert recruiting_end_card_lines(project) == [
        "Abby Raymond",
        "Class of 2028 · Defense",
        "Test Team",
        "coach@example.com",
    ]


def test_recruiting_end_card_lines_partial_and_absent():
    assert recruiting_end_card_lines(
        make_project(player=PlayerInfo(name="Abby Raymond"))
    ) == ["Abby Raymond"]
    assert recruiting_end_card_lines(
        make_project(player=PlayerInfo(name="Abby", class_year="2028"))
    ) == ["Abby", "Class of 2028"]
    assert recruiting_end_card_lines(make_project()) == []


def test_vertical_card_lines():
    project = make_project(player=FULL_PLAYER, play_title="Crease stand")
    assert vertical_title_card_lines(project) == [SERIES_NAME, "Crease stand"]
    assert vertical_end_card_lines(project) == [SERIES_NAME, "@abbylax"]
    bare = make_project()
    assert vertical_title_card_lines(bare) == [SERIES_NAME]
    assert vertical_end_card_lines(bare) == [SERIES_NAME]


# ── Rasterization ────────────────────────────────────────────────────

def test_render_card_png(tmp_path):
    out = render_card_png(["TITLE", "supporting line"], tmp_path / "card.png", 320, 180)
    img = Image.open(out)
    assert img.size == (320, 180)
    assert img.getpixel((0, 0)) == CARD_BG_RGB
    # Something (text / gold rule) is drawn over the field.
    pixels = set(img.getdata())
    assert len(pixels) > 1
    assert (255, 255, 255) in pixels


def test_render_card_png_rejects_empty():
    with pytest.raises(ValueError):
        render_card_png([], "unused.png", 320, 180)
