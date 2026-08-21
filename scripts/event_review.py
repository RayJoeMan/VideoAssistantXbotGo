#!/usr/bin/env python3
"""Review / label / evaluate detected events — the ground-truth loop.

This turns the classifier from guesswork into measured performance. There is
no built-in ground truth in FALCON tracks, so the loop is:

  # 1. See what the detector finds (one game or a whole folder of games)
  python scripts/event_review.py analyze TRACK [TRACK...]
  python scripts/event_review.py analyze --folder /media/joe/Vault/falcon

  # 2. Export EVERY detected event as a clip you can quickly watch
  python scripts/event_review.py export VIDEO TRACK OUTDIR

  # 3. Generate a label sheet (JSONL) pre-filled with predictions
  python scripts/event_review.py labels TRACK labels.jsonl

  # 4. After marking each event correct/wrong (and the right type), measure
  python scripts/event_review.py evaluate TRACK labels.jsonl

Label sheet format (JSONL, one event per line):
  {"id": 0, "predicted_type": "goal", "start_sec": 1254.3, ...,
   "correct": true, "actual_type": "goal", "notes": ""}
  - correct: true | false | null (null = not yet reviewed)
  - actual_type: set only when correct is false (what it really was)
  - Add a row with "predicted_type": "MISSED" and "actual_type": "shot" for
    real events the detector never found (adds false-negatives).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from telemetry.parser import parse_track_file  # noqa: E402
from analysis.detection import detect_events  # noqa: E402
from export.ffmpeg import ExportConfig, extract_clip_from_event  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════════════════

def _load_track(path: Path):
    return parse_track_file(path)


def _detect(path: Path, min_confidence: float):
    track = _load_track(path)
    events = detect_events(track)
    if min_confidence > 0:
        events = [e for e in events if e.confidence >= min_confidence]
    return track, events


def _event_dict(idx: int, event) -> dict:
    return {
        "id": idx,
        "predicted_type": event.event_type.value,
        "start_sec": round(event.start_time_sec, 2),
        "end_sec": round(event.end_time_sec, 2),
        "peak_sec": round(event.peak_time_sec, 2),
        "duration_sec": round(event.duration_sec, 2),
        "confidence": round(event.confidence, 3),
        "frame_range": list(event.frame_range),
        "tags": list(event.tags),
        "description": event.description,
    }


def _find_tracks(folder: Path) -> list:
    """All .track files under a game folder (skips stray vendor copies)."""
    tracks = []
    for p in sorted(folder.rglob("*.track")):
        # FALCON keeps telemetry in a hidden .data subfolder
        if ".data" in p.parts:
            tracks.append(p)
        else:
            tracks.append(p)
    return tracks


# ══════════════════════════════════════════════════════════════════════════
# Subcommands
# ══════════════════════════════════════════════════════════════════════════

def cmd_analyze(args) -> int:
    """Print a table of detected events per game (optionally as JSON)."""
    paths = [Path(p) for p in args.track]
    if args.folder:
        paths.extend(_find_tracks(Path(args.folder)))
    if not paths:
        print("no tracks given (pass TRACK paths or --folder)")
        return 2

    all_events: dict = {}
    for p in paths:
        track, events = _detect(p, args.min_confidence)
        game = p.stem
        print(
            f"\n=== {game} | {track.metadata.total_duration_sec:.0f}s | "
            f"{len(track.points)} frames | {len(events)} events ==="
        )
        for i, e in enumerate(events):
            print(
                f"  {i:3d} {e.event_type.value:10s} "
                f"t={e.start_time_sec:7.1f}-{e.end_time_sec:7.1f}s "
                f"conf={e.confidence:.2f} {e.description}"
            )
        all_events[game] = [_event_dict(i, e) for i, e in enumerate(events)]

    if args.json:
        Path(args.json).write_text(json.dumps(all_events, indent=2))
        print(f"\nwrote {args.json}")
    return 0


def cmd_export(args) -> int:
    """Export every detected event as a clip + sidecar + manifest."""
    video = Path(args.video)
    if not video.exists():
        print(f"video not found: {video}")
        return 2
    track, events = _detect(Path(args.track), args.min_confidence)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = ExportConfig()

    manifest = []
    success = 0
    for i, e in enumerate(events):
        name = f"evt_{i:03d}_{e.event_type.value}.mp4"
        try:
            clip = extract_clip_from_event(
                video, e, outdir / name, config=cfg, add_title=args.titles
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  skip {name}: {exc}")
            continue
        side = _event_dict(i, e)
        side["clip"] = clip.name
        side["clip_start_sec"] = round(max(0.0, e.start_time_sec - cfg.pre_roll_sec), 2)
        side["clip_end_sec"] = round(e.end_time_sec + cfg.post_roll_sec, 2)
        (outdir / f"{clip.stem}.json").write_text(json.dumps(side, indent=2))
        manifest.append(side)
        success += 1
        print(
            f"  {i:3d} {name}  ({e.event_type.value}, t={e.start_time_sec:.1f}s, "
            f"conf={e.confidence:.2f})"
        )

    (outdir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(m) for m in manifest) + "\n"
    )
    print(f"\nexported {success}/{len(events)} review clips to {outdir}")
    if manifest:
        print("next: watch the clips, then run 'labels' + 'evaluate' to build")
        print("ground truth and recalibrate the classifier.")
    return 0


def cmd_labels(args) -> int:
    """Write a JSONL label sheet pre-filled with predictions."""
    track, events = _detect(Path(args.track), args.min_confidence)
    out = Path(args.out)
    with out.open("w") as f:
        for i, e in enumerate(events):
            rec = _event_dict(i, e)
            rec["correct"] = None      # user: true / false
            rec["actual_type"] = None  # user: set when correct is false
            rec["notes"] = ""
            f.write(json.dumps(rec) + "\n")
    print(f"wrote {len(events)} labels to {out}")
    print("edit each line: set \"correct\": true/false, and if wrong set")
    print("\"actual_type\" (shot|goal|save|transition|face_off|turnover).")
    print('Add rows with "predicted_type": "MISSED" for plays the detector missed.')
    return 0


def score_labels(labels: list) -> dict:
    """Compute per-type confusion from reviewed labels.

    Returns {"tp": Counter, "fp": Counter, "fn": Counter, "unlabeled": int,
             "total": int}
    """
    tp, fp, fn = Counter(), Counter(), Counter()
    unlabeled = 0
    for lab in labels:
        pred = lab.get("predicted_type")
        correct = lab.get("correct")
        actual = lab.get("actual_type")

        if pred == "MISSED":
            fn[actual or "unknown"] += 1
            continue
        if correct is None:
            unlabeled += 1
            continue
        if correct:
            tp[pred] += 1
        else:
            fp[pred] += 1
            if actual:
                fn[actual] += 1
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "unlabeled": unlabeled, "total": len(labels),
    }


def cmd_evaluate(args) -> int:
    """Measure precision/recall/F1 from a reviewed label sheet."""
    labels = [
        json.loads(line)
        for line in Path(args.labels).read_text().splitlines()
        if line.strip()
    ]
    scores = score_labels(labels)
    tp, fp, fn = scores["tp"], scores["fp"], scores["fn"]

    print(
        f"\nGround-truth evaluation ({scores['total']} labels, "
        f"{scores['unlabeled']} not yet reviewed)"
    )
    print(f"{'type':12s} {'TP':>4s} {'FP':>4s} {'FN':>4s} "
          f"{'Prec':>6s} {'Rec':>6s} {'F1':>6s}")
    types = sorted(set(tp) | set(fp) | set(fn))
    for t in types:
        prec = tp[t] / (tp[t] + fp[t]) if (tp[t] + fp[t]) else 0.0
        rec = tp[t] / (tp[t] + fn[t]) if (tp[t] + fn[t]) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"{t:12s} {tp[t]:4d} {fp[t]:4d} {fn[t]:4d} "
              f"{prec:6.2f} {rec:6.2f} {f1:6.2f}")

    total_tp = sum(tp.values())
    total_fp = sum(fp.values())
    total_fn = sum(fn.values())
    prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    print("-" * 44)
    print(f"{'ALL':12s} {total_tp:4d} {total_fp:4d} {total_fn:4d} "
          f"{prec:6.2f} {rec:6.2f} {f1:6.2f}")
    print("\nUse these numbers (not guesses) to recalibrate DetectionConfig in")
    print("src/analysis/detection.py, or run with --json for machine output.")
    if args.json:
        Path(args.json).write_text(json.dumps({
            t: {"tp": tp[t], "fp": fp[t], "fn": fn[t]}
            for t in types
        }, indent=2))
        print(f"wrote {args.json}")
    return 0


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review/label/evaluate detected events (ground-truth loop)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="list detected events per game")
    p_analyze.add_argument("track", nargs="*", help=".track file(s)")
    p_analyze.add_argument("--folder", help="scan a folder of games")
    p_analyze.add_argument("--json", help="also write events to this JSON file")
    p_analyze.add_argument("--min-confidence", type=float, default=0.0)
    p_analyze.set_defaults(func=cmd_analyze)

    p_export = sub.add_parser("export", help="export all events as review clips")
    p_export.add_argument("video")
    p_export.add_argument("track")
    p_export.add_argument("outdir")
    p_export.add_argument("--titles", action="store_true", help="burn titles")
    p_export.add_argument("--min-confidence", type=float, default=0.0)
    p_export.set_defaults(func=cmd_export)

    p_labels = sub.add_parser("labels", help="generate a JSONL label sheet")
    p_labels.add_argument("track")
    p_labels.add_argument("out")
    p_labels.add_argument("--min-confidence", type=float, default=0.0)
    p_labels.set_defaults(func=cmd_labels)

    p_eval = sub.add_parser("evaluate", help="precision/recall from labels")
    p_eval.add_argument("track")
    p_eval.add_argument("labels")
    p_eval.add_argument("--json", help="also write metrics to this JSON file")
    p_eval.set_defaults(func=cmd_evaluate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
