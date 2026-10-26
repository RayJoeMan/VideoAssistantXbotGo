"""Output-timeline math for editorial beats (Session 2).

The Session 1 renderer maps output frames to source times with a
simple rule: hold the first frame for the freeze intro, then advance
1:1.  Beats break the 1:1 part — a slow-mo segment stretches source
time, a freeze mark inserts held frames mid-clip.  This module turns
(window, freeze_intro_s, beats) into an ordered list of segments that
tiles the output timeline exactly, and answers the two mapping
questions the renderer needs:

  * ``source_time_at_output(t)`` — which source instant an output
    instant shows (ring positions, segment trims);
  * ``output_time_at_source(t)`` — where a source instant lands in
    the render.

With no beats the timeline is [freeze intro] + [one 1.0x play segment]
and the mapping reduces to the Session 1 rule.  All times here are
seconds; segment source times use the project's SOURCE-video clock
(the same clock as keyframes and beats), output times use the
rendered clip's clock (0 = first output frame).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from .project import BEAT_FREEZE, BEAT_SLOWMO, Beat

SEG_PLAY = "play"
SEG_FREEZE = "freeze"


@dataclass
class TimelineSegment:
    """One tile of the output timeline.

    A ``play`` segment advances the source clock from ``src_start`` to
    ``src_end`` at ``rate`` (1.0 = real time, 0.5 = half-speed); a
    ``freeze`` segment holds the single source instant ``src_start``
    (== ``src_end``) for ``out_duration`` output seconds.
    """

    kind: str
    src_start: float
    src_end: float
    rate: float
    out_start: float
    out_duration: float

    @property
    def out_end(self) -> float:
        return self.out_start + self.out_duration

    @property
    def src_duration(self) -> float:
        return self.src_end - self.src_start


@dataclass
class Timeline:
    """An ordered, gap-free tiling of the output timeline."""

    segments: List[TimelineSegment] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Total rendered length in seconds."""
        if not self.segments:
            return 0.0
        last = self.segments[-1]
        return last.out_start + last.out_duration

    @property
    def src_start(self) -> float:
        return self.segments[0].src_start if self.segments else 0.0

    @property
    def src_end(self) -> float:
        return self.segments[-1].src_end if self.segments else 0.0

    def source_time_at_output(self, out_t: float) -> float:
        """Source instant shown at output time *out_t* (clamped)."""
        if not self.segments:
            return 0.0
        t = min(max(float(out_t), 0.0), self.duration)
        for seg in self.segments:
            if t <= seg.out_end or seg is self.segments[-1]:
                if seg.kind == SEG_FREEZE:
                    return seg.src_start
                shown = seg.src_start + (t - seg.out_start) * seg.rate
                return min(max(shown, seg.src_start), seg.src_end)
        return self.segments[-1].src_end  # unreachable; satisfies linters

    def output_time_at_source(self, src_t: float) -> float:
        """Output instant at which source time *src_t* is shown.

        For a source instant held by a freeze, this is the moment the
        hold begins.  Clamped to the timeline ends.
        """
        if not self.segments:
            return 0.0
        t = float(src_t)
        if t <= self.src_start:
            return 0.0
        for seg in self.segments:
            if seg.kind == SEG_FREEZE:
                if t == seg.src_start:
                    return seg.out_start
                continue
            if seg.src_start <= t <= seg.src_end:
                return seg.out_start + (t - seg.src_start) / seg.rate
        return self.duration


def build_timeline(
    window_start: float,
    window_end: float,
    freeze_intro_s: float,
    beats: Sequence[Beat],
) -> Timeline:
    """Tile the output timeline for one clip.

    Layout: the freeze intro (a hold on the window's first frame),
    then a walk along the source window — plain play at 1.0x, slow-mo
    beats at their rate, freeze beats as holds that consume no source
    time.  *beats* must be sorted by start and non-overlapping (the
    project model enforces this; the builder re-checks cheaply and
    raises ValueError rather than emitting a broken tiling).
    """
    segments: List[TimelineSegment] = []
    out_cursor = 0.0

    def add_play(src_start: float, src_end: float, rate: float) -> None:
        nonlocal out_cursor
        if src_end <= src_start:
            return
        dur = (src_end - src_start) / rate
        segments.append(
            TimelineSegment(SEG_PLAY, src_start, src_end, rate, out_cursor, dur)
        )
        out_cursor += dur

    def add_freeze(src_t: float, duration: float) -> None:
        nonlocal out_cursor
        if duration <= 0:
            return
        segments.append(
            TimelineSegment(SEG_FREEZE, src_t, src_t, 1.0, out_cursor, duration)
        )
        out_cursor += duration

    if freeze_intro_s > 0:
        add_freeze(window_start, float(freeze_intro_s))

    cursor = float(window_start)
    slowmo_end = None
    last_start = None
    for beat in beats:
        if last_start is not None and beat.start <= last_start:
            raise ValueError("beats must have strictly increasing start times")
        if slowmo_end is not None and beat.start < slowmo_end:
            raise ValueError("beats must not overlap")
        if beat.kind == BEAT_SLOWMO:
            add_play(cursor, beat.start, 1.0)
            add_play(beat.start, beat.end, beat.rate)
            cursor = beat.end
            slowmo_end = beat.end
        elif beat.kind == BEAT_FREEZE:
            add_play(cursor, beat.start, 1.0)
            add_freeze(beat.start, beat.duration)
            cursor = beat.start
        else:  # pragma: no cover - Beat validates its kind
            raise ValueError(f"unknown beat kind {beat.kind!r}")
        last_start = beat.start
    add_play(cursor, float(window_end), 1.0)
    return Timeline(segments)
