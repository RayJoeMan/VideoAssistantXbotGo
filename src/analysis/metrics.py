"""
Performance Metrics from Telemetry Data

Computes player and game-level metrics from parsed track data.
Used for ranking highlights, generating stat lines, and
providing context for event descriptions.

Metrics computed:
  - Speed (avg, max, distribution)
  - Distance covered (cumulative position delta)
  - Heat map data (position density over time)
  - Possession segments (directional movement clusters)
  - Intensity scoring (composite activity × speed × object count)
  - Period breakdowns (by quarter/half)

Usage:
    from src.telemetry.parser import parse_track_file
    from src.analysis.metrics import compute_game_metrics, rank_events

    track = parse_track_file("game.track")
    metrics = compute_game_metrics(track)
    print(f"Total distance: {metrics['total_distance']:.0f} units")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from telemetry.models import (
    TrackPoint, Event, EventType, PlayIntensity,
    GameMetadata,
)
from telemetry.parser import ParsedTrack
from telemetry.logging_setup import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════

def compute_game_metrics(track: ParsedTrack) -> dict:
    """Compute comprehensive game metrics from parsed track data.
    
    Returns a dictionary with:
        speed: {avg, max, median, p90}
        distance: {total, per_minute}
        activity: {avg, active_pct, intense_pct, peak_window}
        objects: {avg_per_frame, max, total_detections}
        possession: {direction_changes, avg_segment_duration}
        intensity: {score, breakdown_by_period}
        periods: [{start, end, avg_activity, events}]
    """
    points = track.points
    if not points:
        return {}
    
    n = len(points)
    time = np.array([p.timestamp_sec for p in points])
    activity = np.array([p.activity_score for p in points])
    speed = np.abs(np.array([p.center_speed for p in points]))
    pos = np.array([p.center_x for p in points])
    objects = np.array([p.objects_detected for p in points], dtype=float)
    
    total_duration = track.metadata.total_duration_sec
    
    # ── Speed metrics ──
    speed_metrics = {
        "avg": round(float(np.mean(speed)), 1),
        "max": round(float(np.max(speed)), 1),
        "median": round(float(np.median(speed)), 1),
        "p90": round(float(np.percentile(speed, 90)), 1),
    }
    
    # ── Distance metrics ──
    # Cumulative absolute position change
    pos_deltas = np.abs(np.diff(pos))
    total_distance = float(np.sum(pos_deltas))
    distance_per_minute = total_distance / max(total_duration / 60.0, 0.1)
    
    distance_metrics = {
        "total": round(total_distance, 0),
        "per_minute": round(distance_per_minute, 0),
    }
    
    # ── Activity metrics ──
    active_frames = int(np.sum(activity >= 0.5))
    intense_frames = int(np.sum(activity >= 0.75))
    
    # Find peak activity window (5-second sliding window)
    window_frames = int(5.0 * 30.0)  # ~5 seconds at 30fps
    if window_frames > 1 and n > window_frames:
        window_avgs = np.convolve(activity, np.ones(window_frames)/window_frames, mode='valid')
        peak_idx = int(np.argmax(window_avgs))
        peak_start = float(time[peak_idx]) if peak_idx < len(time) else 0.0
    else:
        peak_start = 0.0
    
    activity_metrics = {
        "avg": round(float(np.mean(activity)), 2),
        "active_pct": round(active_frames / max(n, 1) * 100, 1),
        "intense_pct": round(intense_frames / max(n, 1) * 100, 1),
        "peak_window_start_sec": round(peak_start, 1),
    }
    
    # ── Object detection metrics ──
    object_metrics = {
        "avg_per_frame": round(float(np.mean(objects)), 1),
        "max": int(np.max(objects)),
        "total_detections": int(np.sum(objects)),
    }
    
    # ── Possession metrics ──
    direction_changes = _count_direction_changes(pos)
    segments = _segment_possession(pos, time)
    
    possession_metrics = {
        "direction_changes": direction_changes,
        "avg_segment_duration_sec": round(
            float(np.mean([s["duration"] for s in segments])) if segments else 0, 1
        ),
        "total_segments": len(segments),
    }
    
    # ── Intensity score (composite 0-100) ──
    intensity_score = _compute_intensity_score(
        activity_metrics["active_pct"],
        speed_metrics["avg"],
        activity_metrics["avg"],
        object_metrics["avg_per_frame"],
    )
    
    intensity_metrics = {
        "score": round(intensity_score, 1),
        "rating": _intensity_rating(intensity_score),
    }
    
    # ── Period breakdown ──
    periods = _compute_periods(points, total_duration)
    
    return {
        "speed": speed_metrics,
        "distance": distance_metrics,
        "activity": activity_metrics,
        "objects": object_metrics,
        "possession": possession_metrics,
        "intensity": intensity_metrics,
        "periods": periods,
    }


def rank_events(
    events: List[Event],
    top_n: int = 10,
) -> List[Event]:
    """Rank events by composite priority score for highlight selection.
    
    Priority = confidence × intensity_weight × activity_context
    
    Returns top_n events sorted by priority (highest first).
    """
    scored = sorted(events, key=lambda e: e.priority_score, reverse=True)
    return scored[:top_n]


def compute_event_context(
    event: Event,
    points: List[TrackPoint],
    window_sec: float = 5.0,
) -> dict:
    """Get the telemetry context around an event for clip description.
    
    Returns a dict with pre/post activity, speed, and position stats.
    """
    time = np.array([p.timestamp_sec for p in points])
    
    peak_t = event.peak_time_sec
    pre_mask = (time >= peak_t - window_sec) & (time < peak_t)
    post_mask = (time >= peak_t) & (time <= peak_t + window_sec)
    
    pre_indices = np.where(pre_mask)[0]
    post_indices = np.where(post_mask)[0]
    
    def stats(indices):
        if len(indices) == 0:
            return {"activity": 0.0, "speed": 0.0}
        return {
            "activity": round(float(np.mean([points[i].activity_score for i in indices])), 2),
            "speed": round(float(np.mean([abs(points[i].center_speed) for i in indices])), 1),
        }
    
    return {
        "pre_event": stats(pre_indices),
        "post_event": stats(post_indices),
        "peak_activity": round(float(
            np.mean([p.activity_score for p in points[max(0, int(peak_t * 30) - 5):int(peak_t * 30) + 5]])
        ), 2) if points else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ══════════════════════════════════════════════════════════════════════════

def _count_direction_changes(pos: np.ndarray, min_delta: float = 50.0) -> int:
    """Count significant direction changes in position signal."""
    if len(pos) < 3:
        return 0
    
    # Smooth position
    window = min(10, len(pos) // 2)
    if window > 1:
        smooth = np.convolve(pos, np.ones(window)/window, mode='same')
    else:
        smooth = pos
    
    changes = 0
    prev_sign = 0
    
    for i in range(1, len(smooth)):
        delta = smooth[i] - smooth[i - 1]
        if abs(delta) < min_delta:
            continue
        
        sign = 1 if delta > 0 else -1
        if prev_sign != 0 and sign != prev_sign:
            changes += 1
        prev_sign = sign
    
    return changes


def _segment_possession(
    pos: np.ndarray,
    time: np.ndarray,
    min_segment_sec: float = 3.0,
) -> List[dict]:
    """Segment the game into directional possession segments."""
    if len(pos) < 10:
        return []
    
    segments = []
    seg_start = 0
    prev_dir = 0
    
    for i in range(5, len(pos)):
        delta = pos[i] - pos[i - 5]
        curr_dir = 1 if delta > 20 else (-1 if delta < -20 else 0)
        
        if curr_dir != 0 and curr_dir != prev_dir and prev_dir != 0:
            duration = float(time[i] - time[seg_start])
            if duration >= min_segment_sec:
                direction = "right" if prev_dir > 0 else "left"
                segments.append({
                    "start_sec": round(float(time[seg_start]), 1),
                    "end_sec": round(float(time[i]), 1),
                    "duration": round(duration, 1),
                    "direction": direction,
                })
            seg_start = i
        
        if curr_dir != 0:
            prev_dir = curr_dir
    
    # Final segment
    if seg_start < len(pos) - 5:
        duration = float(time[-1] - time[seg_start])
        if duration >= min_segment_sec:
            direction = "right" if prev_dir > 0 else "left"
            segments.append({
                "start_sec": round(float(time[seg_start]), 1),
                "end_sec": round(float(time[-1]), 1),
                "duration": round(duration, 1),
                "direction": direction,
            })
    
    return segments


def _compute_intensity_score(
    active_pct: float,
    avg_speed: float,
    avg_activity: float,
    avg_objects: float,
) -> float:
    """Compute a composite game intensity score (0-100).
    
    Weighted combination of activity %, speed, and object density.
    """
    # Activity contribution (0-50)
    activity_score = min(active_pct / 100.0, 1.0) * 50
    
    # Speed contribution (0-30)
    speed_score = min(avg_speed / 80.0, 1.0) * 30
    
    # Object density contribution (0-20)
    object_score = min(avg_objects / 15.0, 1.0) * 20
    
    return activity_score + speed_score + object_score


def _intensity_rating(score: float) -> str:
    """Convert intensity score to human-readable rating."""
    if score >= 75:
        return "elite"
    elif score >= 60:
        return "high"
    elif score >= 40:
        return "moderate"
    elif score >= 20:
        return "low"
    return "inactive"


def _compute_periods(points: List[TrackPoint], total_duration: float) -> List[dict]:
    """Break the game into ~5-minute periods for stat comparison."""
    period_sec = 300.0  # 5 minutes
    n_periods = max(1, int(total_duration / period_sec))
    periods = []
    
    for p in range(n_periods):
        t_start = p * period_sec
        t_end = min((p + 1) * period_sec, total_duration)
        
        period_points = [
            pt for pt in points
            if t_start <= pt.timestamp_sec < t_end
        ]
        
        if not period_points:
            continue
        
        avg_act = np.mean([pt.activity_score for pt in period_points])
        avg_speed = np.mean([abs(pt.center_speed) for pt in period_points])
        
        periods.append({
            "period": p + 1,
            "start_sec": round(t_start, 1),
            "end_sec": round(t_end, 1),
            "duration_sec": round(t_end - t_start, 1),
            "avg_activity": round(float(avg_act), 2),
            "avg_speed": round(float(avg_speed), 1),
            "frames": len(period_points),
        })
    
    return periods
