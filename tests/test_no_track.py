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
    build_nominations,
    detect_surges,
    detect_whistles,
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
