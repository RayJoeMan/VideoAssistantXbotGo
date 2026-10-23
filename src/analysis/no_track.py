"""No-track nomination: find candidate play moments from video alone.

Most of the game library has no FALCON ``.track`` telemetry sidecar, so
the telemetry detector in :mod:`analysis.detection` cannot run on it.
This module is the fallback *nominator*: it reads only the video's own
audio and pixels and proposes candidate play moments (with reasons) for
a human to confirm in the review window.  Its job is recall -- don't
miss the moment -- not final labels.

Signals
-------
Audio (mono 16 kHz wav):
  * Referee whistles -- near-pure tones concentrated in the 2-4.5 kHz
    band, far above the broadband floor, sustained >= 0.15 s.  Draws,
    fouls and goals are all bracketed by whistles, so a whistle followed
    by live play is a strong nomination.
  * Crowd surges -- broadband RMS rising to > 2.5x the trailing 10 s
    median within ~2 s.  Goals and big saves produce these.

Motion (downscaled grayscale rendition, 4 fps, 320 px wide):
  * Frame-difference energy -- how much of the picture is moving.
  * Global horizontal pan -- the FALCON auto-tracks play, so its pan
    velocity traces where the action goes; a *settle* (camera still,
    picture quiet -- teams set for a draw / free position) followed by a
    *burst* is the classic shape of a play starting.

Nomination rules (all thresholds are per-game percentiles, so the
module self-calibrates to each recording's noise floor):
  R1 ``settle_burst``  -- activity burst whose onset is preceded within
     3 s by a >= 2 s camera settle.
  R2 ``whistle_play``  -- whistle burst followed by above-median
     activity within 5 s; peak at the first burst peak in the window.
  R3 ``crowd_surge``   -- crowd-surge onset; boosted when it lands
     within 5 s after a motion burst (``surge_after_burst``).
Nominations whose peaks fall within 8 s are merged (reasons unioned,
highest component score kept).

Everything here is pure numpy on arrays; file IO (ffmpeg extraction /
decode) lives in :func:`analyze_files` and the CLI in
``scripts/motion_nominate.py``.  Times are VIDEO seconds throughout.
"""

from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import numpy as np

# ── Audio constants ──────────────────────────────────────────────────
WHISTLE_BAND_HZ = (2000.0, 4500.0)
WHISTLE_MIN_BAND_FRACTION = 0.35
WHISTLE_MIN_BAND_RATIO = 6.0      # band energy vs its own median
WHISTLE_MIN_SEC = 0.15
WHISTLE_MERGE_GAP_SEC = 0.4       # chirped bursts count as one whistle
SURGE_RATIO = 2.5                 # vs trailing 10 s median
SURGE_TRAIL_SEC = 10.0

# ── Motion / nomination constants ────────────────────────────────────
MOTION_FPS = 4.0
SETTLE_MIN_SEC = 2.0
SETTLE_LOOKBACK_SEC = 3.0
MERGE_PEAK_GAP_SEC = 8.0
NOM_PRE_SEC = 6.0                 # nomination window before the peak
NOM_POST_SEC = 9.0                # ... and after it


# ══════════════════════════════════════════════════════════════════════
# Audio
# ══════════════════════════════════════════════════════════════════════

def load_wav(path: Path | str) -> Tuple[np.ndarray, int]:
    """Read a mono PCM wav into float32 samples in [-1, 1]."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:  # 8-bit PCM is unsigned
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, sr


def _stft_magnitude(samples: np.ndarray, sr: int,
                     frame: int = 1024, hop: int = 512) -> Tuple[np.ndarray, np.ndarray]:
    """Magnitude STFT (chunked so a full game fits in memory)."""
    window = np.hanning(frame).astype(np.float32)
    n_frames = 1 + max(0, (len(samples) - frame) // hop)
    mags = np.empty((n_frames, frame // 2 + 1), dtype=np.float32)
    chunk = 8192
    for start in range(0, n_frames, chunk):
        stop = min(n_frames, start + chunk)
        idx = start * hop + np.arange(frame)[None, :] + hop * np.arange(stop - start)[:, None]
        frames = samples[np.minimum(idx, len(samples) - 1)] * window
        mags[start:stop] = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(frame, d=1.0 / sr)
    return mags, freqs


def detect_whistles(samples: np.ndarray, sr: int,
                    frame: int = 1024, hop: int = 512) -> List[dict]:
    """Detect referee-whistle bursts in a mono waveform.

    A whistle frame has most of its spectral energy inside the
    2-4.5 kHz band *and* band energy far above the recording's median
    band energy (crowd noise is broadband, so it fails the fraction
    test; quiet passages fail the energy test).
    """
    mags, freqs = _stft_magnitude(samples, sr, frame, hop)
    power = mags ** 2
    band = (freqs >= WHISTLE_BAND_HZ[0]) & (freqs <= WHISTLE_BAND_HZ[1])
    band_e = power[:, band].sum(axis=1)
    total_e = power.sum(axis=1) + 1e-12
    frac = band_e / total_e
    med_band = np.median(band_e) + 1e-12
    mask = (frac > WHISTLE_MIN_BAND_FRACTION) & (band_e > WHISTLE_MIN_BAND_RATIO * med_band)

    hop_sec = hop / sr
    events: List[dict] = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        last_true = i
        # extend through short gaps (chirps)
        while j < n and (mask[j] or (j - last_true) * hop_sec <= WHISTLE_MERGE_GAP_SEC):
            if mask[j]:
                last_true = j
            j += 1
        dur = (last_true - i + 1) * hop_sec
        if dur >= WHISTLE_MIN_SEC:
            seg = slice(i, last_true + 1)
            events.append({
                "start_sec": round(i * hop_sec, 2),
                "end_sec": round((last_true + 1) * hop_sec, 2),
                "peak_sec": round((i + int(np.argmax(band_e[seg]))) * hop_sec, 2),
                "strength": round(float(frac[seg].max()), 3),
            })
        i = j
    return events


def broadband_envelope(samples: np.ndarray, sr: int,
                       win_sec: float = 0.25) -> Tuple[np.ndarray, np.ndarray]:
    """RMS envelope; returns (times, rms) at ``win_sec`` resolution."""
    win = int(sr * win_sec)
    n = len(samples) // win
    frames = samples[: n * win].reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    times = (np.arange(n) + 0.5) * win_sec
    return times, rms


def detect_surges(times: np.ndarray, rms: np.ndarray,
                  ratio: float = SURGE_RATIO,
                  trail_sec: float = SURGE_TRAIL_SEC,
                  win_sec: float = 0.25) -> List[dict]:
    """Crowd surges: envelope jumping to ``ratio`` x trailing median."""
    if len(rms) < int(trail_sec / win_sec) + 8:
        return []
    # smooth ~0.75 s to ride over single shouts
    k = max(1, int(0.75 / win_sec))
    smooth = np.convolve(rms, np.ones(k) / k, mode="same")
    trail_n = int(trail_sec / win_sec)
    events: List[dict] = []
    i = trail_n
    n = len(smooth)
    while i < n:
        base = np.median(smooth[max(0, i - trail_n):i]) + 1e-9
        if smooth[i] > 1.6 * base:
            # candidate rise: does it reach the full ratio within 2 s?
            horizon = min(n, i + int(2.0 / win_sec))
            peak_i = i + int(np.argmax(smooth[i:horizon]))
            if smooth[peak_i] > ratio * base:
                events.append({
                    "start_sec": round(float(times[i]), 2),
                    "peak_sec": round(float(times[peak_i]), 2),
                    "ratio": round(float(smooth[peak_i] / base), 2),
                })
                # one surge per swell: skip while the crowd stays loud
                j = peak_i
                cap = peak_i + int(6.0 / win_sec)
                while j < n and j < cap and smooth[j] > 1.3 * base:
                    j += 1
                i = j
                continue
        i += 1
    return events


# ══════════════════════════════════════════════════════════════════════
# Motion
# ══════════════════════════════════════════════════════════════════════

def pan_from_profiles(prev: np.ndarray, cur: np.ndarray,
                      max_lag: int = 80) -> float:
    """Signed horizontal shift (px) between two column profiles.

    Positive = scene moved right (camera panned left-to-right following
    play to the right is the negative of scene shift; we keep the raw
    scene shift and let callers use magnitude).
    """
    a = prev - prev.mean()
    b = cur - cur.mean()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    corr = np.correlate(b, a, mode="full")  # lag>0: b shifted right vs a
    lags = np.arange(-len(a) + 1, len(a))
    keep = np.abs(lags) <= max_lag
    idx = np.argmax(np.where(keep, corr, -np.inf))
    return float(lags[idx])


def motion_series(frames, fps: float = MOTION_FPS) -> dict:
    """Per-frame-pair motion timeline from grayscale frames.

    Returns dict of numpy arrays: ``t`` (sec, at the later frame),
    ``diff`` (mean abs pixel difference / 255), ``pan`` (signed
    horizontal scene shift, px/frame).
    """
    ts, diffs, pans = [], [], []
    prev = None
    prev_profile = None
    for i, frame in enumerate(frames):
        f = frame.astype(np.float32)
        if prev is not None:
            diffs.append(float(np.abs(f - prev).mean()) / 255.0)
            profile = f.mean(axis=0)
            pans.append(pan_from_profiles(prev_profile, profile))
            ts.append(i / fps)
            prev_profile = profile
        else:
            prev_profile = f.mean(axis=0)
        prev = f
    return {"t": np.array(ts), "diff": np.array(diffs), "pan": np.array(pans)}


def iter_lowres_frames(path: Path | str, fps: float = MOTION_FPS,
                       width: int = 320) -> Iterator[np.ndarray]:
    """Stream grayscale frames from a video file via ffmpeg rawvideo."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    w, h = (int(x) for x in probe.stdout.strip().split(",")[:2])
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={fps},scale={width}:-2,format=gray",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE)
    assert proc.stdout is not None
    hh = (h * width) // w // 2 * 2  # scale=-2 keeps even dims
    frame_bytes = width * hh
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        yield np.frombuffer(buf, dtype=np.uint8).reshape(hh, width).copy()
    proc.stdout.close()
    proc.wait()


# ══════════════════════════════════════════════════════════════════════
# Nomination
# ══════════════════════════════════════════════════════════════════════

def _moving_avg(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) == 0:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same")


def _segments_above(x: np.ndarray, thresh: float, min_gap: int) -> List[Tuple[int, int]]:
    """Index spans where x > thresh, merging spans < min_gap apart."""
    spans: List[Tuple[int, int]] = []
    i, n = 0, len(x)
    while i < n:
        if x[i] > thresh:
            j = i
            while j < n and x[j] > thresh:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


@dataclass
class Nomination:
    start_sec: float
    peak_sec: float
    end_sec: float
    reasons: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "start_sec": round(self.start_sec, 1),
            "peak_sec": round(self.peak_sec, 1),
            "end_sec": round(self.end_sec, 1),
            "reasons": list(self.reasons),
            "score": round(self.score, 3),
        }


def build_nominations(motion: dict, whistles: List[dict], surges: List[dict],
                      duration: float, fps: float = MOTION_FPS) -> List[dict]:
    """Combine audio + motion cues into merged nominations.

    Thresholds are percentiles of *this* game's signals, so nothing is
    tuned to any particular game's ground truth.
    """
    t = motion["t"]
    if len(t) < int(30 * fps):
        return []
    act = _moving_avg(motion["diff"], int(1.0 * fps))          # ~1 s smoothing
    pan_rate = _moving_avg(np.abs(motion["pan"]), int(1.0 * fps))

    act_q40, act_q50, act_q80 = np.percentile(act, [40, 50, 80])
    pan_q60 = np.percentile(pan_rate, 60)

    # settle: quiet picture AND still camera, sustained >= SETTLE_MIN_SEC
    settle_pt = (act <= act_q40) & (pan_rate < max(0.6, pan_q60))
    settle_spans = _segments_above(settle_pt.astype(float), 0.5,
                                   min_gap=int(0.5 * fps))
    settles = [(t[s], t[min(e, len(t) - 1)]) for s, e in settle_spans
               if (e - s) / fps >= SETTLE_MIN_SEC]

    # bursts: activity above the 80th percentile
    burst_spans = _segments_above(act, act_q80, min_gap=int(3.0 * fps))
    bursts = []
    for s, e in burst_spans:
        pk = s + int(np.argmax(act[s:e]))
        bursts.append({"onset": float(t[s]), "peak": float(t[pk]),
                       "peak_i": pk, "strength": float(act[pk] / (act_q80 + 1e-9))})

    noms: List[Nomination] = []

    def add(peak: float, reason: str, score: float, onset: Optional[float] = None):
        start = max(0.0, (onset if onset is not None else peak) - 2.0)
        noms.append(Nomination(
            start_sec=max(0.0, min(start, peak - NOM_PRE_SEC + 4.0)),
            peak_sec=float(peak),
            end_sec=min(duration, peak + NOM_POST_SEC),
            reasons=[reason], score=float(score)))

    # R1: settle -> burst (settle ends within the lookback before onset)
    for b in bursts:
        prior = [sp for sp in settles
                 if -1.0 <= b["onset"] - sp[1] <= SETTLE_LOOKBACK_SEC]
        if prior:
            add(b["peak"], "settle_burst",
                min(1.0, 0.55 + 0.2 * (b["strength"] - 1.0)), onset=b["onset"])

    # R2: whistle followed by live play
    for w in whistles:
        lo, hi = w["start_sec"] - 1.0, w["start_sec"] + 6.0
        near = [b for b in bursts if lo <= b["peak"] <= hi]
        win = (t >= w["start_sec"]) & (t <= w["start_sec"] + 5.0)
        if len(act[win]) and act[win].mean() > act_q50:
            if near:
                add(near[0]["peak"], "whistle_play", 0.75, onset=w["start_sec"])
            else:
                add(w["start_sec"] + 1.0, "whistle_play", 0.55, onset=w["start_sec"])

    # R3: crowd surge (boost when it follows a burst)
    for s in surges:
        prior_b = [b for b in bursts if 0.0 <= s["peak_sec"] - b["peak"] <= 5.0]
        if prior_b:
            add(prior_b[-1]["peak"], "crowd_surge", 0.9, onset=prior_b[-1]["onset"])
            noms[-1].reasons.append("surge_after_burst")
        else:
            near = [b for b in bursts if abs(b["peak"] - s["peak_sec"]) <= 3.0]
            add(near[0]["peak"] if near else s["peak_sec"], "crowd_surge", 0.7,
                onset=s["start_sec"])

    # merge peaks within MERGE_PEAK_GAP_SEC
    noms.sort(key=lambda n: n.peak_sec)
    merged: List[Nomination] = []
    for n in noms:
        if merged and n.peak_sec - merged[-1].peak_sec <= MERGE_PEAK_GAP_SEC:
            m = merged[-1]
            keep = n if n.score > m.score else m
            reasons = sorted(set(m.reasons) | set(n.reasons))
            merged[-1] = Nomination(
                start_sec=min(m.start_sec, n.start_sec),
                peak_sec=keep.peak_sec,
                end_sec=max(m.end_sec, n.end_sec),
                reasons=reasons,
                score=max(m.score, n.score) + 0.05 * (len(reasons) - 1))
        else:
            merged.append(n)
    for m in merged:
        m.start_sec = max(0.0, min(m.start_sec, m.peak_sec - 1.0))
        m.end_sec = min(duration, max(m.end_sec, m.peak_sec + 3.0))
    return [m.to_dict() for m in merged]


# ══════════════════════════════════════════════════════════════════════
# File-level orchestration
# ══════════════════════════════════════════════════════════════════════

def extract_derivatives(video: Path | str, workdir: Path | str) -> Tuple[Path, Path]:
    """ffmpeg: mono 16 kHz wav + 4 fps 320 px grayscale rendition."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    wav = workdir / "audio.wav"
    low = workdir / "low.mp4"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                        "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(wav)], check=True)
    if not low.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                        "-vf", f"fps={MOTION_FPS},scale=320:-2,format=gray",
                        "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "32", str(low)], check=True)
    return wav, low


def probe_duration(path: Path | str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def analyze_files(wav_path: Path | str, lowres_path: Path | str,
                  duration: Optional[float] = None) -> dict:
    """Run the full nominator on pre-extracted derivatives."""
    samples, sr = load_wav(wav_path)
    whistles = detect_whistles(samples, sr)
    etimes, erms = broadband_envelope(samples, sr)
    surges = detect_surges(etimes, erms)
    motion = motion_series(iter_lowres_frames(lowres_path))
    if duration is None:
        duration = probe_duration(lowres_path)
    noms = build_nominations(motion, whistles, surges, duration)
    return {
        "duration_sec": round(duration, 1),
        "whistles": whistles,
        "surges": surges,
        "nominations": noms,
    }
