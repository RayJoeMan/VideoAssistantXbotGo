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

The second half of this module compensates that interpolation for
camera motion: when a project names Falcon telemetry, keyframes are
interpolated in a camera-independent field space instead, so pans
(and zooms, where a calibrated scale exists) stop dragging the ring
off the player.  See the "Telemetry-compensated interpolation"
section below for the model and its measured limits.
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


# ══════════════════════════════════════════════════════════════════════════
# Telemetry-compensated interpolation
#
# The defect (spotted by Joe on the Session 1 smoke render, 2026-10-26):
# plain `position_at` interpolates between keyframes in raw frame
# coordinates, but the Falcon is a panning panoramic camera — between two
# clicks the *frame itself* slides by up to ~0.27 frame widths (measured
# on the 2026-06-14 game), so the ring cuts the corner and drifts off
# the player through every pan, worst while the camera swings fast.
#
# The fix: interpolate in a camera-independent "field" space.  Each
# keyframe is unwrapped with the camera state at its own timestamp, the
# smoothstep runs there, and the result is re-wrapped with the camera
# state at render time.  A player standing still on the field then
# holds still in field space no matter how the camera moves.
#
# Camera model — the frame mapping is scale + translate about the
# frame center, driven by the per-frame telemetry the .track parser
# already exposes (see telemetry/models.py TrackPoint):
#
#   * yaw (deg) — the pan.  This is the trustworthy channel: smooth,
#     physically plausible, and it explains the measured frame motion
#     (fit on the 2026-06-14 game: content shift vs yaw r = -0.95).
#   * pitch (deg) — same form vertically, but the Falcon's pitch is
#     its fixed mount angle (5.69 deg for the whole of the 2026-06-14
#     game), so the term is ~0 in practice.  Its sign convention
#     (tilt up => content moves down) is modeled, not measured.
#   * scale — the model supports a zoom factor about the frame
#     center, but Falcon telemetry does NOT provide one that tracks
#     the frame: the Frame-line SZ and the Zoom-line CPSz values are
#     noisy per-frame estimates that do not correlate with the
#     measured frame scale (r ~= -0.2 / -0.05 on the calibration
#     window; apparent scale changes during pans are spatially
#     non-uniform — projection warp, not a uniform zoom).  Falcon
#     camera tracks therefore carry scale == 1.0 and compensation is
#     pan-only; the scale path exists for a future calibrated source.
#
# Calibration (2026-06-14 game, ORB affine fits of the real video):
# one degree of yaw moves frame content by ~10.1 px at 960 px width,
# i.e. ~0.0105 frame widths per degree — a ~95 deg horizontal FOV.
# Residual after compensation is ~0.03 frame widths RMS (projection
# warp the yaw channel cannot see), vs ~0.26 widths uncompensated.
# ══════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass
from typing import Optional, Tuple as _Tuple

DEFAULT_FOV_X_DEG = 95.0
DEFAULT_ASPECT = 16.0 / 9.0


@dataclass
class CameraState:
    """Where the camera was looking at one instant.

    ``scale`` is the frame's magnification relative to the reference
    state (1.0 = same zoom).  Falcon tracks always carry 1.0 — see the
    section note above.
    """

    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    scale: float = 1.0


@dataclass
class CameraCalibration:
    """Converts gimbal degrees to normalized frame units.

    ``fov_x_deg`` is the horizontal field of view of the rendered
    frame; one degree of yaw then shifts content by ``1 / fov_x_deg``
    frame widths.  Vertically the same pixels-per-degree applies
    (square pixels), so one degree of pitch shifts content by
    ``aspect / fov_x_deg`` frame heights.
    """

    fov_x_deg: float = DEFAULT_FOV_X_DEG

    def __post_init__(self) -> None:
        if not (20.0 <= self.fov_x_deg <= 180.0):
            raise ValueError(
                f"fov_x_deg must be between 20 and 180, got {self.fov_x_deg}"
            )

    def pan_per_deg_x(self) -> float:
        """Frame widths of content shift per degree of yaw."""
        return 1.0 / self.fov_x_deg

    def pan_per_deg_y(self, aspect: float = DEFAULT_ASPECT) -> float:
        """Frame heights of content shift per degree of pitch."""
        return aspect / self.fov_x_deg


def field_to_frame(
    fx: float,
    fy: float,
    state: CameraState,
    reference: CameraState,
    calibration: Optional[CameraCalibration] = None,
    aspect: float = DEFAULT_ASPECT,
) -> _Tuple[float, float]:
    """Map a field-space point into frame coordinates at *state*.

    Field space is defined as the frame as seen from *reference*:
    a point whose field coordinates are (fx, fy) appeared at (fx, fy)
    in a frame rendered with the reference camera state.
    """
    calib = calibration or CameraCalibration()
    s = state.scale / reference.scale
    x = 0.5 + s * (fx - 0.5) + (reference.yaw_deg - state.yaw_deg) * calib.pan_per_deg_x()
    y = 0.5 + s * (fy - 0.5) + (state.pitch_deg - reference.pitch_deg) * calib.pan_per_deg_y(aspect)
    return (x, y)


def frame_to_field(
    x: float,
    y: float,
    state: CameraState,
    reference: CameraState,
    calibration: Optional[CameraCalibration] = None,
    aspect: float = DEFAULT_ASPECT,
) -> _Tuple[float, float]:
    """Inverse of :func:`field_to_frame`: unwrap a frame-space click."""
    calib = calibration or CameraCalibration()
    s = state.scale / reference.scale
    fx = 0.5 + (x - 0.5 - (reference.yaw_deg - state.yaw_deg) * calib.pan_per_deg_x()) / s
    fy = 0.5 + (y - 0.5 - (state.pitch_deg - reference.pitch_deg) * calib.pan_per_deg_y(aspect)) / s
    return (fx, fy)


class CameraTrack:
    """Camera state as a function of source-video time.

    Built from (video_time, CameraState) samples in non-decreasing
    time order (see :func:`load_camera_track`); ``state_at`` linearly
    interpolates between samples and clamps outside their range.
    """

    def __init__(self, samples: Sequence) -> None:
        if not samples:
            raise ValueError("CameraTrack needs at least one sample")
        times = [float(t) for t, _ in samples]
        if any(b < a for a, b in zip(times, times[1:])):
            raise ValueError("camera samples must be in non-decreasing time order")
        self._times = times
        self._states = [state for _, state in samples]

    def __len__(self) -> int:
        return len(self._times)

    @property
    def start(self) -> float:
        return self._times[0]

    @property
    def end(self) -> float:
        return self._times[-1]

    def state_at(self, t: float) -> CameraState:
        """Interpolated camera state at source-video time *t*."""
        times, states = self._times, self._states
        if t <= times[0]:
            return states[0]
        if t >= times[-1]:
            return states[-1]
        i = bisect.bisect_right(times, t) - 1
        a, b = states[i], states[i + 1]
        span = times[i + 1] - times[i]
        if span <= 0.0:  # duplicate timestamps (a recording-gap plateau)
            return b
        u = (t - times[i]) / span
        return CameraState(
            yaw_deg=a.yaw_deg + (b.yaw_deg - a.yaw_deg) * u,
            pitch_deg=a.pitch_deg + (b.pitch_deg - a.pitch_deg) * u,
            scale=a.scale + (b.scale - a.scale) * u,
        )


class _FieldPoint:
    """Duck-typed keyframe (t/x/y) in field space, for `position_at`."""

    __slots__ = ("t", "x", "y")

    def __init__(self, t: float, x: float, y: float) -> None:
        self.t, self.x, self.y = t, x, y


class CompensatedInterpolator:
    """Keyframe interpolation in field space (camera-compensated).

    Keyframes arrive as clicks in frame space; each is unwrapped with
    the camera state at its own timestamp, interpolated there with the
    same smoothstep as :func:`position_at`, and re-wrapped with the
    camera state at the query time.  The reference state is the camera
    state at the first keyframe — field space is that frame's view.
    """

    def __init__(
        self,
        keyframes: Sequence,
        camera: CameraTrack,
        calibration: Optional[CameraCalibration] = None,
        aspect: float = DEFAULT_ASPECT,
    ) -> None:
        if not keyframes:
            raise ValueError("CompensatedInterpolator needs at least one keyframe")
        self._camera = camera
        self._calibration = calibration or CameraCalibration()
        self._aspect = aspect
        self.reference = camera.state_at(keyframes[0].t)
        self._field_keyframes = [
            _FieldPoint(
                k.t,
                *frame_to_field(
                    k.x,
                    k.y,
                    camera.state_at(k.t),
                    self.reference,
                    self._calibration,
                    aspect,
                ),
            )
            for k in keyframes
        ]

    def position_at(self, t: float) -> _Tuple[float, float]:
        """Compensated frame-space (x, y) at source time *t*."""
        fx, fy = position_at(self._field_keyframes, t)
        return field_to_frame(
            fx,
            fy,
            self._camera.state_at(t),
            self.reference,
            self._calibration,
            self._aspect,
        )

    def scale_at(self, t: float) -> float:
        """Magnification at *t* relative to the reference state.

        The renderer scales the ring by this so a zoomed-in player
        gets a proportionally larger ring.  Always 1.0 for Falcon
        telemetry (no trustworthy zoom channel — see section note).
        """
        return self._camera.state_at(t).scale / self.reference.scale


def position_at_compensated(
    keyframes: Sequence,
    t: float,
    camera: CameraTrack,
    calibration: Optional[CameraCalibration] = None,
    aspect: float = DEFAULT_ASPECT,
) -> _Tuple[float, float]:
    """One-shot compensated position (builds an interpolator per call).

    The renderer builds a :class:`CompensatedInterpolator` once and
    reuses it; this form exists for tests and one-off queries.
    """
    return CompensatedInterpolator(keyframes, camera, calibration, aspect).position_at(t)


def load_camera_track(track_file, source_video) -> Optional[CameraTrack]:
    """Build a :class:`CameraTrack` from a Falcon .track file.

    Telemetry timestamps are mapped onto the video's clock with
    ``telemetry.video_sync`` (head offset + recording gaps) — keyframes
    live in video time, so the camera samples must too.  Returns None
    when no sync can be built (no track start time, or the video has
    no readable .vdata sidecar): compensating on the wrong clock would
    be worse than not compensating, so callers fall back instead.
    Raises whatever the parser raises for a missing/corrupt file.
    """
    from telemetry.parser import parse_track_file
    from telemetry.video_sync import sync_for

    parsed = parse_track_file(track_file, compute_summary=False)
    sync = sync_for(parsed, source_video)
    if sync is None:
        return None
    samples = [
        (
            sync.to_video_time(p.timestamp_sec),
            CameraState(yaw_deg=p.yaw, pitch_deg=p.pitch, scale=1.0),
        )
        for p in parsed.points
    ]
    samples.sort(key=lambda s: s[0])
    return CameraTrack(samples)
