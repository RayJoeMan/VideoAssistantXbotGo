"""Tests for the voiceover mix builders (highlight/audio.py).

The duck trapezoid math is the source of truth; the ffmpeg volume
expression is checked structurally against the same numbers.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.audio import (
    DUCK_ATTACK_S,
    DUCK_RELEASE_S,
    TakeSpan,
    build_duck_volume_filter,
    build_mix_filters,
    build_take_filter,
    duck_gain_db_at,
    loudnorm_filter,
    merge_spans,
    silence_bed_filter,
    take_spans,
)


def take(start):
    return SimpleNamespace(start=start)


# ── spans ────────────────────────────────────────────────────────────

def test_take_spans_from_durations():
    spans = take_spans([take(2.0), take(10.0)], [3.0, None], 30.0)
    assert spans[0] == TakeSpan(2.0, 5.0)
    assert spans[1] == TakeSpan(10.0, 30.0)  # unprobed -> runs to the end


def test_take_spans_clamp_to_render_end():
    spans = take_spans([take(28.0)], [5.0], 30.0)
    assert spans[0].end == 30.0


def test_merge_spans_merges_close_and_sorts():
    merged = merge_spans([TakeSpan(2.3, 4.0), TakeSpan(0.0, 2.0)])
    assert merged == [TakeSpan(0.0, 4.0)]  # 0.3s gap < attack+release


def test_merge_spans_keeps_distant_spans():
    merged = merge_spans([TakeSpan(0.0, 2.0), TakeSpan(3.0, 4.0)])
    assert merged == [TakeSpan(0.0, 2.0), TakeSpan(3.0, 4.0)]


# ── duck math ────────────────────────────────────────────────────────

SPAN = [TakeSpan(5.0, 10.0)]


def test_duck_gain_outside_span_is_zero():
    assert duck_gain_db_at(SPAN, 2.0, 12.0) == 0.0
    assert duck_gain_db_at(SPAN, 11.0, 12.0) == 0.0
    assert duck_gain_db_at([], 7.0, 12.0) == 0.0


def test_duck_gain_full_depth_inside_span():
    assert duck_gain_db_at(SPAN, 5.0, 12.0) == pytest.approx(-12.0)
    assert duck_gain_db_at(SPAN, 7.5, 12.0) == pytest.approx(-12.0)
    assert duck_gain_db_at(SPAN, 10.0, 12.0) == pytest.approx(-12.0)


def test_duck_gain_ramps_before_start_and_after_end():
    mid_attack = 5.0 - DUCK_ATTACK_S / 2.0
    assert duck_gain_db_at(SPAN, mid_attack, 12.0) == pytest.approx(-6.0)
    mid_release = 10.0 + DUCK_RELEASE_S / 2.0
    assert duck_gain_db_at(SPAN, mid_release, 12.0) == pytest.approx(-6.0)


def test_duck_gain_ramps_are_monotonic():
    times = [4.7, 4.8, 4.9, 5.0]
    gains = [duck_gain_db_at(SPAN, t, 12.0) for t in times]
    assert gains == sorted(gains, reverse=True)  # deepening toward the span


# ── ffmpeg expression builder ────────────────────────────────────────

def test_duck_filter_none_without_spans_or_depth():
    assert build_duck_volume_filter([], 12.0) is None
    assert build_duck_volume_filter(SPAN, 0.0) is None


def test_duck_filter_expression_shape():
    expr = build_duck_volume_filter(SPAN, 12.0)
    assert expr.startswith("volume='pow(10\\,")
    assert "eval=frame" in expr
    assert "-12.000" in expr
    assert "4.850" in expr   # attack begins at start - 0.15
    assert "10.400" in expr  # release ends at end + 0.40
    assert expr.count("\\,") >= 3  # commas escaped for the filtergraph


def test_duck_filter_combines_spans_with_max():
    expr = build_duck_volume_filter([TakeSpan(1.0, 2.0), TakeSpan(5.0, 6.0)], 12.0)
    assert "max(" in expr


# ── mix assembly ─────────────────────────────────────────────────────

def test_loudnorm_filter_targets():
    text = loudnorm_filter(-16.0)
    assert "loudnorm=I=-16.000" in text
    assert "TP=-1.500" in text and "LRA=11.000" in text


def test_take_filter_delay_and_gain():
    plain = build_take_filter(3, SimpleNamespace(start=2.5, gain_db=0.0), "vo0")
    assert plain == "[3:a]aresample=48000,adelay=2500:all=1[vo0]"
    gained = build_take_filter(3, SimpleNamespace(start=2.5, gain_db=-3.0), "vo0")
    assert "volume=-3.000dB" in gained


def test_silence_bed_filter():
    text = silence_bed_filter(12.5, "game_a")
    assert text.startswith("anullsrc=r=48000:cl=stereo")
    assert "atrim=0:12.500" in text and "[game_a]" in text


def test_mix_filters_duck_then_mix_then_loudnorm():
    text = build_mix_filters("game_a", ["vo0", "vo1"], SPAN, 12.0, -16.0)
    assert "[game_a]volume=" in text and "[game_duck]" in text
    assert "[game_duck][vo0][vo1]amix=inputs=3:duration=first:normalize=0" in text
    assert "loudnorm=I=-16.000" in text and text.endswith("[aout]")


def test_mix_filters_without_duck_wire_game_directly():
    text = build_mix_filters("game_a", ["vo0"], [], 12.0, -16.0)
    assert "[game_duck]" not in text
    assert text.startswith("[game_a][vo0]amix=inputs=2")
