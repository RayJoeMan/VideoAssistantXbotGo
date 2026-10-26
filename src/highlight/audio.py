"""Voiceover mix construction — ducking envelopes, mix graph, loudnorm.

Pure builders plus one ffprobe helper.  The renderer composes these
pieces into the audio half of its filter_complex; everything here is
testable without ffmpeg or a real take.

Clocks: takes, duck spans and the mix all live on the OUTPUT timeline
(0 = first rendered frame, freeze intro included) — the clock a
narration take is recorded against.

Ducking model (spec Feature 3: game audio sits ``duck_db`` under the
VO while a take speaks): a trapezoid weight per take span — the gain
ramps down over ``DUCK_ATTACK_S`` *before* the span starts (so the
duck is already in place on the first syllable), holds at full depth
through the span, and releases over ``DUCK_RELEASE_S`` after it ends.
``duck_gain_db_at`` is the math source of truth; the ffmpeg
volume-expression builder renders the same trapezoids, and the tests
pin both to the same numbers.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence

DUCK_ATTACK_S = 0.15
DUCK_RELEASE_S = 0.40
SAMPLE_RATE = 48000
LOUDNORM_TRUE_PEAK = -1.5
LOUDNORM_LRA = 11.0


@dataclass
class TakeSpan:
    """The [start, end] output-time span one VO take occupies."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def take_spans(takes, durations, render_end: float) -> List[TakeSpan]:
    """Spans for *takes* given probed *durations* (parallel lists).

    A take whose duration could not be probed (None) is assumed to run
    to the end of the render — ducking a little too long beats ducking
    out from under the narrator mid-sentence.
    """
    spans = []
    for take, dur in zip(takes, durations):
        end = render_end if dur is None else min(take.start + dur, render_end)
        spans.append(TakeSpan(float(take.start), float(end)))
    return spans


def merge_spans(
    spans: Sequence[TakeSpan],
    min_gap: float = DUCK_ATTACK_S + DUCK_RELEASE_S,
) -> List[TakeSpan]:
    """Merge spans separated by less than *min_gap* (sorted output).

    Two takes a breath apart should hold one continuous duck — letting
    the game audio pump up and back down between them sounds broken.
    """
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: List[TakeSpan] = []
    for span in ordered:
        if merged and span.start - merged[-1].end < min_gap:
            last = merged[-1]
            merged[-1] = TakeSpan(last.start, max(last.end, span.end))
        else:
            merged.append(TakeSpan(span.start, span.end))
    return merged


def _trapezoid_weight(
    span: TakeSpan, t: float, attack: float, release: float
) -> float:
    """0..1 duck weight of one span at time *t* (pure math)."""
    up = (t - (span.start - attack)) / attack if attack > 0 else 1.0
    down = ((span.end + release) - t) / release if release > 0 else 1.0
    return min(max(min(up, down), 0.0), 1.0)


def duck_gain_db_at(
    spans: Sequence[TakeSpan],
    t: float,
    duck_db: float,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
) -> float:
    """Game-audio gain in dB at output time *t* (0 or negative).

    *spans* should be merged spans (see merge_spans); the deepest
    active trapezoid wins.
    """
    weight = 0.0
    for span in spans:
        weight = max(weight, _trapezoid_weight(span, t, attack, release))
    return -abs(duck_db) * weight


def _fmt(v: float) -> str:
    return f"{v:.3f}"


def _trapezoid_expr(span: TakeSpan, attack: float, release: float) -> str:
    """ffmpeg expression for one span's weight.  Commas are escaped
    (``\\,``) because the expression is embedded in a filtergraph."""
    up = f"(t-({_fmt(span.start - attack)}))/{_fmt(attack)}"
    down = f"({_fmt(span.end + release)}-t)/{_fmt(release)}"
    return f"clip(min({up}\\,{down})\\,0\\,1)"


def build_duck_volume_filter(
    spans: Sequence[TakeSpan],
    duck_db: float,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
) -> Optional[str]:
    """A volume filter ducking by *duck_db*, or None when unneeded.

    Returns None when there are no spans or the duck depth is zero —
    the caller then wires the game chain straight through.
    """
    if not spans or duck_db == 0:
        return None
    weights = [_trapezoid_expr(s, attack, release) for s in spans]
    combined = weights[0]
    for w in weights[1:]:
        combined = f"max({combined}\\,{w})"
    gain = f"({_fmt(-abs(duck_db))})*({combined})"
    return f"volume='pow(10\\,({gain})/20)':eval=frame"


def loudnorm_filter(target_lufs: float) -> str:
    """Single-pass loudnorm to *target_lufs* (spec: −16 LUFS)."""
    return (
        f"loudnorm=I={_fmt(target_lufs)}"
        f":TP={_fmt(LOUDNORM_TRUE_PEAK)}:LRA={_fmt(LOUDNORM_LRA)}"
    )


def build_take_filter(input_index: int, take, label: str) -> str:
    """One VO take as a mix input: resampled, delayed to its output
    start, trimmed by its per-take gain."""
    delay_ms = int(round(take.start * 1000))
    parts = [f"[{input_index}:a]aresample={SAMPLE_RATE}", f"adelay={delay_ms}:all=1"]
    if take.gain_db:
        parts.append(f"volume={_fmt(take.gain_db)}dB")
    parts.append(f"[{label}]")
    # The label rides on the last filter; rebuild as one chain.
    chain = ",".join(parts[:-1])
    return f"{chain}{parts[-1]}"


def silence_bed_filter(duration: float, label: str) -> str:
    """A silent stereo bed of *duration* seconds (the game chain for
    mic-off Falcon footage — the mix still needs a first input for
    amix's duration and for the duck to act on)."""
    return (
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
        f"atrim=0:{_fmt(duration)},asetpts=PTS-STARTPTS[{label}]"
    )


def build_mix_filters(
    game_label: str,
    vo_labels: Sequence[str],
    spans: Sequence[TakeSpan],
    duck_db: float,
    target_lufs: float,
    out_label: str = "aout",
) -> str:
    """Duck the game chain, mix the VO takes over it, loudnorm.

    Emits one or two filter strings joined by ';': an optional duck
    stage ``[game]volume=...[game_duck]`` and the final
    ``[...]amix=...,loudnorm=...[aout]``.  amix keeps the first
    (game/bed) input's duration and does not renormalize, so the
    loudnorm that follows sets the final level.
    """
    parts = []
    first = game_label
    duck = build_duck_volume_filter(spans, duck_db)
    if duck is not None:
        parts.append(f"[{game_label}]{duck}[game_duck]")
        first = "game_duck"
    inputs = "".join(f"[{label}]" for label in [first, *vo_labels])
    parts.append(
        f"{inputs}amix=inputs={1 + len(vo_labels)}:duration=first:normalize=0,"
        f"{loudnorm_filter(target_lufs)}[{out_label}]"
    )
    return ";".join(parts)


def probe_duration(path, ffprobe_bin: str = "ffprobe") -> Optional[float]:
    """Duration of a media file in seconds, or None if unprobeable."""
    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        duration = json.loads(result.stdout)["format"]["duration"]
        return float(duration)
    except Exception:
        return None
