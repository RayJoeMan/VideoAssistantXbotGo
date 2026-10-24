#!/usr/bin/env python3
"""Nominate candidate play moments from a game video with no track file.

Usage:
    python scripts/motion_nominate.py VIDEO [--out nominations.json] [--workdir DIR]
    python scripts/motion_nominate.py --wav audio.wav --lowres low.mp4 [--out nominations.json]

Derivatives are extracted with ffmpeg (mono 16 kHz wav + 4 fps /
320 px grayscale rendition) and cached in the workdir, so a rerun is
cheap.  Output is a JSON list of
``{start_sec, peak_sec, end_sec, reasons, score}`` in video seconds.

Requires numpy.  No track file, no machine learning -- just audio cues
(referee whistles, crowd surges) and motion cues (camera settle
followed by a burst of action).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analysis.markers import markers_from_nominations, write_mark_fp
from analysis.no_track import (
    NominationConfig,
    analyze_files,
    extract_derivatives,
    probe_duration,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", nargs="?", help="game video file")
    ap.add_argument("--out", default="nominations.json", help="output JSON path")
    ap.add_argument("--workdir", default="/tmp/no_track_work",
                    help="where to cache derivatives")
    ap.add_argument("--wav", help="pre-extracted mono 16 kHz wav")
    ap.add_argument("--lowres", help="pre-extracted low-fps grayscale rendition")
    ap.add_argument("--v2", action="store_true",
                    help="use the v2 rule set (sustained pressure, post-goal "
                         "reset, luminance-normalized activity, rolling "
                         "thresholds) instead of v1")
    ap.add_argument("--markers", action="store_true",
                    help="also write the nominations as Falcon Player "
                         "markers (.data/<stem>.mark.fp beside the video; "
                         "requires a VIDEO argument)")
    args = ap.parse_args()

    if args.markers and not args.video:
        ap.error("--markers needs a VIDEO (the marker file lives beside it)")
        return

    if args.wav and args.lowres:
        wav, low = Path(args.wav), Path(args.lowres)
        duration = probe_duration(low)
    elif args.video:
        wav, low = extract_derivatives(args.video, args.workdir)
        duration = probe_duration(args.video)
    else:
        ap.error("give a VIDEO, or both --wav and --lowres")
        return

    config = NominationConfig.v2() if args.v2 else None
    result = analyze_files(wav, low, duration=duration, config=config)
    Path(args.out).write_text(json.dumps(result["nominations"], indent=1))
    noms = result["nominations"]
    print(f"video: {duration:.0f}s  whistles: {len(result['whistles'])}  "
          f"surges: {len(result['surges'])}  nominations: {len(noms)}"
          f"  rules: {'v2' if args.v2 else 'v1'}")
    print(f"wrote {args.out}")
    if args.markers:
        marks = markers_from_nominations(noms)
        path = write_mark_fp(Path(args.video), marks)
        print(f"wrote {len(marks)} markers to {path}")


if __name__ == "__main__":
    main()
