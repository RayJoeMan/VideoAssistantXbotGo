"""Player-highlight editing: project model, keyframe tracking, rendering.

Session 1 (Tier 1): the project file (project.py), smoothstep keyframe
interpolation (tracking.py), and the spotlight renderer (render.py).
Voiceover, captions and the dual exports land in later sessions.
"""

from .project import (
    PROJECT_VERSION,
    ClipWindow,
    DimSettings,
    ExportPreset,
    HighlightProject,
    Keyframe,
    RingSettings,
    default_export_presets,
    load_project,
    save_project,
)
from .render import (
    build_ffmpeg_command,
    build_filtergraph,
    frame_source_time,
    freeze_frame_count,
    output_frame_count,
    overlay_frame_rgba,
    render_project,
    write_overlay_frames,
)
from .tracking import position_at, sample_positions, smoothstep

__all__ = [
    "PROJECT_VERSION",
    "ClipWindow",
    "DimSettings",
    "ExportPreset",
    "HighlightProject",
    "Keyframe",
    "RingSettings",
    "build_ffmpeg_command",
    "build_filtergraph",
    "default_export_presets",
    "frame_source_time",
    "freeze_frame_count",
    "load_project",
    "output_frame_count",
    "overlay_frame_rgba",
    "position_at",
    "render_project",
    "sample_positions",
    "save_project",
    "smoothstep",
    "write_overlay_frames",
]
