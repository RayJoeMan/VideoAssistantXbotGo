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
    # Shot detection
    shot_min_speed: float = 40.0         # Minimum center speed for a shot
    shot_speed_spike: float = 25.0       # Speed increase over baseline to trigger
    shot_min_activity: float = 0.4       # Minimum activity during shot
    shot_lookahead_sec: float = 3.0      # Window after shot for goal confirmation
    shot_goal_activity_spike: float = 0.7 # Activity threshold for goal celebration
    
    # Save detection
    save_min_speed: float = 25.0        # Minimum incoming speed (0-100) for a save
    save_speed_drop: float = 0.6         # Fraction speed must drop (60% reduction)
    save_position_threshold: float = 0.15 # Position near goal line (0-1 normalized)
    save_reversal_min_speed: float = 20.0 # Minimum speed after save for clear
    
    # Transition detection
    transition_midfield_zone: Tuple[float, float] = (400.0, 600.0)
    transition_min_speed: float = 40.0
    transition_min_duration_sec: float = 1.5
    transition_direction_change: float = 300.0  # Minimum position delta for direction change
    
    # Face-off detection
    faceoff_center_zone: Tuple[float, float] = (450.0, 550.0)
    faceoff_max_objects: int = 6          # Minimum objects near center
    faceoff_activity_ramp: float = 0.3    # Activity must rise from below this
    
    # General
    min_event_spacing_sec: float = 8.0    # Minimum time between distinct events
    goal_confirmation_window_sec: float = 8.0  # Window to confirm goal after shot


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
    
    # Acceleration (derivative of speed)
    dt = np.diff(time)
    dt = np.where(dt == 0, 1e-6, dt)  # Avoid division by zero
    speed_accel = np.zeros(n)
    speed_accel[1:] = np.diff(center_speed) / dt
    
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
    
    # Post-processing
    events = _resolve_goals(events, cfg)
    events = _deduplicate_events(events, cfg)
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
    
    speed = signals["center_speed"]
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
        if activity[i] < cfg.shot_min_activity:
            continue
        
        # Acceleration should be positive (ball accelerating)
        if accel[i] < 0:
            continue
        
        # Look for buildup: sustained moderate activity before the shot
        buildup_start = max(0, i - 30)  # ~1 second before
        buildup_activity = np.mean(activity[buildup_start:i])
        if buildup_activity < 0.3:
            continue
        
        # Compute confidence
        confidence = _shot_confidence(
            speed_spike, speed[i], activity[i], buildup_activity, cfg
        )
        
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
    
    speed = signals["center_speed"]
    accel = signals["speed_accel"]
    pos = signals["center_x"]
    time = signals["time"]
    
    for i in range(5, n - 5):
        # Need high incoming speed (fast play, not gentle ebb)
        if speed[i] < cfg.save_min_speed:
            continue
        
        # Look ahead for speed drop
        lookahead = min(i + 20, n - 1)
        future_speed = speed[i + 1:lookahead]
        
        if len(future_speed) < 3:
            continue
        
        min_future = np.min(future_speed)
        
        # Speed must drop significantly
        if min_future > speed[i] * (1 - cfg.save_speed_drop):
            continue
        
        # Must be near a goal end (extreme position), not mid-field
        near_goal = (pos[i] < cfg.save_position_threshold * 1000.0) or \
                    (pos[i] > 1000.0 - cfg.save_position_threshold * 1000.0)
        if not near_goal:
            continue
        
        # Look for reversal after the stop
        min_idx = i + 1 + np.argmin(future_speed)
        if min_idx < n - 10:
            post_save_speed = np.max(speed[min_idx:min(min_idx + 30, n)])
            if post_save_speed < cfg.save_reversal_min_speed:
                continue  # No clear — might be a goal instead
        
        confidence = 0.6 + 0.2 * (speed[i] / 100.0) + 0.2 * (1 - min_future / max(speed[i], 1e-6))
        confidence = min(confidence, 1.0)
        
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
    """Detect face-offs from clustered positions at center with activity ramp.
    
    A face-off is characterized by:
    1. Multiple objects near center X (players clustered)
    2. Activity starts near zero and ramps up
    3. Position stays near center briefly then disperses
    """
    events: List[Event] = []
    n = len(points)
    
    objects = signals["objects"]
    pos = signals["center_x"]
    activity = signals["activity"]
    time = signals["time"]
    
    center_low, center_high = cfg.faceoff_center_zone
    
    for i in range(10, n - 10):
        # Objects clustered near center
        if objects[i] < cfg.faceoff_max_objects:
            continue
        
        in_center = center_low <= pos[i] <= center_high
        if not in_center:
            continue
        
        # Activity must be ramping up from low
        pre_activity = float(np.mean(activity[max(0, i - 10):i]))
        post_activity = float(np.mean(activity[i:min(n - 1, i + 10)]))
        
        if pre_activity > cfg.faceoff_activity_ramp:
            continue
        if post_activity < cfg.faceoff_activity_ramp * 2:
            continue
        
        # Check objects disperse after (position variance increases)
        post_positions = pos[i:min(n - 1, i + 30)]
        dispersion = float(np.std(post_positions)) if len(post_positions) > 1 else 0
        
        if dispersion < 50:  # Players must spread out
            continue
        
        events.append(Event(
            event_type=EventType.FACE_OFF,
            start_time_sec=float(time[max(0, i - 15)]),
            end_time_sec=float(time[min(n - 1, i + 30)]),
            peak_time_sec=float(time[i]),
            confidence=min(0.5 + 0.3 * (objects[i] / 15.0) + 0.2 * (post_activity / 0.8), 0.95),
            frame_range=(points[max(0, i - 15)].frame_num, points[min(n - 1, i + 30)].frame_num),
            description=f"Face-off at {time[i]:.1f}s, {int(objects[i])} objects at center",
        ))
    
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

def _resolve_goals(events: List[Event], cfg: DetectionConfig) -> List[Event]:
    """Promote shots to goals when followed by celebration activity spike."""
    shots = [e for e in events if e.event_type == EventType.SHOT]
    
    for shot in shots:
        # Look for activity spike after the shot
        nearby = [
            e for e in events
            if e.event_type in (EventType.SAVE, EventType.TURNOVER)
            and abs(e.peak_time_sec - shot.peak_time_sec) < cfg.goal_confirmation_window_sec
        ]
        
        # If a save is detected right after, it's NOT a goal
        if any(e.event_type == EventType.SAVE for e in nearby):
            continue
        
        # If no save and no turnover, upgrade confidence toward goal
        if not nearby:
            shot.confidence = min(shot.confidence * 1.2, 0.95)
            shot.event_type = EventType.GOAL
            shot.description = shot.description.replace("Shot attempt", "Goal")
            shot.tags.append("scoring_play")
    
    return events


def _deduplicate_events(events: List[Event], cfg: DetectionConfig) -> List[Event]:
    """Remove duplicate events that are too close together."""
    if not events:
        return events
    
    # Sort by time
    sorted_events = sorted(events, key=lambda e: e.peak_time_sec)
    
    kept: List[Event] = []
    for e in sorted_events:
        # Check if too close to the last kept event
        if kept:
            last = kept[-1]
            gap = e.peak_time_sec - last.peak_time_sec
            
            if gap < cfg.min_event_spacing_sec:
                # Same event type → keep higher confidence
                if e.event_type == last.event_type:
                    if e.confidence > last.confidence:
                        kept[-1] = e
                    continue
                # Different types → keep higher priority
                elif e.confidence <= last.confidence:
                    continue
        
        kept.append(e)
    
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
