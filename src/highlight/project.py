"""Highlight project model — the editable description of one play's edit.

A project is data, not pixels: it names a source video, a clip window in
source-video seconds, and a set of player keyframes in normalized frame
coordinates.  Everything downstream renders from this file — the Tier 1
spotlight renderer now; voiceover, captions and the dual exports in later
build sessions — so a project can be re-rendered at any size without
re-editing.

File format (``project.json``, UTF-8, 2-space indent)::

    {
      "version": 1,
      "source_video": "VID_20260614_125909_01_01.mp4",
      "window": {"start": 100.0, "end": 125.0},
      "tag_text": "#25",
      "dim": {"enabled": true, "strength": 0.35},
      "freeze_intro_s": 1.0,
      "ring": {"rx": 0.045, "ry": 0.028},
      "keyframes": [{"t": 100.0, "x": 0.42, "y": 0.66}, ...],
      "export_presets": [
        {"name": "recruiting", "width": 1920, "height": 1080}, ...
      ]
    }

Conventions:
  * Keyframe ``t`` is in SOURCE-video seconds — the same clock the
    detector events and .mark.fp markers use — and must lie inside the
    clip window.
  * ``x``/``y`` are normalized frame coordinates (0..1); ``y`` is the
    player's ground position (feet), measured downward from the top.
  * ``ring.rx``/``ring.ry`` are the spotlight ellipse radii as fractions
    of frame width/height.
  * A relative ``source_video`` is resolved against the project file's
    folder at load time when a file exists there; otherwise it is kept
    as written (and later resolved against the working directory).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_VERSION = 1

MAX_FREEZE_INTRO_S = 3.0


def _num(name: str, value, lo: float, hi: float) -> float:
    """Coerce *value* to a finite float inside [lo, hi] or raise ValueError."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(out) or out < lo or out > hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {out}")
    return out


# ══════════════════════════════════════════════════════════════════════════
# Model
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Keyframe:
    """One editor click: the player is at (x, y) at source time ``t``."""

    t: float
    x: float
    y: float

    def __post_init__(self) -> None:
        self.t = _num("keyframe.t", self.t, 0.0, 1e9)
        self.x = _num("keyframe.x", self.x, 0.0, 1.0)
        self.y = _num("keyframe.y", self.y, 0.0, 1.0)

    def to_dict(self) -> dict:
        return {"t": self.t, "x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> "Keyframe":
        if not isinstance(data, dict):
            raise ValueError(f"keyframe must be an object, got {data!r}")
        try:
            return cls(t=data["t"], x=data["x"], y=data["y"])
        except KeyError as exc:
            raise ValueError(f"keyframe missing field {exc}") from None


@dataclass
class ClipWindow:
    """The [start, end] slice of the source video, in source seconds."""

    start: float
    end: float

    def __post_init__(self) -> None:
        self.start = _num("window.start", self.start, 0.0, 1e9)
        self.end = _num("window.end", self.end, 0.0, 1e9)
        if self.end <= self.start:
            raise ValueError(
                f"window.end ({self.end}) must be after window.start ({self.start})"
            )

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: dict) -> "ClipWindow":
        if not isinstance(data, dict):
            raise ValueError(f"window must be an object, got {data!r}")
        try:
            return cls(start=data["start"], end=data["end"])
        except KeyError as exc:
            raise ValueError(f"window missing field {exc}") from None


@dataclass
class DimSettings:
    """Dim-everything-but-the-player spotlight mask."""

    enabled: bool = True
    strength: float = 0.35  # alpha of the black mask far from the player

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.strength = _num("dim.strength", self.strength, 0.0, 0.95)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "strength": self.strength}

    @classmethod
    def from_dict(cls, data: dict) -> "DimSettings":
        if not isinstance(data, dict):
            raise ValueError(f"dim must be an object, got {data!r}")
        return cls(
            enabled=data.get("enabled", True),
            strength=data.get("strength", 0.35),
        )


@dataclass
class RingSettings:
    """Spotlight ellipse radii, as fractions of frame width/height."""

    rx: float = 0.045
    ry: float = 0.028

    def __post_init__(self) -> None:
        self.rx = _num("ring.rx", self.rx, 0.005, 0.5)
        self.ry = _num("ring.ry", self.ry, 0.005, 0.5)

    def to_dict(self) -> dict:
        return {"rx": self.rx, "ry": self.ry}

    @classmethod
    def from_dict(cls, data: dict) -> "RingSettings":
        if not isinstance(data, dict):
            raise ValueError(f"ring must be an object, got {data!r}")
        return cls(rx=data.get("rx", 0.045), ry=data.get("ry", 0.028))


@dataclass
class ExportPreset:
    """A named output size.  Session 1 only stores these; the export
    sessions consume them."""

    name: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"export preset name must be non-empty, got {self.name!r}")
        for label, value in (("width", self.width), ("height", self.height)):
            if int(value) != value or int(value) <= 0:
                raise ValueError(f"export preset {label} must be a positive int, got {value!r}")
        self.width = int(self.width)
        self.height = int(self.height)

    def to_dict(self) -> dict:
        return {"name": self.name, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict) -> "ExportPreset":
        if not isinstance(data, dict):
            raise ValueError(f"export preset must be an object, got {data!r}")
        try:
            return cls(name=data["name"], width=data["width"], height=data["height"])
        except KeyError as exc:
            raise ValueError(f"export preset missing field {exc}") from None


def default_export_presets() -> List[ExportPreset]:
    return [
        ExportPreset("recruiting", 1920, 1080),
        ExportPreset("vertical", 1080, 1920),
        ExportPreset("clean", 1920, 1080),
    ]


@dataclass
class HighlightProject:
    """One play's complete edit description (see module docstring)."""

    source_video: str
    window: ClipWindow
    keyframes: List[Keyframe]
    tag_text: str = "#25"
    dim: DimSettings = field(default_factory=DimSettings)
    freeze_intro_s: float = 1.0
    ring: RingSettings = field(default_factory=RingSettings)
    export_presets: List[ExportPreset] = field(default_factory=default_export_presets)

    def __post_init__(self) -> None:
        if not isinstance(self.source_video, str) or not self.source_video.strip():
            raise ValueError(f"source_video must be a non-empty string, got {self.source_video!r}")
        if not isinstance(self.tag_text, str):
            raise ValueError(f"tag_text must be a string, got {self.tag_text!r}")
        self.freeze_intro_s = _num(
            "freeze_intro_s", self.freeze_intro_s, 0.0, MAX_FREEZE_INTRO_S
        )
        if not self.keyframes:
            raise ValueError("project needs at least one keyframe")
        times = [k.t for k in self.keyframes]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("keyframe times must be strictly increasing")
        for k in self.keyframes:
            if not (self.window.start <= k.t <= self.window.end):
                raise ValueError(
                    f"keyframe at t={k.t} lies outside the clip window "
                    f"[{self.window.start}, {self.window.end}]"
                )
        names = [p.name for p in self.export_presets]
        if len(set(names)) != len(names):
            raise ValueError(f"export preset names must be unique, got {names}")

    @property
    def output_duration(self) -> float:
        """Rendered length: freeze intro followed by the full window."""
        return self.freeze_intro_s + self.window.duration

    def preset(self, name: str) -> ExportPreset:
        for p in self.export_presets:
            if p.name == name:
                return p
        raise ValueError(
            f"no export preset named {name!r}; have {[p.name for p in self.export_presets]}"
        )

    # ── serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "version": PROJECT_VERSION,
            "source_video": self.source_video,
            "window": self.window.to_dict(),
            "tag_text": self.tag_text,
            "dim": self.dim.to_dict(),
            "freeze_intro_s": self.freeze_intro_s,
            "ring": self.ring.to_dict(),
            "keyframes": [k.to_dict() for k in self.keyframes],
            "export_presets": [p.to_dict() for p in self.export_presets],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HighlightProject":
        if not isinstance(data, dict):
            raise ValueError(f"project must be a JSON object, got {data!r}")
        version = data.get("version", PROJECT_VERSION)
        if version != PROJECT_VERSION:
            raise ValueError(f"unsupported project version {version!r}")
        try:
            source_video = data["source_video"]
            window = ClipWindow.from_dict(data["window"])
            raw_keyframes = data["keyframes"]
        except KeyError as exc:
            raise ValueError(f"project missing field {exc}") from None
        if not isinstance(raw_keyframes, list):
            raise ValueError(f"keyframes must be a list, got {raw_keyframes!r}")
        return cls(
            source_video=source_video,
            window=window,
            keyframes=[Keyframe.from_dict(k) for k in raw_keyframes],
            tag_text=data.get("tag_text", "#25"),
            dim=DimSettings.from_dict(data.get("dim", {})),
            freeze_intro_s=data.get("freeze_intro_s", 1.0),
            ring=RingSettings.from_dict(data.get("ring", {})),
            export_presets=[
                ExportPreset.from_dict(p) for p in data.get("export_presets", [])
            ]
            or default_export_presets(),
        )


# ══════════════════════════════════════════════════════════════════════════
# File IO
# ══════════════════════════════════════════════════════════════════════════

def save_project(project: HighlightProject, path) -> Path:
    """Write *project* as pretty JSON (2-space indent, trailing newline)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out


def load_project(path) -> HighlightProject:
    """Load a project file, validating every field.

    A relative ``source_video`` that names a file sitting beside the
    project file is resolved to that absolute path.
    """
    src = Path(path)
    data = json.loads(src.read_text(encoding="utf-8"))
    project = HighlightProject.from_dict(data)
    video = Path(project.source_video)
    if not video.is_absolute():
        beside = src.resolve().parent / video
        if beside.exists():
            project.source_video = str(beside)
    return project
