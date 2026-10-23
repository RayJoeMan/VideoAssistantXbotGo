"""Score detector output against stored human verdicts.

The grading protocol (built across the June 2026 calibration games):
a human labels a stratified sample of detections (consistent /
contradicted / indeterminate, from screenshot or clip review) plus
the hottest undetected windows (real_miss / no_event / covered).
Verdicts live in grading/verdicts-*.json in the repo. This module
re-runs matching for any detector output so a code change can be
checked for regressions against every graded game at once: a change
regresses if it loses a previously-kept consistent detection, starts
producing a previously-eliminated contradicted one, or stops missing
nothing it used to catch. Catching a previously-missed real play is
an improvement, reported separately.
"""

from __future__ import annotations

from typing import Dict, List

from telemetry.models import Event

DET_TOLERANCE_SEC = 10.0   # Same play, allowing peak drift
MISS_TOLERANCE_SEC = 12.0  # Any event this close covers the window


def produced_detection(events: List[Event], item: dict) -> bool:
    """True if a same-type event peaks within tolerance of the item."""
    for e in events:
        if e.event_type.value != item["type"]:
            continue
        if abs(e.peak_time_sec - item["track_peak"]) <= DET_TOLERANCE_SEC:
            return True
    return False


def produced_in_window(events: List[Event], track_peak: float) -> bool:
    """True if ANY event peaks within the miss-window tolerance."""
    return any(
        abs(e.peak_time_sec - track_peak) <= MISS_TOLERANCE_SEC
        for e in events
    )


def score_game(events: List[Event], verdicts: dict) -> Dict[str, dict]:
    """Return per-item produced flags keyed for baseline comparison."""
    game = verdicts["game"]
    scored: Dict[str, dict] = {}
    for item in verdicts.get("detections", []):
        key = f"{game}:det:{item['type']}:{item['track_peak']:.1f}"
        scored[key] = {
            "kind": "detection",
            "verdict": item["verdict"],
            "produced": produced_detection(events, item),
        }
    for item in verdicts.get("miss_windows", []):
        key = f"{game}:miss:{item['track_peak']:.1f}"
        scored[key] = {
            "kind": "miss_window",
            "verdict": item["verdict"],
            "produced": produced_in_window(events, item["track_peak"]),
        }
    return scored


def summarize(scored: Dict[str, dict]) -> Dict[str, tuple]:
    """Aggregate counts: (numerator, denominator) per headline metric."""
    det = [s for s in scored.values() if s["kind"] == "detection"]
    miss = [s for s in scored.values() if s["kind"] == "miss_window"]
    cons = [s for s in det if s["verdict"] == "consistent"]
    contra = [s for s in det if s["verdict"] == "contradicted"]
    real_miss = [s for s in miss if s["verdict"] == "real_miss"]
    return {
        "consistent_kept": (sum(s["produced"] for s in cons), len(cons)),
        "contradicted_produced": (sum(s["produced"] for s in contra), len(contra)),
        "real_miss_still_missed": (
            sum(not s["produced"] for s in real_miss), len(real_miss)),
    }


def compare_to_baseline(
    scored: Dict[str, dict], baseline: Dict[str, bool]
) -> Dict[str, List[str]]:
    """Diff current produced flags against the baseline snapshot.

    Regressions: a consistent detection lost, or a contradicted
    detection (re)gained. Improvements: a contradicted detection
    eliminated, or a real_miss window now covered. Items missing from
    the baseline are reported as new (first run for that game).
    """
    regressions: List[str] = []
    improvements: List[str] = []
    new_items: List[str] = []
    for key, s in scored.items():
        if key not in baseline:
            new_items.append(key)
            continue
        was, now = baseline[key], s["produced"]
        if was == now:
            continue
        if s["kind"] == "detection" and s["verdict"] == "consistent" and was and not now:
            regressions.append(f"lost consistent detection {key}")
        elif s["kind"] == "detection" and s["verdict"] == "contradicted" and not was and now:
            regressions.append(f"contradicted detection returned {key}")
        elif s["kind"] == "detection" and s["verdict"] == "contradicted" and was and not now:
            improvements.append(f"eliminated contradicted detection {key}")
        elif s["kind"] == "miss_window" and s["verdict"] == "real_miss" and not was and now:
            improvements.append(f"previously-missed play now caught {key}")
        elif s["kind"] == "miss_window" and s["verdict"] == "real_miss" and was and not now:
            regressions.append(f"play that was caught is now missed {key}")
    return {"regressions": regressions, "improvements": improvements,
            "new_items": new_items}
