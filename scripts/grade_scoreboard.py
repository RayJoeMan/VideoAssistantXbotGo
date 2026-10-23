#!/usr/bin/env python3
"""Grading scoreboard: re-score the detector against every graded game.

Usage:
    python scripts/grade_scoreboard.py --tracks-root /path/to/tracks
    python scripts/grade_scoreboard.py --tracks-root ... --write-baseline

Verdict files live in grading/verdicts-*.json (see grading/README.md).
The baseline (grading/baseline.json) snapshots per-item produced
flags for the reference code; a run that loses a consistent detection
or resurrects a contradicted one exits 1.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analysis.detection import detect_events, DetectionConfig  # noqa: E402
from analysis.grading import compare_to_baseline, score_game, summarize  # noqa: E402
from telemetry.parser import parse_track_file  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tracks-root", required=True,
                    help="Directory containing the verdicts' track files")
    ap.add_argument("--grading-dir", default=str(
        Path(__file__).resolve().parent.parent / "grading"))
    ap.add_argument("--write-baseline", action="store_true",
                    help="Overwrite grading/baseline.json with this run")
    args = ap.parse_args()

    grading_dir = Path(args.grading_dir)
    baseline_path = grading_dir / "baseline.json"
    baseline = {}
    if baseline_path.exists() and not args.write_baseline:
        baseline = json.loads(baseline_path.read_text())

    all_scored: dict = {}
    any_regression = False
    for vf in sorted(glob.glob(str(grading_dir / "verdicts-*.json"))):
        verdicts = json.loads(Path(vf).read_text())
        track_path = Path(args.tracks_root) / verdicts["track_file"]
        if not track_path.exists():
            print(f"SKIP {verdicts['game']}: track not found at {track_path}")
            continue
        events = detect_events(parse_track_file(track_path), DetectionConfig())
        scored = score_game(events, verdicts)
        all_scored.update(scored)
        s = summarize(scored)
        ck, ct = s["consistent_kept"]
        xp, xt = s["contradicted_produced"]
        mm, mt = s["real_miss_still_missed"]
        print(f"{verdicts['game']}: {len(events)} events | "
              f"consistent kept {ck}/{ct} | "
              f"contradicted still produced {xp}/{xt} | "
              f"real misses still missed {mm}/{mt}")
        if baseline:
            diff = compare_to_baseline(scored, baseline)
            for r in diff["regressions"]:
                print(f"  REGRESSION: {r}")
                any_regression = True
            for i in diff["improvements"]:
                print(f"  improvement: {i}")

    if args.write_baseline:
        baseline_path.write_text(json.dumps(
            {k: v["produced"] for k, v in sorted(all_scored.items())},
            indent=1))
        print(f"baseline written: {baseline_path} ({len(all_scored)} items)")
    return 1 if any_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
