"""Tests for telemetry-compensated interpolation (the ring-drift fix).

The defect: plain keyframe interpolation runs in raw frame
coordinates, so when the Falcon camera pans between keyframes the
ring cuts the corner and drifts off the player.  The fix unwraps
keyframes into a camera-independent field space (tracking.py),
interpolates there, and re-wraps at render time.

These tests pin: transform round-trips, compensation correctness on
synthetic pan and zoom ramps (a point fixed on the field must stay
fixed in field space while the camera moves), CameraTrack sampling,
the no-telemetry / broken-telemetry fallbacks, and the project
model's telemetry block.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import (
    ClipWindow,
    HighlightProject,
    Keyframe,
    RingSettings,
    TelemetrySettings,
    load_project,
    save_project,
)
from highlight.render import build_position_provider, overlay_frame_rgba
from highlight.tracking import (
    CameraCalibration,
    CameraState,
    CameraTrack,
    CompensatedInterpolator,
    field_to_frame,
    frame_to_field,
    load_camera_track,
    position_at,
    position_at_compensated,
)

CAL = CameraCalibration(fov_x_deg=95.0)
ASPECT = 16.0 / 9.0


def kf(t, x, y):
    return Keyframe(t, x, y)


def track_from(states):
    """CameraTrack from [(t, yaw, pitch, scale), ...]."""
    return CameraTrack([(t, CameraState(y, p, s)) for t, y, p, s in states])


# ── transform round-trips ────────────────────────────────────────────

@pytest.mark.parametrize(
    "fx, fy",
    [(0.5, 0.5), (0.1, 0.9), (0.83, 0.27), (0.0, 0.0), (1.0, 1.0)],
)
@pytest.mark.parametrize(
    "state",
    [
        CameraState(0.0, 0.0, 1.0),
        CameraState(32.5, 5.69, 1.0),
        CameraState(-48.25, 5.69, 1.0),
        CameraState(12.0, 4.0, 1.6),
        CameraState(-7.5, 6.5, 0.7),
    ],
)
def test_field_frame_round_trip(fx, fy, state):
    ref = CameraState(20.0, 5.0, 1.1)
    x, y = field_to_frame(fx, fy, state, ref, CAL, ASPECT)
    fx2, fy2 = frame_to_field(x, y, state, ref, CAL, ASPECT)
    assert fx2 == pytest.approx(fx, abs=1e-9)
    assert fy2 == pytest.approx(fy, abs=1e-9)


def test_frame_field_round_trip():
    ref = CameraState(-10.0, 5.69, 1.0)
    state = CameraState(41.0, 5.69, 1.35)
    fx, fy = frame_to_field(0.62, 0.44, state, ref, CAL, ASPECT)
    x, y = field_to_frame(fx, fy, state, ref, CAL, ASPECT)
    assert x == pytest.approx(0.62, abs=1e-9)
    assert y == pytest.approx(0.44, abs=1e-9)


def test_identity_when_state_equals_reference():
    ref = CameraState(33.0, 5.69, 1.2)
    assert field_to_frame(0.3, 0.6, ref, ref, CAL, ASPECT) == (0.3, 0.6)
    assert frame_to_field(0.3, 0.6, ref, ref, CAL, ASPECT) == (0.3, 0.6)


def test_pan_direction_and_magnitude():
    # Yaw decreases by 19 deg (camera pans one way) => a fixed field
    # point's frame position moves right by 19/95 = 0.2 frame widths.
    ref = CameraState(40.0, 5.69, 1.0)
    state = CameraState(21.0, 5.69, 1.0)
    x, y = field_to_frame(0.4, 0.5, state, ref, CAL, ASPECT)
    assert x == pytest.approx(0.6)
    assert y == pytest.approx(0.5)


def test_zoom_about_center():
    # Scale 2 relative to reference: offsets from center double,
    # the center itself does not move.
    ref = CameraState(0.0, 0.0, 1.0)
    state = CameraState(0.0, 0.0, 2.0)
    assert field_to_frame(0.5, 0.5, state, ref, CAL, ASPECT) == (0.5, 0.5)
    x, y = field_to_frame(0.75, 0.25, state, ref, CAL, ASPECT)
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(0.0)


def test_calibration_validation():
    with pytest.raises(ValueError, match="fov_x_deg"):
        CameraCalibration(fov_x_deg=10.0)
    assert CameraCalibration(fov_x_deg=95.0).pan_per_deg_x() == pytest.approx(1 / 95.0)


# ── CameraTrack sampling ─────────────────────────────────────────────

def test_camera_track_interpolates_and_clamps():
    track = track_from([(0.0, 30.0, 5.0, 1.0), (10.0, 10.0, 5.0, 2.0)])
    assert track.state_at(-5.0).yaw_deg == 30.0
    assert track.state_at(99.0).yaw_deg == 10.0
    mid = track.state_at(5.0)
    assert mid.yaw_deg == pytest.approx(20.0)
    assert mid.scale == pytest.approx(1.5)
    assert len(track) == 2 and track.start == 0.0 and track.end == 10.0


def test_camera_track_rejects_empty_and_unordered():
    with pytest.raises(ValueError):
        CameraTrack([])
    with pytest.raises(ValueError, match="non-decreasing"):
        track_from([(10.0, 0.0, 0.0, 1.0), (5.0, 0.0, 0.0, 1.0)])


def test_camera_track_duplicate_timestamps_do_not_crash():
    # Recording gaps clamp telemetry onto one video time (plateau).
    track = track_from(
        [(0.0, 30.0, 5.0, 1.0), (5.0, 28.0, 5.0, 1.0), (5.0, 12.0, 5.0, 1.0), (9.0, 12.0, 5.0, 1.0)]
    )
    assert track.state_at(5.0).yaw_deg == pytest.approx(12.0)  # post-gap state
    assert track.state_at(2.5).yaw_deg == pytest.approx(29.0)


# ── compensation correctness on synthetic ramps ──────────────────────

def glued_keyframes(field_xy, track, times):
    """Frame-space keyframes for a player standing at *field_xy*.

    Field space is anchored at the state of the first time, matching
    CompensatedInterpolator's reference choice.
    """
    ref = track.state_at(times[0])
    return [
        kf(t, *field_to_frame(*field_xy, track.state_at(t), ref, CAL, ASPECT))
        for t in times
    ]


def test_pan_ramp_point_stays_glued():
    # Camera holds, then pans 20 deg late in the clip — the shape of
    # the real defect (ring slides early / cuts the corner unpatched).
    track = track_from([(0.0, 30.0, 5.69, 1.0), (8.0, 30.0, 5.69, 1.0), (10.0, 10.0, 5.69, 1.0)])
    field_xy = (0.35, 0.5)
    frames = glued_keyframes(field_xy, track, [0.0, 10.0])
    ref = track.state_at(0.0)
    for t in (0.0, 2.5, 5.0, 8.0, 9.0, 9.5, 10.0):
        expected = field_to_frame(*field_xy, track.state_at(t), ref, CAL, ASPECT)
        got = position_at_compensated(frames, t, track, CAL, ASPECT)
        assert got == pytest.approx(expected, abs=1e-9), f"t={t}"
    # While the camera is still (t <= 8) the ring must not move at all.
    assert position_at_compensated(frames, 5.0, track, CAL, ASPECT)[0] == pytest.approx(0.35)


def test_pan_ramp_uncompensated_deviates():
    # Same setup: plain interpolation must visibly fail (this is the
    # defect being fixed — if this ever passes, the test rig is wrong).
    track = track_from([(0.0, 30.0, 5.69, 1.0), (8.0, 30.0, 5.69, 1.0), (10.0, 10.0, 5.69, 1.0)])
    frames = glued_keyframes((0.35, 0.5), track, [0.0, 10.0])
    plain_x = position_at(frames, 9.0)[0]
    glued_x = position_at_compensated(frames, 9.0, track, CAL, ASPECT)[0]
    assert abs(plain_x - glued_x) > 0.05  # > 5% of frame width off


def test_zoom_ramp_point_stays_glued_and_ring_scales():
    # Zoom holds, then ramps late (non-uniform in time — on a linear
    # ramp plain interpolation coincides with glued at the midpoint,
    # because both the scale and the smoothstep are halfway there).
    track = track_from([(0.0, 0.0, 5.0, 1.0), (8.0, 0.0, 5.0, 1.0), (10.0, 0.0, 5.0, 1.5)])
    field_xy = (0.7, 0.4)  # off-center: zoom must move the frame point
    frames = glued_keyframes(field_xy, track, [0.0, 10.0])
    interp = CompensatedInterpolator(frames, track, CAL, ASPECT)
    ref = track.state_at(0.0)
    for t in (0.0, 2.5, 5.0, 9.0, 10.0):
        expected = field_to_frame(*field_xy, track.state_at(t), ref, CAL, ASPECT)
        assert interp.position_at(t) == pytest.approx(expected, abs=1e-9), f"t={t}"
    assert interp.scale_at(5.0) == pytest.approx(1.0)   # zoom hasn't started
    assert interp.scale_at(9.0) == pytest.approx(1.25)
    assert interp.scale_at(10.0) == pytest.approx(1.5)
    # Plain interpolation starts growing the offset immediately.
    plain = position_at(frames, 5.0)
    assert abs(plain[0] - interp.position_at(5.0)[0]) > 0.01


def test_compensated_hits_keyframes_exactly():
    track = track_from([(0.0, 44.0, 5.69, 1.0), (6.0, 15.0, 5.69, 1.0), (12.0, 38.0, 5.69, 1.0)])
    frames = [kf(0.0, 0.32, 0.35), kf(6.0, 0.55, 0.37), kf(12.0, 0.36, 0.36)]
    interp = CompensatedInterpolator(frames, track, CAL, ASPECT)
    for k in frames:
        assert interp.position_at(k.t) == pytest.approx((k.x, k.y), abs=1e-9)


def test_compensated_equals_plain_when_camera_never_moves():
    track = track_from([(0.0, 22.0, 5.69, 1.0), (20.0, 22.0, 5.69, 1.0)])
    frames = [kf(2.0, 0.2, 0.4), kf(9.0, 0.7, 0.6), kf(15.0, 0.4, 0.3)]
    for t in (0.0, 2.0, 5.5, 9.0, 12.0, 15.0, 19.0):
        assert position_at_compensated(frames, t, track, CAL, ASPECT) == pytest.approx(
            position_at(frames, t), abs=1e-9
        )


def test_compensated_requires_keyframes():
    track = track_from([(0.0, 0.0, 0.0, 1.0)])
    with pytest.raises(ValueError, match="at least one keyframe"):
        CompensatedInterpolator([], track, CAL, ASPECT)


# ── load_camera_track (parser + sync wiring, stubbed) ────────────────

class _FakePoint:
    def __init__(self, t, yaw, pitch):
        self.timestamp_sec, self.yaw, self.pitch = t, yaw, pitch


class _FakeParsed:
    def __init__(self, points):
        self.points = points


class _FakeSync:
    def to_video_time(self, track_t):
        return track_t + 47.0  # head offset, no gaps


def test_load_camera_track_maps_to_video_time(monkeypatch):
    import telemetry.parser as parser_mod
    import telemetry.video_sync as sync_mod

    parsed = _FakeParsed([_FakePoint(0.0, 10.0, 5.69), _FakePoint(10.0, 30.0, 5.69)])
    monkeypatch.setattr(parser_mod, "parse_track_file", lambda *a, **k: parsed)
    monkeypatch.setattr(sync_mod, "sync_for", lambda *a, **k: _FakeSync())
    track = load_camera_track("game.track", "game.mp4")
    assert track is not None
    assert track.start == pytest.approx(47.0)
    assert track.state_at(52.0).yaw_deg == pytest.approx(20.0)


def test_load_camera_track_returns_none_without_sync(monkeypatch):
    import telemetry.parser as parser_mod
    import telemetry.video_sync as sync_mod

    monkeypatch.setattr(
        parser_mod, "parse_track_file", lambda *a, **k: _FakeParsed([_FakePoint(0.0, 1.0, 2.0)])
    )
    monkeypatch.setattr(sync_mod, "sync_for", lambda *a, **k: None)
    assert load_camera_track("game.track", "game.mp4") is None


# ── provider fallback behavior (render wiring) ───────────────────────

def make_project(**overrides) -> HighlightProject:
    kwargs = dict(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.6, 0.5)],
        ring=RingSettings(0.05, 0.10),
    )
    kwargs.update(overrides)
    return HighlightProject(**kwargs)


def test_provider_without_telemetry_is_frame_space():
    provider, mode = build_position_provider(make_project(), ASPECT)
    assert mode == "frame-space"
    assert provider(110.0) == (*position_at(make_project().keyframes, 110.0), 1.0)


def test_provider_with_missing_track_file_falls_back(tmp_path):
    project = make_project(
        telemetry=TelemetrySettings(track_file=str(tmp_path / "nope.track"))
    )
    provider, mode = build_position_provider(project, ASPECT)
    assert mode == "frame-space"
    assert provider(110.0)[2] == 1.0


def test_provider_with_unsyncable_track_falls_back(monkeypatch):
    import highlight.render as render_mod

    monkeypatch.setattr(render_mod, "load_camera_track", lambda *a, **k: None)
    project = make_project(telemetry=TelemetrySettings(track_file="game.track"))
    _, mode = build_position_provider(project, ASPECT)
    assert mode == "frame-space"


def test_provider_compensated_when_track_loads(monkeypatch):
    import highlight.render as render_mod

    track = track_from([(100.0, 30.0, 5.69, 1.0), (125.0, 12.0, 5.69, 1.0)])
    monkeypatch.setattr(render_mod, "load_camera_track", lambda *a, **k: track)
    project = make_project(telemetry=TelemetrySettings(track_file="game.track"))
    provider, mode = build_position_provider(project, ASPECT)
    assert mode == "telemetry-compensated"
    x, y, scale = provider(112.5)
    interp = CompensatedInterpolator(project.keyframes, track, CAL, ASPECT)
    assert (x, y) == pytest.approx(interp.position_at(112.5))
    assert scale == pytest.approx(1.0)


# ── overlay honors the provider ──────────────────────────────────────

def _gold_centroid(rgba):
    gold = np.all(rgba[:, :, :3] == np.array([255, 199, 44], dtype=np.uint8), axis=2)
    ys, xs = np.nonzero(gold)
    assert len(xs) > 0, "no gold ring pixels drawn"
    return xs.mean(), ys.mean()


def test_overlay_uses_provider_position():
    project = make_project()
    left = overlay_frame_rgba(
        project, 30, 320, 180, 30, provider=lambda t: (0.25, 0.5, 1.0)
    )
    right = overlay_frame_rgba(
        project, 30, 320, 180, 30, provider=lambda t: (0.75, 0.5, 1.0)
    )
    assert _gold_centroid(left)[0] == pytest.approx(0.25 * 320, abs=3)
    assert _gold_centroid(right)[0] == pytest.approx(0.75 * 320, abs=3)


def test_overlay_provider_scale_grows_ring():
    project = make_project()
    small = overlay_frame_rgba(
        project, 30, 320, 180, 30, provider=lambda t: (0.5, 0.5, 1.0)
    )
    big = overlay_frame_rgba(
        project, 30, 320, 180, 30, provider=lambda t: (0.5, 0.5, 2.0)
    )

    def ring_width(rgba):
        gold = np.all(rgba[:, :, :3] == np.array([255, 199, 44], dtype=np.uint8), axis=2)
        ys, xs = np.nonzero(gold)
        return xs.max() - xs.min()

    assert ring_width(big) > 1.8 * ring_width(small)


# ── project model: telemetry block ───────────────────────────────────

def test_telemetry_settings_validation():
    with pytest.raises(ValueError, match="track_file"):
        TelemetrySettings(track_file="  ")
    with pytest.raises(ValueError, match="pan_fov_deg"):
        TelemetrySettings(track_file="g.track", pan_fov_deg=500.0)
    with pytest.raises(ValueError, match="telemetry"):
        TelemetrySettings.from_dict(["not", "a", "dict"])
    with pytest.raises(ValueError, match="missing field"):
        TelemetrySettings.from_dict({})


def test_project_without_telemetry_serializes_unchanged():
    project = make_project()
    assert "telemetry" not in project.to_dict()
    clone = HighlightProject.from_dict(json.loads(json.dumps(project.to_dict())))
    assert clone.telemetry is None


def test_project_telemetry_round_trip(tmp_path):
    project = make_project(
        telemetry=TelemetrySettings(track_file="game.track", pan_fov_deg=92.0)
    )
    path = tmp_path / "p.json"
    save_project(project, path)
    raw = json.loads(path.read_text())
    assert raw["telemetry"] == {"track_file": "game.track", "pan_fov_deg": 92.0}
    clone = load_project(path)
    assert clone.telemetry.track_file == "game.track"
    assert clone.telemetry.pan_fov_deg == pytest.approx(92.0)


def test_load_project_resolves_track_beside_project(tmp_path):
    (tmp_path / "game.track").write_bytes(b"")
    (tmp_path / "game.mp4").write_bytes(b"")
    project = make_project(telemetry=TelemetrySettings(track_file="game.track"))
    path = tmp_path / "p.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.telemetry.track_file == str(tmp_path / "game.track")
