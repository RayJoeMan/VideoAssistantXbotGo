"""Tests for the event review/label/evaluate toolchain (no ffmpeg needed)."""

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from telemetry.models import Event, EventType  # noqa: E402
from telemetry.parser import parse_track_file  # noqa: E402


def _load_event_review():
    spec = importlib.util.spec_from_file_location(
        "event_review", ROOT / "scripts" / "event_review.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def review():
    return _load_event_review()


def _mini_track(num_frames: int = 80) -> str:
    """Small V1.4 track with sweeping position + high object speed.

    The position sweeps the full field over ~12s so a midfield crossing is
    slow enough to register as a transition.
    """
    parts = [
        "SDKV1.4.0-0710-Type15",
        "",
        "Lacrosse yawLim112.0 areaTH500 pitchInit5.00",
        "SDKV1.4.0-0710-Type15-pitInit5-YawLim112-ZoomState1-Start",
        "2026-07-19 14:53:18.240",
        "",
    ]
    base = datetime(2026, 7, 19, 14, 53, 18)
    for i in range(num_frames):
        t = base + timedelta(milliseconds=150 * i)
        ts = t.strftime("%H:%M:%S.") + f"{int(t.microsecond / 1000):03d}"
        fps = "" if i == 0 else "fps20 "
        yaw = 90 - (i / num_frames) * 180
        rx = int(i / num_frames * 2560)
        parts.append(
            f"UTC{ts} {fps}Frame{i + 1} Yaw{yaw:.2f} Pit4.98 Detect25 AFilter:P25"
        )
        parts.append(
            f"Crowd25 mot22 Dq22(v400,dx0)(v300,dx0)(v250,dx0) "
            f"F20 virx0 realx{rx}"
        )
        parts.append("YawMC x0 v0 Smooth(in0.0,out0.0)dir0 gear32")
        parts.append("")
    return "\n".join(parts)


@pytest.fixture
def mini_track(tmp_path):
    p = tmp_path / "mini.track"
    p.write_text(_mini_track())
    return p


# ══════════════════════════════════════════════════════════════════════════

class TestScoreLabels:
    def test_counts_tp_fp_fn(self, review):
        labels = [
            {"predicted_type": "goal", "correct": True, "actual_type": "goal"},
            {"predicted_type": "save", "correct": True, "actual_type": "save"},
            {"predicted_type": "goal", "correct": False, "actual_type": "transition"},
            {"predicted_type": "turnover", "correct": False, "actual_type": None},
        ]
        s = review.score_labels(labels)
        assert s["tp"]["goal"] == 1
        assert s["tp"]["save"] == 1
        assert s["fp"]["goal"] == 1          # misclassified goal
        assert s["fn"]["transition"] == 1    # it was really a transition
        assert s["fp"]["turnover"] == 1      # wrong without actual type
        assert s["unlabeled"] == 0
        assert s["total"] == 4

    def test_ignores_unlabeled(self, review):
        labels = [
            {"predicted_type": "goal", "correct": None, "actual_type": None},
            {"predicted_type": "shot", "correct": True, "actual_type": "shot"},
        ]
        s = review.score_labels(labels)
        assert s["unlabeled"] == 1
        assert s["tp"]["shot"] == 1
        assert sum(s["fp"].values()) == 0

    def test_handles_missed_events(self, review):
        labels = [
            {"predicted_type": "MISSED", "actual_type": "goal"},
            {"predicted_type": "MISSED", "actual_type": "shot"},
        ]
        s = review.score_labels(labels)
        assert s["fn"]["goal"] == 1
        assert s["fn"]["shot"] == 1


class TestEventDict:
    def test_shape(self, review):
        e = Event(
            event_type=EventType.GOAL,
            start_time_sec=10.0,
            end_time_sec=12.0,
            peak_time_sec=11.0,
            confidence=0.9,
            description="Goal at 11.0s",
            tags=["offense"],
        )
        d = review._event_dict(3, e)
        assert d["id"] == 3
        assert d["predicted_type"] == "goal"
        assert d["start_sec"] == 10.0
        assert d["confidence"] == 0.9
        assert d["tags"] == ["offense"]


class TestCmdLabels:
    def test_writes_valid_jsonl(self, review, mini_track, tmp_path):
        out = tmp_path / "labels.jsonl"
        args = review.argparse.Namespace(
            track=str(mini_track), out=str(out), min_confidence=0.0
        )
        rc = review.cmd_labels(args)
        assert rc == 0
        assert out.exists()
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert lines, "expected at least one detected event in the mini track"
        for line in lines:
            rec = json.loads(line)
            assert "predicted_type" in rec
            assert "correct" in rec and rec["correct"] is None
            assert "actual_type" in rec and rec["actual_type"] is None
            assert "start_sec" in rec and "peak_sec" in rec
