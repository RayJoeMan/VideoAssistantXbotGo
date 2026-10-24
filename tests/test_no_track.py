"""Tests for the no-track nomination prototype (analysis/no_track.py).

All signals are synthetic: a tone burst in noise must read as a
whistle, a step up in an RMS envelope as a crowd surge, a shifted
texture as camera pan, and a quiet-then-burst motion timeline as a
settle_burst nomination.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analysis.no_track import (
    NominationConfig,
    build_nominations,
    detect_surges,
    detect_whistles,
    motion_series,
    pan_from_profiles,
)

SR = 16000


def _noise(sec: float, amp: float = 0.02, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(sec * SR)) * amp).astype(np.float32)


def test_whistle_tone_burst_detected():
    samples = _noise(3.0)
    tone = (0.5 * np.sin(2 * np.pi * 3000 * np.arange(int(0.4 * SR)) / SR)).astype(np.float32)
    samples[int(1.0 * SR): int(1.4 * SR)] += tone
    events = detect_whistles(samples, SR)
    assert len(events) == 1
    assert 0.9 <= events[0]["start_sec"] <= 1.1
    assert events[0]["end_sec"] - events[0]["start_sec"] >= 0.3


def test_no_whistle_in_plain_noise():
    assert detect_whistles(_noise(3.0, amp=0.05), SR) == []


def test_crowd_surge_detected():
    win = 0.25
    times = np.arange(0.5, 60.0, win)
    rms = np.ones_like(times)
    rms[(times >= 32) & (times < 36)] = 4.0   # the crowd erupts
    rms[times >= 36] = 1.5                     # ... and settles a bit higher
    events = detect_surges(times, rms, win_sec=win)
    assert len(events) == 1
    assert 30.5 <= events[0]["start_sec"] <= 33.0
    assert events[0]["ratio"] > 2.5


def test_no_surge_on_flat_envelope():
    times = np.arange(0.5, 60.0, 0.25)
    assert detect_surges(times, np.ones_like(times), win_sec=0.25) == []


def test_pan_from_shifted_texture():
    rng = np.random.default_rng(1)
    frame = rng.standard_normal((180, 320)).astype(np.float32)
    shifted = np.roll(frame, 3, axis=1)
    pan = pan_from_profiles(frame.mean(axis=0), shifted.mean(axis=0))
    assert abs(pan - 3.0) < 1.0
    still = pan_from_profiles(frame.mean(axis=0), frame.mean(axis=0))
    assert still == 0.0


def _fake_motion(duration: float = 60.0, fps: float = 4.0) -> dict:
    n = int(duration * fps) - 1
    t = (np.arange(n) + 1) / fps
    diff = np.full(n, 0.01)
    diff[(t >= 30) & (t <= 34)] = 0.20          # the play explodes at 30 s
    return {"t": t, "diff": diff, "pan": np.zeros(n)}


def test_settle_burst_nomination():
    noms = build_nominations(_fake_motion(), [], [], duration=60.0)
    hits = [n for n in noms if "settle_burst" in n["reasons"]]
    assert hits, f"expected a settle_burst nomination, got {noms}"
    assert 28.0 <= hits[0]["peak_sec"] <= 35.0
    assert hits[0]["start_sec"] < hits[0]["peak_sec"] < hits[0]["end_sec"]


def test_whistle_adds_reason():
    whistles = [{"start_sec": 29.5, "end_sec": 29.9, "peak_sec": 29.7,
                 "strength": 0.9}]
    noms = build_nominations(_fake_motion(), whistles, [], duration=60.0)
    assert any("whistle_play" in n["reasons"] for n in noms)


# ── v2 rules ─────────────────────────────────────────────────────────

def _fake_motion_full(duration: float = 120.0, fps: float = 4.0,
                      base: float = 0.01) -> dict:
    n = int(duration * fps) - 1
    t = (np.arange(n) + 1) / fps
    return {"t": t, "diff": np.full(n, base), "pan": np.zeros(n),
            "lum": np.full(n, 120.0), "ndiff": np.full(n, base)}


def test_motion_series_has_luminance_channels():
    a = np.full((180, 320), 100, dtype=np.uint8)
    b = np.full((180, 320), 150, dtype=np.uint8)
    m = motion_series([a, b])
    assert len(m["lum"]) == 1 and abs(m["lum"][0] - 150.0) < 1.0
    # Weber diff: |150-100| / (150+100+1) ~ 0.199, below the raw 50/255
    assert 0.15 < m["ndiff"][0] < 0.25
    assert abs(m["diff"][0] - 50.0 / 255.0) < 0.01


def test_v2_all_flags_off_matches_v1():
    motion = _fake_motion()
    plain = build_nominations(motion, [], [], duration=60.0)
    flagged = build_nominations(motion, [], [], duration=60.0,
                                config=NominationConfig())
    assert plain == flagged


def test_sustained_pressure_fires_at_run_end():
    motion = _fake_motion_full()
    t = motion["t"]
    motion["diff"][(t >= 40) & (t < 65)] = 0.20     # 25 s of pressure
    cfg = NominationConfig(sustained_pressure=True)
    noms = build_nominations(motion, [], [], duration=120.0, config=cfg)
    hits = [n for n in noms if "sustained_pressure" in n["reasons"]]
    assert hits, f"expected a sustained_pressure nomination, got {noms}"
    assert 62.0 <= hits[0]["peak_sec"] <= 66.0       # at the END of the run


def test_sustained_pressure_needs_twenty_seconds():
    motion = _fake_motion_full()
    t = motion["t"]
    motion["diff"][(t >= 40) & (t < 50)] = 0.20     # only 10 s
    cfg = NominationConfig(sustained_pressure=True)
    noms = build_nominations(motion, [], [], duration=120.0, config=cfg)
    assert not any("sustained_pressure" in n["reasons"] for n in noms)


def _reset_pattern(after: float, regroup: float = 0.004) -> dict:
    """Burst at 30-34 s, then `after` activity, then a `regroup` level."""
    motion = _fake_motion_full(base=0.02)
    t, d = motion["t"], motion["diff"]
    d[t < 10] = 0.004                                # opening settle
    d[(t >= 30) & (t < 34)] = 0.30                   # the play
    d[(t >= 34) & (t < 41)] = after                  # collapse or continuation
    d[(t >= 41) & (t < 60)] = regroup               # regroup (or more play)
    return motion


def test_post_goal_reset_fires():
    motion = _reset_pattern(after=0.0)               # dead stop after burst
    cfg = NominationConfig(post_goal_reset=True)
    noms = build_nominations(motion, [], [], duration=120.0, config=cfg)
    hits = [n for n in noms if "post_goal_reset" in n["reasons"]]
    assert hits, f"expected a post_goal_reset nomination, got {noms}"
    assert 29.0 <= hits[0]["peak_sec"] <= 35.0


def test_post_goal_reset_needs_the_collapse():
    # Play rolls straight on at a lively level -- no dead stop, no
    # quiet regroup within 40 s of the burst, so no reset signature.
    motion = _reset_pattern(after=0.05, regroup=0.05)
    cfg = NominationConfig(post_goal_reset=True)
    noms = build_nominations(motion, [], [], duration=120.0, config=cfg)
    assert not any("post_goal_reset" in n["reasons"] for n in noms)


def test_luminance_normalize_uses_ndiff():
    motion = _fake_motion_full(duration=124.0)
    t = motion["t"]
    motion["diff"][(t >= 60) & (t < 64)] = 0.25      # raw-diff "burst"
    # ndiff stays flat: the burst is a brightness artifact, not motion
    plain = build_nominations(motion, [], [], duration=124.0)
    assert any("settle_burst" in n["reasons"] for n in plain)
    cfg = NominationConfig(luminance_normalize=True)
    noms = build_nominations(motion, [], [], duration=124.0, config=cfg)
    assert noms == []


def test_rolling_thresholds_catch_local_burst():
    motion = _fake_motion_full(duration=600.0, base=0.01)
    t, d = motion["t"], motion["diff"]
    d[(t >= 100) & (t < 104)] = 0.06                 # modest burst, quiet half
    d[t >= 300] = 0.10                               # loud second half
    plain = build_nominations(motion, [], [], duration=600.0)
    assert not any("settle_burst" in n["reasons"] for n in plain)
    cfg = NominationConfig(rolling_thresholds=True, rolling_window_sec=240.0)
    noms = build_nominations(motion, [], [], duration=600.0, config=cfg)
    hits = [n for n in noms if "settle_burst" in n["reasons"]]
    assert hits, f"expected the local burst to nominate, got {noms}"
    assert 98.0 <= hits[0]["peak_sec"] <= 106.0
