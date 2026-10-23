"""Tests for the grading scoreboard matching/diff logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analysis.grading import compare_to_baseline, produced_detection, score_game
from telemetry.models import Event, EventType


def _ev(etype, peak):
    return Event(etype, peak - 1.0, peak + 1.0, peak, confidence=0.8)


def test_produced_detection_matches_type_and_window():
    events = [_ev(EventType.SHOT, 105.0)]
    item = {"type": "shot", "track_peak": 100.0}
    assert produced_detection(events, item) is True
    assert produced_detection(events, {"type": "save", "track_peak": 100.0}) is False
    assert produced_detection(events, {"type": "shot", "track_peak": 130.0}) is False


def test_score_and_compare_flags_regression_and_improvement():
    verdicts = {
        "game": "2099-01-01",
        "detections": [
            {"type": "shot", "track_peak": 100.0, "verdict": "consistent"},
            {"type": "save", "track_peak": 200.0, "verdict": "contradicted"},
        ],
        "miss_windows": [
            {"track_peak": 300.0, "verdict": "real_miss"},
        ],
    }
    baseline_run = score_game(
        [_ev(EventType.SHOT, 100.0), _ev(EventType.SAVE, 200.0)], verdicts)
    baseline = {k: v["produced"] for k, v in baseline_run.items()}

    # Later run: loses the good shot, keeps the bad save, catches the miss
    later = score_game([_ev(EventType.SAVE, 200.0), _ev(EventType.SHOT, 300.0)],
                       verdicts)
    diff = compare_to_baseline(later, baseline)
    assert any("lost consistent" in r for r in diff["regressions"])
    assert any("now caught" in i for i in diff["improvements"])

    # Run that eliminates the bad save: improvement, no regression there
    cleaner = score_game([_ev(EventType.SHOT, 100.0)], verdicts)
    diff2 = compare_to_baseline(cleaner, baseline)
    assert any("eliminated contradicted" in i for i in diff2["improvements"])
    assert not any("contradicted" in r for r in diff2["regressions"])
