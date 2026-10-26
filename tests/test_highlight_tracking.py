"""Tests for keyframe interpolation (highlight/tracking.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import Keyframe
from highlight.tracking import position_at, sample_positions, smoothstep


def kf(t, x, y):
    return Keyframe(t, x, y)


# ── smoothstep ───────────────────────────────────────────────────────

def test_smoothstep_endpoints_and_midpoint():
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0
    assert smoothstep(0.5) == 0.5


def test_smoothstep_clamps_outside_unit_interval():
    assert smoothstep(-0.25) == 0.0
    assert smoothstep(1.75) == 1.0


def test_smoothstep_quarter_value():
    # s(0.25) = 0.25^2 * (3 - 0.5) = 0.15625 exactly
    assert smoothstep(0.25) == pytest.approx(0.15625)
    assert smoothstep(0.75) == pytest.approx(0.84375)


# ── position_at ──────────────────────────────────────────────────────

def test_single_keyframe_is_constant():
    frames = [kf(10.0, 0.3, 0.7)]
    assert position_at(frames, 0.0) == (0.3, 0.7)
    assert position_at(frames, 10.0) == (0.3, 0.7)
    assert position_at(frames, 999.0) == (0.3, 0.7)


def test_clamps_before_first_and_after_last():
    frames = [kf(10.0, 0.2, 0.4), kf(20.0, 0.8, 0.6)]
    assert position_at(frames, 5.0) == (0.2, 0.4)
    assert position_at(frames, 25.0) == (0.8, 0.6)


def test_exact_keyframe_hits():
    frames = [kf(10.0, 0.2, 0.4), kf(20.0, 0.8, 0.6), kf(30.0, 0.5, 0.5)]
    assert position_at(frames, 10.0) == (0.2, 0.4)
    assert position_at(frames, 20.0) == (0.8, 0.6)
    assert position_at(frames, 30.0) == (0.5, 0.5)


def test_midpoint_is_average_of_neighbors():
    frames = [kf(10.0, 0.2, 0.4), kf(20.0, 0.8, 0.6)]
    x, y = position_at(frames, 15.0)
    assert x == pytest.approx(0.5)
    assert y == pytest.approx(0.5)


def test_easing_is_not_linear():
    frames = [kf(0.0, 0.0, 0.0), kf(10.0, 1.0, 1.0)]
    x, _ = position_at(frames, 2.5)  # u=0.25 -> s=0.15625, slower than linear
    assert x == pytest.approx(0.15625)
    x, _ = position_at(frames, 7.5)  # u=0.75 -> s=0.84375
    assert x == pytest.approx(0.84375)


def test_second_segment_selected():
    frames = [kf(0.0, 0.0, 0.0), kf(10.0, 0.4, 0.4), kf(20.0, 0.4, 0.9)]
    x, y = position_at(frames, 15.0)
    assert x == pytest.approx(0.4)
    assert y == pytest.approx(0.65)


def test_empty_keyframes_raise():
    with pytest.raises(ValueError, match="at least one keyframe"):
        position_at([], 5.0)


def test_sample_positions_matches_point_queries():
    frames = [kf(0.0, 0.1, 0.2), kf(10.0, 0.9, 0.8)]
    times = [0.0, 2.5, 5.0, 10.0, 12.0]
    assert sample_positions(frames, times) == [position_at(frames, t) for t in times]
