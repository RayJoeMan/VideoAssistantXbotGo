"""Player-highlight editing: project model, keyframe tracking, rendering.

Session 1 (Tier 1): the project file (project.py), smoothstep keyframe
interpolation (tracking.py), and the spotlight renderer (render.py).
Voiceover, captions and the dual exports land in later sessions.

tracking.py also carries telemetry-compensated interpolation: when a
project names Falcon .track telemetry, keyframes are interpolated in
a camera-independent field space so camera pans stop dragging the
spotlight ring off the player (the fix for the drift defect Joe
spotted in the Session 1 smoke render).
"""

from .project import (
    PROJECT_VERSION,
    ClipWindow,
    DimSettings,
    ExportPreset,
    HighlightProject,
    Keyframe,
    RingSettings,
    TelemetrySettings,
    default_export_presets,
    load_project,
    save_project,
)
from .render import (
    build_ffmpeg_command,
    build_filtergraph,
    build_position_provider,
    frame_source_time,
    freeze_frame_count,
    output_frame_count,
    overlay_frame_rgba,
    render_project,
    write_overlay_frames,
)
from .tracking import (
    CameraCalibration,
    CameraState,
    CameraTrack,
    CompensatedInterpolator,
    frame_to_field,
    field_to_frame,
    load_camera_track,
    position_at,
    position_at_compensated,
    sample_positions,
    smoothstep,
)

__all__ = [
    "PROJECT_VERSION",
    "CameraCalibration",
    "CameraState",
    "CameraTrack",
    "ClipWindow",
    "CompensatedInterpolator",
    "DimSettings",
    "ExportPreset",
    "HighlightProject",
    "Keyframe",
    "RingSettings",
    "TelemetrySettings",
    "build_ffmpeg_command",
    "build_filtergraph",
    "build_position_provider",
    "default_export_presets",
    "frame_source_time",
    "frame_to_field",
    "field_to_frame",
    "freeze_frame_count",
    "load_camera_track",
    "load_project",
    "output_frame_count",
    "overlay_frame_rgba",
    "position_at",
    "position_at_compensated",
    "render_project",
    "sample_positions",
    "save_project",
    "smoothstep",
    "write_overlay_frames",
]
