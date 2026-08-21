"""
Telemetry data models for the Lacrosse Highlight Assistant.

Defines the domain types that abstract over FALCON .track files
and provide a clean interface for analysis and export stages.

Model hierarchy:
  TrackPoint  →  one frame of telemetry
  TrackSegment →  contiguous range of frames
  Event       →  detected play (goal, save, transition, face-off)
  GameMetadata →  game-level info (sport, venue, date, teams)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# ── Event Types ──────────────────────────────────────────────────────────

class EventType(str, Enum):
    """Categories of play events detectable from telemetry."""
    SHOT = "shot"
    SAVE = "save"
    GOAL = "goal"
    TRANSITION = "transition"
    FACE_OFF = "face_off"
    TURNOVER = "turnover"
    PENALTY = "penalty"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class PlayIntensity(str, Enum):
    """3-tier intensity classification for ranking highlights."""
    LOW = "low"         # Routine play, low crowd energy
    MEDIUM = "medium"   # Active play, moderate engagement
    HIGH = "high"       # Game-changing moment, peak activity


# ── Core Data Classes ────────────────────────────────────────────────────

@dataclass
class TrackPoint:
    """Telemetry data for a single video frame.
    
    Mirrors the FALCON .track format fields but uses
    descriptive names independent of the parsing format.
    """
    frame_num: int
    timestamp_sec: float          # Seconds from video start
    
    # Activity signal (0.0 = dead, 1.0 = intense)
    activity_score: float = 0.0
    
    # Object/person detection
    objects_detected: int = 0     # Count of tracked objects
    motion_objects: int = 0       # Objects in motion
    
    # Spatial data (normalized coordinates, 0-1000 or pixel)
    crowd_x: float = 0.0          # Crowd center x-position
    center_x: float = 0.0         # Action center x
    center_speed: float = 0.0     # Rate of center movement
    
    # Camera metadata
    fps: float = 0.0
    zoom_level: int = 0
    yaw: float = 0.0
    pitch: float = 0.0
    
    # Raw source fields (for debugging / format migration)
    raw_utc: str = ""
    raw_fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class TrackSegment:
    """A contiguous segment of frames within a track."""
    start_frame: int
    end_frame: int
    start_time_sec: float
    end_time_sec: float
    duration_sec: float = 0.0
    
    # Aggregate metrics over this segment
    avg_activity: float = 0.0
    max_activity: float = 0.0
    avg_objects: float = 0.0
    total_frames: int = 0
    
    # Classification
    intensity: PlayIntensity = PlayIntensity.LOW
    label: str = ""


@dataclass
class Event:
    """A detected play event with temporal bounds and confidence.
    
    Events are the primary output of the analysis phase and
    the primary input to the export phase.
    """
    event_type: EventType
    start_time_sec: float
    end_time_sec: float
    peak_time_sec: float          # Frame of maximum intensity
    
    confidence: float = 0.0       # 0.0 – 1.0 detection confidence
    intensity: PlayIntensity = PlayIntensity.MEDIUM
    
    # Context
    frame_range: tuple[int, int] = (0, 0)
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    # For ranking / sorting
    priority_score: float = 0.0   # Composite: confidence × intensity × activity
    
    def __post_init__(self):
        if self.priority_score == 0.0:
            intensity_weight = {"low": 0.3, "medium": 0.6, "high": 1.0}
            self.priority_score = (
                self.confidence *
                intensity_weight.get(self.intensity.value, 0.5)
            )
    
    @property
    def duration_sec(self) -> float:
        return self.end_time_sec - self.start_time_sec


@dataclass
class GameMetadata:
    """Game-level context for telemetry interpretation."""
    sport: str = "lacrosse"
    venue: str = ""
    date: Optional[datetime] = None
    home_team: str = ""
    away_team: str = ""
    camera_position: str = ""     # e.g. "sideline", "endline", "press_box"
    video_fps: float = 30.0
    total_frames: int = 0
    total_duration_sec: float = 0.0
    
    # Source info
    track_file: str = ""          # Path to the .track file
    video_file: str = ""          # Path to the source video
    track_version: str = ""       # FALCON SDK version string
    
    # Custom metadata
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class ActivityWindow:
    """A time window where activity exceeds a threshold.
    
    Used for segmenting the game into active/inactive periods.
    """
    start_time_sec: float
    end_time_sec: float
    peak_time_sec: float = 0.0
    peak_score: float = 0.0
    avg_score: float = 0.0
    frame_count: int = 0
    
    @property
    def duration_sec(self) -> float:
        return self.end_time_sec - self.start_time_sec


# ── Track Summary ────────────────────────────────────────────────────────

@dataclass
class TrackSummary:
    """Aggregate statistics for a parsed track file."""
    total_frames: int
    duration_sec: float
    active_frames: int            # Frames with activity >= 0.5
    intense_frames: int           # Frames with activity >= 0.75
    activity_pct: float           # % of frames that are active
    avg_objects_per_frame: float
    max_objects: int
    avg_center_speed: float
    active_windows: List[ActivityWindow] = field(default_factory=list)
    camera_version: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
