"""Keyframe interpolation — where is the player at time *t*?

The editor stores a handful of keyframes (a click every few seconds);
the renderer needs a position for every output frame.  Between two
keyframes we ease with the classic smoothstep polynomial
``s(u) = u^2 (3 - 2u)``: zero velocity at both ends, so the ring glides
out of a keyframe and settles into the next instead of sliding at a
constant speed and lurching at every click.  Outside the keyframed
range the position clamps to the nearest keyframe — the ring holds
still rather than extrapolating off-frame.

Keyframes are duck-typed: anything with ``t``/``x``/``y`` attributes,
sorted by strictly increasing ``t`` (the project model guarantees it).
"""

from __future__ import annotations

import bisect
from typing import List, Sequence, Tuple


def smoothstep(u: float) -> float:
    """Smoothstep easing on [0, 1]; inputs clamp into range."""
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return u * u * (3.0 - 2.0 * u)


def position_at(keyframes: Sequence, t: float) -> Tuple[float, float]:
    """Interpolated (x, y) at source time *t*, clamped at both ends."""
    if not keyframes:
        raise ValueError("position_at needs at least one keyframe")
    first, last = keyframes[0], keyframes[-1]
    if t <= first.t:
        return (first.x, first.y)
    if t >= last.t:
        return (last.x, last.y)
    times = [k.t for k in keyframes]
    i = bisect.bisect_right(times, t) - 1
    a, b = keyframes[i], keyframes[i + 1]
    u = (t - a.t) / (b.t - a.t)
    s = smoothstep(u)
    return (a.x + (b.x - a.x) * s, a.y + (b.y - a.y) * s)


def sample_positions(keyframes: Sequence, times: Sequence[float]) -> List[Tuple[float, float]]:
    """`position_at` over a sequence of times, in order."""
    return [position_at(keyframes, t) for t in times]
