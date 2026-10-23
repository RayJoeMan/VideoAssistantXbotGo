"""
Event Detection from Telemetry Data

Detects lacrosse play events from FALCON track data using
signal processing on activity, position, and velocity signals.

Event types detected:
  - Shot: ball velocity spike toward attacking goal
  - Save: rapid velocity drop + direction reversal near goal
  - Transition: center position crosses midfield at speed
  - Face-off: clustered positions at center X, activity from zero
  - Turnover: sustained direction change without shot follow-through
  - Goal: shot event followed by activity celebration spike

Architecture:
  ParsedTrack → compute derived signals → detect pattern → Event list

Calibration notes (2026-10-23, from a screenshot-triaged sample of 51
detections on a real game — see the calibration review pack):
  - The parser now feeds object (Deque) speeds, not camera pan speed;
    thresholds below assume that signal.
  - A local-activity floor removes detections from dead periods
    (stoppages, lulls, pre/post-game), which produced many false saves.
  - Saves are only trusted when linked to a shot, or when standalone
    evidence is strong (high activity + high incoming speed). The old
    hard position gate is gone: the FALCON position signal sits at
    midfield for many genuine goal-mouth plays, so it cannot gate.
  - Goals require a celebration-level activity follow-through in an
    attacking area, not merely the absence of a save.
  - One label per play: events whose peaks fall inside one spacing
    window collapse to the highest-priority type.

Usage:
    from src.telemetry.parser import parse_track_file
    from src.analysis.detection import detect_events

    track = parse_track_file("game.track")
    events = detect_events(track)
    for e in events:
        print(f"{e.event_type.value} at {e.peak_time_sec:.1f}s (conf={e.confidence:.2f})")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from telemetry.models import (
    TrackPoint, Event, EventType, PlayIntensity, ActivityWindow,
    GameMetadata, TrackSummary,
)
from telemetry.parser import ParsedTrack
from telemetry.logging_setup import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class DetectionConfig:
    """Tunable parameters for event detection algorithms."""
    # Shot detection (on the smoothed object-speed series; thresholds
    # recalibrated 2026-10-23 — the camera-era values admitted almost
    # no real shots once the parser fed object speeds)
    shot_min_speed: float = 28.0         # Minimum smoothed speed for a shot
    shot_speed_spike: float = 12.0       # Smoothed spike over baseline to trigger
    shot_min_activity: float = 0.4       # Minimum activity during shot
    shot_min_buildup: float = 0.15       # Mean activity in the ~1.5s before

    # Save detection (also on smoothed speed)
    save_min_speed: float = 30.0        # Minimum incoming smoothed speed
    save_speed_drop: float = 0.6         # Fraction speed must drop (60% reduction)
    save_drop_floor: float = 18.0        # ...and fall to at most this (a real stop)
    save_reversal_min_speed: float = 18.0 # Minimum speed after save for clear
    # A save is trusted when a shot/goal sits within this window of it.
    save_link_window_sec: float = 4.0
    # Unlinked saves need strong standalone evidence (calibration: most
    # unlinked low-activity "saves" were stoppages or midfield play).
    save_standalone_min_activity: float = 0.35
    save_standalone_min_speed: float = 45.0

    # Transition detection
    transition_midfield_zone: Tuple[float, float] = (400.0, 600.0)
    transition_min_speed: float = 40.0
    transition_min_duration_sec: float = 1.5
    transition_direction_change: float = 300.0  # Minimum position delta for direction change

    # Face-off detection (windowed: quiet → clustered at center → ramp)
    faceoff_center_zone: Tuple[float, float] = (420.0, 580.0)
    faceoff_max_objects: int = 4          # Minimum avg objects near center
    faceoff_activity_ramp: float = 0.15   # Pre-draw activity must be at/below this
    faceoff_post_activity_min: float = 0.30  # Activity in the 5s after the draw
    faceoff_min_spacing_sec: float = 30.0

    # General
    min_event_spacing_sec: float = 8.0    # Peaks closer than this are one play
    goal_confirmation_window_sec: float = 4.0  # A save this close vetoes a goal
    # Every detection needs live play around it: mean activity within
    # ±3s of the peak must reach this (dead periods measured ~0.0-0.15,
    # genuine events ~0.23+).
    min_local_activity: float = 0.20
    # Goal promotion: mean activity 5-15s after the shot (celebration /
    # reset energy) and the play must sit outside the center band.
    goal_min_follow_activity: float = 0.40
    goal_center_band: Tuple[float, float] = (400.0, 600.0)

    # Pre/post-game guards (calibration game 2, 2026-10-23): the only
    # pre-draw events in two full games were warmup "turnovers", and
    # the post-game handshake line produced a conf-0.81 "shot" in both
    # games (players jog to the line = a genuine-looking speed spike,
    # but with a cold buildup inside a long low-activity tail).
    pregame_faceoff_deadline_sec: float = 180.0  # Guard applies only if a draw is found this early
    postgame_bin_sec: float = 5.0          # Tail measured in bins of this size
    postgame_bin_activity: float = 0.40    # Every tail bin's mean activity stays below this
    postgame_min_tail_sec: float = 30.0    # Tail must be at least this long
    postgame_buildup_max_speed: float = 55.0  # Spike needs a cold [peak-20, peak-6] window


# ══════════════════════════════════════════════════════════════════════════
# Derived Signal Computation
# ══════════════════════════════════════════════════════════════════════════

def _compute_derived_signals(points: List[TrackPoint]) -> dict:
    """Compute derived time-series signals from raw track points.
    
    Returns dict of numpy arrays keyed by signal name:
        time, activity, center_x, center_speed, crowd_x, objects,
        speed_accel (acceleration), dir_sign (direction: +1 right, -1 left)
    """
    n = len(points)
    if n < 2:
        return {}
    
    time = np.array([p.timestamp_sec for p in points])
    activity = np.array([p.activity_score for p in points])
    center_x = np.array([p.center_x for p in points])
    center_speed = np.array([p.center_speed for p in points])
    crowd_x = np.array([p.crowd_x for p in points])
    objects = np.array([p.objects_detected for p in points], dtype=float)
    
    # Smoothed speed (~0.4s moving average). Object speeds are jittery
    # frame to frame; spike/drop tests run on this series so single-
    # frame noise can't manufacture or erase an event.
    smooth_window = min(7, n)
    if smooth_window > 1:
        center_speed_smooth = np.convolve(
            center_speed, np.ones(smooth_window) / smooth_window, mode='same'
        )
    else:
        center_speed_smooth = center_speed.copy()

    # Acceleration (derivative of the SMOOTHED speed — raw object speed
    # changes sign constantly and makes this test meaningless)
    dt = np.diff(time)
    dt = np.where(dt == 0, 1e-6, dt)  # Avoid division by zero
    speed_accel = np.zeros(n)
    speed_accel[1:] = np.diff(center_speed_smooth) / dt
    
    # Direction sign: +1 = moving right (attacking), -1 = moving left
    # Based on center_x derivative
    dir_sign = np.ones(n)
    if n > 5:
        # Smooth position with moving average before computing direction
        window = min(5, n - 1)
        smooth_pos = np.convolve(center_x, np.ones(window)/window, mode='same')
        pos_delta = np.diff(smooth_pos)
        dir_sign[1:] = np.sign(np.where(np.abs(pos_delta) < 5, 0, pos_delta))
    
    return {
        "time": time,
        "activity": activity,
        "center_x": center_x,
        "center_speed": center_speed,
        "center_speed_smooth": center_speed_smooth,
        "crowd_x": crowd_x,
        "objects": objects,
        "speed_accel": speed_accel,
        "dir_sign": dir_sign,
    }


# ══════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════

def detect_events(
    track: ParsedTrack,
    config: Optional[DetectionConfig] = None,
) -> List[Event]:
    """Detect all play events from parsed track data.
    
    Args:
        track: Parsed FALCON track data
        config: Optional detection parameter overrides
    
    Returns:
        List of Event objects sorted by time, with confidence and priority
    """
    cfg = config or DetectionConfig()
    points = track.points
    
    if len(points) < 10:
        log.warning("track too short for event detection: %d frames", len(points))
        return []
    
    signals = _compute_derived_signals(points)
    if not signals:
        return []
    
    events: List[Event] = []
    
    # Detect each event type
    events.extend(_detect_shots(signals, points, cfg))
    events.extend(_detect_saves(signals, points, cfg))
    events.extend(_detect_transitions(signals, points, cfg))
    events.extend(_detect_faceoffs(signals, points, cfg))
    events.extend(_detect_turnovers(signals, points, cfg))
    
    # Post-processing (order matters: the floor first, while raw
    # candidates are cheap to drop; goal promotion before save
    # filtering, because a nearby save vetoes the goal; clustering
    # last so each play keeps exactly one label)
    events = _apply_activity_floor(events, signals, cfg)
    events = _resolve_goals(events, signals, cfg)
    events = _filter_saves(events, signals, cfg)
    events = _deduplicate_events(events, cfg)
    events = _suppress_pregame(events, cfg)
    events = _suppress_postgame_tail(events, signals, cfg)
    events = _classify_intensity(events, signals)
    events = _sort_by_time(events)
    
    log.info(
        f"detected {len(events)} events",
        extra={
            "shots": sum(1 for e in events if e.event_type == EventType.SHOT),
            "goals": sum(1 for e in events if e.event_type == EventType.GOAL),
            "saves": sum(1 for e in events if e.event_type == EventType.SAVE),
            "transitions": sum(1 for e in events if e.event_type == EventType.TRANSITION),
            "faceoffs": sum(1 for e in events if e.event_type == EventType.FACE_OFF),
            "turnovers": sum(1 for e in events if e.event_type == EventType.TURNOVER),
        },
    )
    
    return events


# ══════════════════════════════════════════════════════════════════════════
# Individual Detectors
# ══════════════════════════════════════════════════════════════════════════

def _detect_shots(
    signals: dict,
    points: List[TrackPoint],
    cfg: DetectionConfig,
) -> List[Event]:
    """Detect shot attempts from velocity + position signals.
    
    A shot is characterized by:
    1. Sudden increase in center speed (ball/stick velocity)
    2. Position in attacking zone (center_x biased toward goal)
    3. High activity level
    4. Preceded by offensive buildup
    """
    events: List[Event] = []
    n = len(points)

    speed = signals["center_speed_smooth"]
    accel = signals["speed_accel"]
    activity = signals["activity"]
    pos = signals["center_x"]
    time = signals["time"]

    # Compute rolling baseline speed (30-frame window ≈ 1 second)
    window = min(30, n // 3)
    if window < 3:
        return events

    baseline = np.convolve(speed, np.ones(window)/window, mode='same')

    for i in range(window, n - window):
        # Speed spike above baseline
        speed_spike = speed[i] - baseline[i]

        if speed_spike < cfg.shot_speed_spike:
            continue
        if speed[i] < cfg.shot_min_speed:
            continue
        # Activity near the peak (object speed is jittery frame to
        # frame, so judge the neighbourhood, not the single frame)
        local_activity = float(np.max(activity[max(0, i - 5):i + 6]))
        if local_activity < cfg.shot_min_activity:
            continue

        # Acceleration should be positive (ball accelerating)
        if accel[i] < 0:
            continue

        # Look for buildup: sustained moderate activity before the shot
        buildup_start = max(0, i - 30)  # ~1 second before
        buildup_activity = np.mean(activity[buildup_start:i])
        if buildup_activity < cfg.shot_min_buildup:
            continue
        
        # Compute confidence
        confidence = _shot_confidence(
            speed_spike, speed[i], local_activity, buildup_activity, cfg
        )

        # Position depth: the same speed spike at a goal line is far
        # more likely a real shot than at midfield (calibration: several
        # false "shots" were fast midfield transition plays).
        depth = abs(pos[i] - 500.0) / 500.0
        confidence = min(confidence * (0.8 + 0.4 * depth), 1.0)
        
        # Frame range: 1 second before to 2 seconds after
        start_idx = max(0, i - 30)
        end_idx = min(n - 1, i + 60)
        
        events.append(Event(
            event_type=EventType.SHOT,
            start_time_sec=float(time[start_idx]),
            end_time_sec=float(time[end_idx]),
            peak_time_sec=float(time[i]),
            confidence=confidence,
            frame_range=(points[start_idx].frame_num, points[end_idx].frame_num),
            description=f"Shot attempt at {time[i]:.1f}s, speed={speed[i]:.0f}",
            tags=["offense"] if pos[i] > 500 else ["defense"],
        ))
    
    return events


def _detect_saves(
    signals: dict,
    points: List[TrackPoint],
    cfg: DetectionConfig,
) -> List[Event]:
    """Detect saves from rapid velocity drops near goal line.
    
    A save is characterized by:
    1. High incoming speed (ball toward goal)
    2. Rapid deceleration to near-zero
    3. Position near goal line extreme
    4. Followed by direction reversal (clear)
    """
    events: List[Event] = []
    n = len(points)

    # Smoothed speed: raw object speed oscillates constantly, and on the
    # raw series a 60% "drop" happens somewhere in almost every second
    # of play (the un-gated detector produced 1,200+ candidates a game).
    speed = signals["center_speed_smooth"]
    accel = signals["speed_accel"]
    pos = signals["center_x"]
    time = signals["time"]

    last_peak = -1e9
    for i in range(5, n - 5):
        # One candidate per play, not per frame
        if time[i] - last_peak < 2.5:
            continue

        # Need high incoming speed (fast play, not gentle ebb)
        if speed[i] < cfg.save_min_speed:
            continue

        # Look ahead for speed drop
        lookahead = min(i + 20, n - 1)
        future_speed = speed[i + 1:lookahead]

        if len(future_speed) < 3:
            continue

        min_future = np.min(future_speed)

        # Speed must drop significantly — in relative terms AND down to
        # a genuine stop (a shot arriving then being stopped, not a
        # carrier merely slowing from very fast to fast)
        if min_future > speed[i] * (1 - cfg.save_speed_drop):
            continue
        if min_future > cfg.save_drop_floor:
            continue
        
        # NOTE: no hard position gate. Calibration showed the FALCON
        # position signal sits at midfield for many genuine goal-mouth
        # saves (the tracking window is wide), so gating on it removed
        # true saves while camera-era false ones sailed through. Save
        # validation now happens in _filter_saves (shot linkage or
        # strong standalone evidence); position only nudges confidence.
        
        # Look for reversal after the stop
        min_idx = i + 1 + np.argmin(future_speed)
        if min_idx < n - 10:
            post_save_speed = np.max(speed[min_idx:min(min_idx + 30, n)])
            if post_save_speed < cfg.save_reversal_min_speed:
                continue  # No clear — might be a goal instead
        
        confidence = 0.6 + 0.2 * (speed[i] / 100.0) + 0.2 * (1 - min_future / max(speed[i], 1e-6))

        # Soft position evidence: play centered in a goal third is a
        # little more believable than the same drop at midfield.
        win_pos = pos[max(0, i - 15):min(n, i + 15)]
        if len(win_pos) and (np.median(win_pos) <= 350.0 or np.median(win_pos) >= 650.0):
            confidence += 0.05
        confidence = min(confidence, 1.0)
        
        last_peak = float(time[i])
        events.append(Event(
            event_type=EventType.SAVE,
            start_time_sec=float(time[max(0, i - 15)]),
            end_time_sec=float(time[min(n - 1, i + 45)]),
            peak_time_sec=float(time[i]),
            confidence=min(confidence, 1.0),
            frame_range=(points[max(0, i - 15)].frame_num, points[min(n - 1, i + 45)].frame_num),
            description=f"Save at {time[i]:.1f}s, speed {speed[i]:.0f}→{min_future:.0f}",
        ))
    
    return events


def _detect_transitions(
    signals: dict,
    points: List[TrackPoint],
    cfg: DetectionConfig,
) -> List[Event]:
    """Detect transitions (fast breaks) from midline crossings at speed.
    
    A transition is characterized by:
    1. Center position crosses midfield
    2. Sustained high speed
    3. Direction is consistent
    4. Crowd position shifts with play
    """
    events: List[Event] = []
    n = len(points)
    
    speed = signals["center_speed"]
    pos = signals["center_x"]
    time = signals["time"]
    dir_sign = signals["dir_sign"]
    
    mid_low, mid_high = cfg.transition_midfield_zone
    in_transition = False
    trans_start = 0
    entry_side = 0  # -1 entered from the left edge, +1 from the right edge
    
    for i in range(1, n):
        in_midfield = mid_low <= pos[i] <= mid_high
        fast_enough = speed[i] >= cfg.transition_min_speed
        
        if not in_transition:
            # Enter the midfield zone at speed from a clear side
            if in_midfield and fast_enough and i > 1:
                if pos[i - 2] < mid_low:
                    entry_side = -1
                    in_transition = True
                    trans_start = i
                elif pos[i - 2] > mid_high:
                    entry_side = 1
                    in_transition = True
                    trans_start = i
        else:
            # A real fast break exits the zone on the OPPOSITE side
            exited_opposite = (
                (entry_side == -1 and pos[i] > mid_high) or
                (entry_side == 1 and pos[i] < mid_low)
            )
            if exited_opposite:
                duration = time[i] - time[trans_start]
                if duration >= cfg.transition_min_duration_sec:
                    avg_speed = float(np.mean(speed[trans_start:i]))
                    direction = "right" if entry_side == -1 else "left"
                    events.append(Event(
                        event_type=EventType.TRANSITION,
                        start_time_sec=float(time[max(0, trans_start - 15)]),
                        end_time_sec=float(time[min(n - 1, i + 15)]),
                        peak_time_sec=float(
                            time[trans_start + int(np.argmax(speed[trans_start:i]))]
                        ),
                        confidence=min(0.5 + 0.5 * (avg_speed / 100.0), 0.95),
                        frame_range=(
                            points[max(0, trans_start - 15)].frame_num,
                            points[min(n - 1, i + 15)].frame_num,
                        ),
                        description=(
                            f"Transition {direction} at {time[trans_start]:.1f}s, "
                            f"{duration:.1f}s"
                        ),
                        tags=["fast_break", direction],
                    ))
                in_transition = False
            elif speed[i] < cfg.transition_min_speed * 0.4:
                in_transition = False  # stalled — not a fast break
    
    return events


def _detect_faceoffs(
    signals: dict,
    points: List[TrackPoint],
    cfg: DetectionConfig,
) -> List[Event]:
    """Detect face-offs: quiet play clustered at center, then a ramp.

    A draw is a windowed pattern, not a frame pattern:
    1. Activity is low for several seconds (teams lining up)
    2. The action center sits at midfield with players clustered
    3. Activity ramps sharply as the draw is contested

    The previous per-frame version required near-total stillness in a
    10-frame pre-window, which essentially never occurs in real FALCON
    data — it fired zero times in a full calibrated game. This version
    scans 5-second windows and was validated against the known draw
    times (game start, second-half start) of that game.
    """
    events: List[Event] = []
    time = signals["time"]
    activity = signals["activity"]
    pos = signals["center_x"]
    objects = signals["objects"]
    if len(time) < 40 or time[-1] - time[0] < 20.0:
        return events

    center_low, center_high = cfg.faceoff_center_zone

    def _win(t0: float, t1: float) -> slice:
        lo = int(np.searchsorted(time, t0))
        hi = int(np.searchsorted(time, t1))
        return slice(lo, max(hi, lo))

    t = float(time[0]) + 10.0
    last_kept = -1e9
    while t < float(time[-1]) - 10.0:
        pre = _win(t - 7.5, t - 2.5)
        mid = _win(t - 2.5, t + 2.5)
        post = _win(t + 2.5, t + 7.5)
        if mid.stop - mid.start >= 5 and pre.stop - pre.start >= 5 \
                and post.stop - post.start >= 5:
            pre_act = float(np.mean(activity[pre]))
            post_act = float(np.mean(activity[post]))
            mid_pos = float(np.median(pos[mid]))
            mid_obj = float(np.mean(objects[mid]))
            if (
                pre_act <= cfg.faceoff_activity_ramp
                and post_act >= cfg.faceoff_post_activity_min
                and post_act >= 2.5 * max(pre_act, 0.01)
                and center_low <= mid_pos <= center_high
                and mid_obj >= cfg.faceoff_max_objects
                and t - last_kept >= cfg.faceoff_min_spacing_sec
            ):
                i = int(np.searchsorted(time, t))
                i = min(max(i, 0), len(points) - 1)
                j = min(int(np.searchsorted(time, t + 10.0)), len(points) - 1)
                events.append(Event(
                    event_type=EventType.FACE_OFF,
                    start_time_sec=float(max(time[0], t - 5.0)),
                    end_time_sec=float(time[j]),
                    peak_time_sec=float(t),
                    confidence=min(0.55 + 0.45 * (post_act / 0.7), 0.95),
                    frame_range=(points[max(0, i - 15)].frame_num, points[j].frame_num),
                    description=f"Face-off at {t:.1f}s, play restarts from center",
                ))
                last_kept = t
        t += 2.5

    return events


def _detect_turnovers(
    signals: dict,
    points: List[TrackPoint],
    cfg: DetectionConfig,
) -> List[Event]:
    """Detect turnovers from sustained direction changes.
    
    A turnover is characterized by:
    1. Sustained movement in one direction
    2. Abrupt direction reversal
    3. Speed maintained through the change
    4. Not near a shot or save (those are separate events)
    """
    events: List[Event] = []
    n = len(points)
    
    pos = signals["center_x"]
    speed = signals["center_speed"]
    time = signals["time"]
    
    window = 15  # ~0.5 second window
    
    # Smooth position first so camera/object jitter doesn't read as a
    # direction change.
    sw = min(5, max(3, n // 20))
    if n >= sw * 2:
        smooth_pos = np.convolve(pos, np.ones(sw) / sw, mode="same")
    else:
        smooth_pos = pos
    
    for i in range(window * 2, n - window):
        # Direction before
        pre_delta = smooth_pos[i] - smooth_pos[i - window]
        # Direction after
        post_delta = smooth_pos[i + window] - smooth_pos[i]
        
        # Must be a clear, sustained direction change (not jitter)
        if abs(pre_delta) < cfg.transition_direction_change:
            continue
        if abs(post_delta) < cfg.transition_direction_change:
            continue
        
        # Directions must be opposite
        if np.sign(pre_delta) == np.sign(post_delta):
            continue
        
        # Speed should be maintained (not a stoppage)
        avg_speed = float(np.mean(speed[i - 5:i + 5]))
        if avg_speed < 25.0:
            continue
        
        events.append(Event(
            event_type=EventType.TURNOVER,
            start_time_sec=float(time[max(0, i - 15)]),
            end_time_sec=float(time[min(n - 1, i + 15)]),
            peak_time_sec=float(time[i]),
            confidence=min(0.5 + 0.3 * (avg_speed / 80.0), 0.85),
            frame_range=(points[max(0, i - 15)].frame_num, points[min(n - 1, i + 15)].frame_num),
            description=f"Turnover at {time[i]:.1f}s, direction change",
        ))
    
    return events


# ══════════════════════════════════════════════════════════════════════════
# Post-processing
# ══════════════════════════════════════════════════════════════════════════

def _window_mean(signals: dict, key: str, t0: float, t1: float) -> float:
    """Mean of a signal over [t0, t1]; 0.0 when the window is empty."""
    time = signals["time"]
    lo = int(np.searchsorted(time, t0))
    hi = int(np.searchsorted(time, t1))
    if hi <= lo:
        return 0.0
    return float(np.mean(signals[key][lo:hi]))


def _window_max(signals: dict, key: str, t0: float, t1: float) -> float:
    """Max of a signal over [t0, t1]; 0.0 when the window is empty."""
    time = signals["time"]
    lo = int(np.searchsorted(time, t0))
    hi = int(np.searchsorted(time, t1))
    if hi <= lo:
        return 0.0
    return float(np.max(signals[key][lo:hi]))


def _window_median(signals: dict, key: str, t0: float, t1: float) -> float:
    """Median of a signal over [t0, t1]; 500.0 (midfield) when empty."""
    time = signals["time"]
    lo = int(np.searchsorted(time, t0))
    hi = int(np.searchsorted(time, t1))
    if hi <= lo:
        return 500.0
    return float(np.median(signals[key][lo:hi]))


def _apply_activity_floor(
    events: List[Event],
    signals: dict,
    cfg: DetectionConfig,
) -> List[Event]:
    """Drop detections from dead periods.

    Mean activity within ±3s of the peak must reach the floor. In the
    calibration sample every contradicted save/goal/turnover from a
    stoppage, lull, or pre/post-game sat below it, and every genuine
    event sat above it.
    """
    kept = []
    for e in events:
        # Face-offs are exempt: a draw is DEFINED by the quiet around
        # it, so its ±3s mean is low by construction. The face-off
        # detector already requires a strong post-draw ramp.
        if e.event_type == EventType.FACE_OFF:
            kept.append(e)
            continue
        local = _window_mean(
            signals, "activity", e.peak_time_sec - 3.0, e.peak_time_sec + 3.0
        )
        if local >= cfg.min_local_activity:
            kept.append(e)
    return kept


def _resolve_goals(
    events: List[Event],
    signals: dict,
    cfg: DetectionConfig,
) -> List[Event]:
    """Promote a shot to a goal on positive evidence, not absence.

    The old rule promoted any shot with no save/turnover nearby, which
    manufactured goals out of ordinary shots (and out of midfield
    activity misread as a shot). Promotion now requires:
    1. No save within the confirmation window (a save vetoes the goal)
    2. Celebration-level follow-through: mean activity 5-15s after the
       shot stays at or above the goal threshold
    3. The play sits outside the center band (an attacking area)
    """
    saves = [e for e in events if e.event_type == EventType.SAVE]
    band_low, band_high = cfg.goal_center_band

    for shot in [e for e in events if e.event_type == EventType.SHOT]:
        if any(
            abs(s.peak_time_sec - shot.peak_time_sec)
            < cfg.goal_confirmation_window_sec
            for s in saves
        ):
            continue
        # Celebration energy is a spike, not a plateau: take the best
        # 5-second mean in the 3-15s after the shot.
        follow = max(
            _window_mean(
                signals, "activity",
                shot.peak_time_sec + off, shot.peak_time_sec + off + 5.0,
            )
            for off in (3.0, 5.0, 7.5, 10.0)
        )
        if follow < cfg.goal_min_follow_activity:
            continue
        pos_med = _window_median(
            signals, "center_x",
            shot.peak_time_sec - 3.0, shot.peak_time_sec + 3.0,
        )
        if band_low <= pos_med <= band_high:
            continue
        shot.event_type = EventType.GOAL
        shot.confidence = min(shot.confidence * 1.1 + 0.05, 0.95)
        shot.description = shot.description.replace("Shot attempt", "Goal")
        if "scoring_play" not in shot.tags:
            shot.tags.append("scoring_play")

    return events


def _filter_saves(
    events: List[Event],
    signals: dict,
    cfg: DetectionConfig,
) -> List[Event]:
    """Keep saves that are linked to a shot, or strongly evidenced.

    A save is a response to a shot. Calibration showed unlinked "saves"
    were overwhelmingly stoppages and midfield slowdowns, while genuine
    saves either sat within seconds of a shot or came with high local
    activity and a fast incoming ball.
    """
    shots = [
        e for e in events
        if e.event_type in (EventType.SHOT, EventType.GOAL)
    ]
    time = signals["time"]
    speed = signals["center_speed_smooth"]

    kept: List[Event] = []
    for e in events:
        if e.event_type != EventType.SAVE:
            kept.append(e)
            continue
        linked = any(
            abs(s.peak_time_sec - e.peak_time_sec) <= cfg.save_link_window_sec
            for s in shots
        )
        if linked:
            e.confidence = min(e.confidence + 0.05, 1.0)
            if "shot_linked" not in e.tags:
                e.tags.append("shot_linked")
            kept.append(e)
            continue
        local_act = _window_mean(
            signals, "activity", e.peak_time_sec - 3.0, e.peak_time_sec + 3.0
        )
        lo = int(np.searchsorted(time, e.peak_time_sec - 3.0))
        hi = int(np.searchsorted(time, e.peak_time_sec))
        incoming = float(np.max(speed[lo:hi])) if hi > lo else 0.0
        if (
            local_act >= cfg.save_standalone_min_activity
            and incoming >= cfg.save_standalone_min_speed
        ):
            if "standalone" not in e.tags:
                e.tags.append("standalone")
            kept.append(e)
    return kept


# One label per play: when several detectors fire inside one spacing
# window, the highest-priority type wins (confidence breaks ties within
# a type). Calibration found single plays labeled shot+save+turnover at
# the same second.
_TYPE_PRIORITY = {
    EventType.GOAL: 0,
    EventType.SAVE: 1,
    EventType.SHOT: 2,
    EventType.TRANSITION: 3,
    EventType.FACE_OFF: 4,
    EventType.TURNOVER: 5,
}


def _suppress_pregame(
    events: List[Event],
    cfg: DetectionConfig,
) -> List[Event]:
    """Drop non-face-off events that peak before the game's first draw.

    Play cannot precede the opening draw, so anything earlier is
    warmup/lineup motion. In two calibrated games the ONLY pre-draw
    events were junk "turnovers" ~19-22s in. The guard stays off
    unless a draw is actually detected early (deadline in config):
    if the draw detector missed the opening, we change nothing.
    """
    faceoffs = [e for e in events if e.event_type == EventType.FACE_OFF]
    if not faceoffs:
        return events
    first_draw = min(e.peak_time_sec for e in faceoffs)
    if first_draw > cfg.pregame_faceoff_deadline_sec:
        return events
    return [
        e for e in events
        if e.event_type == EventType.FACE_OFF
        or e.peak_time_sec >= first_draw - 2.0
    ]


def _suppress_postgame_tail(
    events: List[Event],
    signals: dict,
    cfg: DetectionConfig,
) -> List[Event]:
    """Drop isolated spikes inside a long, quiet post-game tail.

    The handshake line beat the shot detector in both calibrated
    games: players jog to midfield (a real speed spike) and line up.
    What betrays it is the surroundings — the spike sits in a suffix
    of the recording where every 5s bin's mean activity stays low
    (the game is over), and its own buildup window is cold. A hot
    finish is safe twice over: its bins are too active to form the
    tail at all, and a real last-second shot has hot buildup.

    The tail must also be preceded by at least one active bin (there
    was a game before it) and span at least postgame_min_tail_sec.
    Face-offs are exempt: a late draw is harmless metadata.
    """
    time = signals["time"]
    activity = signals["activity"]
    if len(time) < 2:
        return events
    t_end = float(time[-1])
    bin_sec = cfg.postgame_bin_sec

    # Walk bins backward from the end while they stay quiet.
    tail_start = t_end
    saw_active_bin = False
    cursor = t_end
    while cursor > float(time[0]) + bin_sec:
        lo = cursor - bin_sec
        mean_act = _window_mean(signals, "activity", lo, cursor)
        if mean_act >= cfg.postgame_bin_activity:
            saw_active_bin = True
            break
        tail_start = lo
        cursor = lo
    if not saw_active_bin:
        return events
    if t_end - tail_start < cfg.postgame_min_tail_sec:
        return events

    kept = []
    for e in events:
        if e.event_type == EventType.FACE_OFF or e.peak_time_sec < tail_start:
            kept.append(e)
            continue
        buildup = _window_max(
            signals, "center_speed_smooth",
            e.peak_time_sec - 20.0, e.peak_time_sec - 6.0,
        )
        if buildup >= cfg.postgame_buildup_max_speed:
            kept.append(e)  # Hot buildup: live play, not a lineup jog.
    return kept


def _deduplicate_events(events: List[Event], cfg: DetectionConfig) -> List[Event]:
    """Collapse events whose peaks fall inside one spacing window."""
    if not events:
        return events

    def rank(e: Event):
        return (_TYPE_PRIORITY.get(e.event_type, 99), -e.confidence)

    kept: List[Event] = []
    for e in sorted(events, key=lambda x: x.peak_time_sec):
        # Face-offs only compete with face-offs: a draw is a distinct
        # beat of play, and the breakaway it triggers must not erase it
        # (nor the draw erase a genuine quick shot that follows).
        neighbours = [
            k for k in kept
            if abs(k.peak_time_sec - e.peak_time_sec) < cfg.min_event_spacing_sec
            and (k.event_type == EventType.FACE_OFF)
            == (e.event_type == EventType.FACE_OFF)
        ]
        if not neighbours:
            kept.append(e)
            continue
        group = neighbours + [e]
        winner = min(group, key=rank)
        kept = [k for k in kept if k not in neighbours]
        kept.append(winner)

    return kept


def _classify_intensity(events: List[Event], signals: dict) -> List[Event]:
    """Assign intensity levels based on surrounding activity."""
    if not signals or not events:
        return events
    
    activity = signals["activity"]
    time = signals["time"]
    
    for event in events:
        # Find activity around event peak
        peak_t = event.peak_time_sec
        indices = np.where((time >= peak_t - 2.0) & (time <= peak_t + 2.0))[0]
        
        if len(indices) > 0:
            avg_activity = float(np.mean(activity[indices]))
            
            if avg_activity > 0.7:
                event.intensity = PlayIntensity.HIGH
            elif avg_activity > 0.4:
                event.intensity = PlayIntensity.MEDIUM
            else:
                event.intensity = PlayIntensity.LOW
    
    return events


def _sort_by_time(events: List[Event]) -> List[Event]:
    """Sort events by peak time, then by priority (goals first)."""
    type_order = {
        EventType.GOAL: 0,
        EventType.SHOT: 1,
        EventType.SAVE: 2,
        EventType.TRANSITION: 3,
        EventType.TURNOVER: 4,
        EventType.FACE_OFF: 5,
    }
    return sorted(events, key=lambda e: (e.peak_time_sec, type_order.get(e.event_type, 99)))


# ══════════════════════════════════════════════════════════════════════════
# Confidence Scoring Helpers
# ══════════════════════════════════════════════════════════════════════════

def _shot_confidence(
    speed_spike: float,
    speed: float,
    activity: float,
    buildup_activity: float,
    cfg: DetectionConfig,
) -> float:
    """Compute shot confidence from signal features (0.0–1.0)."""
    score = 0.0
    
    # Speed spike magnitude (0–0.4)
    score += 0.4 * min(speed_spike / (cfg.shot_speed_spike * 3), 1.0)
    
    # Absolute speed (0–0.3)
    score += 0.3 * min(speed / (cfg.shot_min_speed * 2), 1.0)
    
    # Activity level (0–0.2)
    score += 0.2 * min((activity - cfg.shot_min_activity) / 0.3, 1.0)
    
    # Buildup quality (0–0.1)
    score += 0.1 * min(buildup_activity / 0.6, 1.0)
    
    return min(score, 1.0)


# ══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point: detect events from a .track file."""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(
        description="Detect events from a FALCON .track file",
    )
    parser.add_argument("track_file", help="Path to .track file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--json", action="store_true", help="Output events as JSON")
    parser.add_argument("--min-confidence", type=float, default=0.3,
                        help="Minimum confidence threshold (default: 0.3)")
    args = parser.parse_args()
    
    from telemetry.logging_setup import configure_logging
    configure_logging(level="DEBUG" if args.debug else "INFO")
    
    from telemetry.parser import parse_track_file
    track = parse_track_file(args.track_file)
    events = detect_events(track)
    
    # Filter by confidence
    events = [e for e in events if e.confidence >= args.min_confidence]
    
    if args.json:
        output = [
            {
                "type": e.event_type.value,
                "time": round(e.peak_time_sec, 1),
                "duration": round(e.duration_sec, 1),
                "confidence": round(e.confidence, 2),
                "intensity": e.intensity.value,
                "description": e.description,
                "tags": e.tags,
                "priority": round(e.priority_score, 2),
            }
            for e in events
        ]
        print(json.dumps(output, indent=2))
    else:
        print(f"\nDetected {len(events)} events:\n")
        for e in events:
            icon = {
                EventType.GOAL: "🥍", EventType.SHOT: "🎯",
                EventType.SAVE: "🧤", EventType.TRANSITION: "🏃",
                EventType.FACE_OFF: "⚡", EventType.TURNOVER: "↩️",
            }.get(e.event_type, "•")
            print(
                f"  {icon} {e.event_type.value:12s} "
                f"@{e.peak_time_sec:6.1f}s  "
                f"conf={e.confidence:.2f}  "
                f"{e.intensity.value:6s}  "
                f"{e.description}"
            )
