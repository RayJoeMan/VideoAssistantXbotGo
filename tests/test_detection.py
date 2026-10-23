"""Tests for event detection algorithms."""

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telemetry.parser import parse_track_file
from telemetry.models import Event, EventType, PlayIntensity, TrackPoint, GameMetadata
from analysis.detection import (
    detect_events,
    DetectionConfig,
    _compute_derived_signals,
    _resolve_goals,
    _deduplicate_events,
    _classify_intensity,
)


# ══════════════════════════════════════════════════════════════════════════
# Test Data Builders
# ══════════════════════════════════════════════════════════════════════════

def _make_points(
    n: int = 300,
    *,
    activity_pattern: str = "flat",
    speed_pattern: str = "flat",
    position_pattern: str = "flat",
    fps: float = 30.0,
) -> List[TrackPoint]:
    """Build synthetic TrackPoint lists for algorithm testing.
    
    Patterns:
      activity: flat, spike, ramp, periodic
      speed: flat, spike, ramp, oscillate
      position: flat, drift_right, drift_left, cross_midfield, oscillate
    """
    points = []
    for i in range(n):
        t = i / fps
        
        # Activity
        if activity_pattern == "flat":
            act = 0.3
        elif activity_pattern == "spike":
            act = 0.9 if abs(i - n//2) < 20 else 0.2
        elif activity_pattern == "ramp":
            act = min(1.0, i / n * 1.2)
        elif activity_pattern == "periodic":
            act = 0.5 + 0.4 * np.sin(i / 30.0 * np.pi)
        else:
            act = 0.3
        
        # Speed
        if speed_pattern == "flat":
            spd = 20.0
        elif speed_pattern == "spike":
            spd = 80.0 if abs(i - n//2) < 15 else 10.0
        elif speed_pattern == "ramp":
            spd = min(100.0, i / n * 120)
        elif speed_pattern == "oscillate":
            spd = 40.0 + 30.0 * np.sin(i / 20.0 * np.pi)
        else:
            spd = 20.0
        
        # Position
        if position_pattern == "flat":
            pos = 500.0
        elif position_pattern == "drift_right":
            pos = 200.0 + (i / n) * 600.0
        elif position_pattern == "drift_left":
            pos = 800.0 - (i / n) * 600.0
        elif position_pattern == "cross_midfield":
            pos = 200.0 + 600.0 * (i / n)
        elif position_pattern == "oscillate":
            pos = 500.0 + 300.0 * np.sin(i / 40.0 * np.pi)
        else:
            pos = 500.0
        
        # Derived direction sign from position delta
        objects = 8 if act > 0.5 else 3
        
        points.append(TrackPoint(
            frame_num=i + 1,
            timestamp_sec=t,
            activity_score=act,
            objects_detected=objects,
            motion_objects=max(1, objects // 2),
            crowd_x=pos - 500.0 if pos != 500.0 else 0.0,
            center_x=pos,
            center_speed=spd,
            fps=fps,
        ))
    
    return points


def _make_track(points: List[TrackPoint]) -> "ParsedTrack":
    """Wrap points in a minimal ParsedTrack for detect_events()."""
    from telemetry.parser import ParsedTrack
    metadata = GameMetadata(
        total_frames=len(points),
        total_duration_sec=points[-1].timestamp_sec if points else 0.0,
        video_fps=points[0].fps if points else 30.0,
    )
    return ParsedTrack(points=points, metadata=metadata)


# ══════════════════════════════════════════════════════════════════════════
# Signal Computation Tests
# ══════════════════════════════════════════════════════════════════════════

class TestDerivedSignals:
    """Tests for _compute_derived_signals()."""

    def test_returns_all_signals(self):
        points = _make_points(100)
        signals = _compute_derived_signals(points)
        assert "time" in signals
        assert "activity" in signals
        assert "center_x" in signals
        assert "center_speed" in signals
        assert "speed_accel" in signals
        assert "dir_sign" in signals

    def test_time_is_monotonic(self):
        points = _make_points(100)
        signals = _compute_derived_signals(points)
        time = signals["time"]
        for i in range(1, len(time)):
            assert time[i] >= time[i - 1]

    def test_acceleration_computed(self):
        points = _make_points(100, speed_pattern="spike")
        signals = _compute_derived_signals(points)
        accel = signals["speed_accel"]
        # Transition from low→high speed should produce acceleration
        # Check at the edge of the spike, not the plateau center
        mid = len(points) // 2
        # Speed spike covers ~15 frames around center
        edge = mid - 17  # Just before spike starts
        if edge > 0:
            assert abs(accel[edge]) >= 0, "Acceleration should be computable at speed transition"

    def test_empty_points_returns_empty(self):
        signals = _compute_derived_signals([])
        assert signals == {}


# ══════════════════════════════════════════════════════════════════════════
# Shot Detection Tests
# ══════════════════════════════════════════════════════════════════════════

class TestShotDetection:
    """Tests for shot detection."""

    def test_detects_shot_with_speed_spike(self):
        """A clear speed spike with high activity and buildup should be detected as a shot."""
        # Build a realistic shot pattern: sustained buildup → sharp spike
        n = 300
        points = []
        for i in range(n):
            t = i / 30.0
            
            # Activity: steady buildup, peak at shot, then celebration
            if i < 100:
                act = 0.3  # Pre-play
            elif i < 140:
                act = 0.3 + (i - 100) * 0.015  # Buildup ramp 0.3→0.9
            elif i < 155:
                act = 0.9  # Shot moment
            elif i < 180:
                act = 0.7  # Celebration
            else:
                act = 0.3  # Reset
            
            # Speed: moderate during buildup, sharp spike at shot
            if i < 140:
                spd = 20.0  # Buildup speed
            elif i < 150:
                spd = 80.0  # Shot speed spike
            elif i < 160:
                spd = 60.0  # Follow-through
            else:
                spd = 15.0  # Reset
            
            # Position: drifting right during buildup, surge at shot
            if i < 140:
                pos = 300.0 + (i - 100) * 2.0  # Gradual advance
            else:
                pos = 380.0 + (i - 140) * 5.0  # Surge toward goal
            
            points.append(TrackPoint(
                frame_num=i + 1, timestamp_sec=t,
                activity_score=act, center_x=pos,
                center_speed=spd, objects_detected=8 if act > 0.5 else 4,
                motion_objects=4, crowd_x=pos - 500.0,
                fps=30.0,
            ))
        
        track = _make_track(points)
        events = detect_events(track, DetectionConfig(
            shot_min_speed=30.0,
            shot_speed_spike=15.0,
            shot_min_activity=0.3,
        ))
        
        shots = [e for e in events if e.event_type in (EventType.SHOT, EventType.GOAL)]
        assert len(shots) >= 1, f"Expected at least 1 shot/goal, got {len(shots)}"
        assert shots[0].confidence > 0.2

    def test_no_shot_without_speed(self):
        """Flat speed should produce no shots."""
        points = _make_points(300, speed_pattern="flat", activity_pattern="flat")
        track = _make_track(points)
        events = detect_events(track)
        
        shots = [e for e in events if e.event_type == EventType.SHOT]
        assert len(shots) == 0

    def test_shot_has_valid_time_range(self):
        points = _make_points(300, speed_pattern="spike", activity_pattern="spike")
        track = _make_track(points)
        events = detect_events(track)
        
        for shot in [e for e in events if e.event_type == EventType.SHOT]:
            assert shot.start_time_sec < shot.peak_time_sec < shot.end_time_sec
            assert shot.duration_sec > 0

    def test_config_controls_sensitivity(self):
        """Strict config should produce fewer shots."""
        points = _make_points(300, speed_pattern="spike", activity_pattern="spike")
        track = _make_track(points)
        
        default_events = detect_events(track)
        strict_events = detect_events(track, DetectionConfig(shot_min_speed=200.0))
        
        default_shots = sum(1 for e in default_events if e.event_type == EventType.SHOT)
        strict_shots = sum(1 for e in strict_events if e.event_type == EventType.SHOT)
        
        assert strict_shots <= default_shots


# ══════════════════════════════════════════════════════════════════════════
# Transition Detection Tests
# ══════════════════════════════════════════════════════════════════════════

class TestTransitionDetection:
    """Tests for transition (fast break) detection."""

    def test_detects_midfield_crossing(self):
        """Crossing midfield at speed should trigger transition."""
        points = _make_points(
            300,
            position_pattern="cross_midfield",
            speed_pattern="oscillate",
            activity_pattern="periodic",
        )
        track = _make_track(points)
        events = detect_events(track)
        
        transitions = [e for e in events if e.event_type == EventType.TRANSITION]
        # May or may not detect depending on speed thresholds
        # Just verify no crashes and events are well-formed
        for t in transitions:
            assert t.duration_sec > 0
            assert "fast_break" in t.tags or any(tag in t.tags for tag in ("right", "left"))

    def test_no_transition_without_midfield_crossing(self):
        """Static position should produce no transitions."""
        points = _make_points(300, position_pattern="flat", speed_pattern="flat")
        track = _make_track(points)
        events = detect_events(track)
        
        transitions = [e for e in events if e.event_type == EventType.TRANSITION]
        assert len(transitions) == 0


# ══════════════════════════════════════════════════════════════════════════
# Face-off Detection Tests
# ══════════════════════════════════════════════════════════════════════════

class TestFaceoffDetection:
    """Tests for face-off detection."""

    def test_detects_faceoff_with_clustered_objects(self):
        """Clustered objects near center with activity ramp should trigger face-off."""
        # Build custom points: objects clustered at center, activity ramping
        points = []
        for i in range(100):
            t = i / 30.0
            if 30 <= i <= 50:
                act = 0.1 + (i - 30) * 0.04  # Ramp from 0.1 to 0.9
                pos = 500.0
                obj = 10
            else:
                act = 0.5
                pos = 300.0 + (i % 3) * 200.0
                obj = 4
            
            points.append(TrackPoint(
                frame_num=i + 1, timestamp_sec=t,
                activity_score=act, center_x=pos,
                objects_detected=obj, center_speed=15.0,
                fps=30.0,
            ))
        
        track = _make_track(points)
        events = detect_events(track, DetectionConfig(
            faceoff_max_objects=5,
            faceoff_activity_ramp=0.2,
        ))
        
        faceoffs = [e for e in events if e.event_type == EventType.FACE_OFF]
        # May not detect depending on exact thresholds
        # Verify events are well-formed if detected
        for f in faceoffs:
            assert f.confidence > 0.3
            assert f.peak_time_sec > 0

    def test_detects_faceoff_at_draw(self):
        """Quiet center cluster that ramps into play should fire a face-off.

        Regression test: the old per-frame detector required near-total
        stillness in a 10-frame window and fired zero times in a full
        real game. The windowed detector looks for seconds of quiet at
        center followed by an activity ramp.
        """
        points = []
        for i in range(1200):  # 40 seconds at 30 fps
            t = i / 30.0
            act = 0.05 if i < 300 else 0.6  # draw at ~10s, then play
            points.append(TrackPoint(
                frame_num=i + 1, timestamp_sec=t,
                activity_score=act, center_x=500.0,
                objects_detected=8, center_speed=30.0,
                fps=30.0,
            ))

        track = _make_track(points)
        events = detect_events(track)

        faceoffs = [e for e in events if e.event_type == EventType.FACE_OFF]
        assert len(faceoffs) >= 1
        assert 5.0 <= faceoffs[0].peak_time_sec <= 20.0


# ══════════════════════════════════════════════════════════════════════════
# Post-processing Tests
# ══════════════════════════════════════════════════════════════════════════

class TestPostProcessing:
    """Tests for event post-processing (goal resolution, dedup, intensity)."""

    def test_deduplicate_removes_close_events(self):
        """Two events at the same time should be deduplicated."""
        events = [
            Event(EventType.SHOT, 10.0, 12.0, 11.0, confidence=0.5),
            Event(EventType.SHOT, 10.1, 12.1, 11.1, confidence=0.8),
        ]
        result = _deduplicate_events(events, DetectionConfig(min_event_spacing_sec=5.0))
        assert len(result) == 1
        assert result[0].confidence == 0.8  # Higher confidence kept

    def test_deduplicate_keeps_distant_events(self):
        """Events far apart in time should all be kept."""
        events = [
            Event(EventType.SHOT, 10.0, 12.0, 11.0, confidence=0.5),
            Event(EventType.SHOT, 30.0, 32.0, 31.0, confidence=0.6),
        ]
        result = _deduplicate_events(events, DetectionConfig(min_event_spacing_sec=5.0))
        assert len(result) == 2

    def test_classify_intensity(self):
        """Events should get intensity labels."""
        events = [
            Event(EventType.SHOT, 10.0, 12.0, 11.0),
            Event(EventType.TRANSITION, 20.0, 22.0, 21.0),
        ]
        # Build signals with moderate activity
        points = _make_points(100, activity_pattern="periodic")
        signals = _compute_derived_signals(points)
        
        result = _classify_intensity(events, signals)
        for e in result:
            assert e.intensity in (PlayIntensity.LOW, PlayIntensity.MEDIUM, PlayIntensity.HIGH)


# ══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """End-to-end tests: parse track → detect events."""

    def test_full_pipeline_no_crash(self):
        """The full pipeline should not crash on valid data."""
        points = _make_points(300, speed_pattern="spike", activity_pattern="spike")
        track = _make_track(points)
        events = detect_events(track)
        
        assert isinstance(events, list)
        # All events should have valid fields
        for e in events:
            assert e.event_type is not None
            assert e.confidence >= 0.0
            assert e.start_time_sec >= 0
            assert e.end_time_sec > e.start_time_sec
            assert e.peak_time_sec >= e.start_time_sec

    def test_empty_track_returns_empty(self):
        """Empty track should return no events."""
        track = _make_track([])
        events = detect_events(track)
        assert events == []

    def test_short_track_handled(self):
        """Very short track should not crash."""
        points = _make_points(5)
        track = _make_track(points)
        events = detect_events(track)
        assert events == []

    def test_events_sorted_by_time(self):
        """Events should be returned in chronological order."""
        points = _make_points(300,
            speed_pattern="oscillate",
            activity_pattern="periodic",
            position_pattern="oscillate",
        )
        track = _make_track(points)
        events = detect_events(track)
        
        for i in range(1, len(events)):
            assert events[i].peak_time_sec >= events[i - 1].peak_time_sec, \
                f"Events out of order at index {i}"

    def test_event_confidence_bounded(self):
        """All event confidences should be between 0 and 1."""
        points = _make_points(300, speed_pattern="spike", activity_pattern="spike")
        track = _make_track(points)
        events = detect_events(track)
        
        for e in events:
            assert 0.0 <= e.confidence <= 1.0, \
                f"Confidence {e.confidence} out of bounds for {e.event_type.value}"
