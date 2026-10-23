# Grading scoreboard

Human verdicts on detector output, kept as a regression suite.

## Protocol

For each graded game:

1. Run the detector. Sample detections stratified by type (all goals;
   every Nth shot/save/face-off/transition/turnover).
2. Label each sampled detection from screenshot triptychs (peak −2s /
   peak / +2s) or clip review: `consistent` (frames support the label),
   `contradicted` (frames rule it out), or `indeterminate` (stills
   can't judge — turnovers usually land here).
3. Hunt misses: take the hottest undetected windows (peak smoothed
   object speed, no detection within ±12s) and label each
   `real_miss` (a play the detector should have caught), `no_event`
   (sprint play, scrum, stoppage — nothing to label), or `covered`
   (the play was in fact detected just outside the window).
4. Store verdicts in `verdicts-YYYY-MM-DD.json` here, keyed by TRACK
   time (the detector's native timebase).

## Scoring

`scripts/grade_scoreboard.py --tracks-root <dir with the .track files>`
re-runs the current detector on every graded game and reports, per
game: consistent detections kept, contradicted detections still
produced, real misses still missed. `baseline.json` snapshots the
per-item produced flags of the reference run; a later run that loses
a consistent detection or resurrects a contradicted one is a
REGRESSION (exit 1). Eliminating a contradicted detection or catching
a previously-missed play is an improvement, printed as such.

Change one thing at a time. A tuning change is only accepted if it
improves the aggregate without regressing any graded game.

## Graded games

- 2026-06-14 — triage of the ORIGINAL detector (51 labels), reused as
  verdicts on its event peaks; miss windows graded 2026-10-23.
- 2026-06-16 — triage of the fixed detector (42 labels) + miss hunt.
- 2026-06-24 — triage of the guarded detector (40 labels) + miss hunt;
  first game with a scorebug and multiple recording gaps.
