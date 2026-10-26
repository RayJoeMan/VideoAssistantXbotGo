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
  * Optional ``telemetry`` block: ``{"track_file": "...", "pan_fov_deg":
    95.0}`` names the game's Falcon .track file.  When present and
    loadable, the renderer compensates keyframe interpolation for
    camera pan (see tracking.py); when absent — phone clips, say —
    rendering falls back to plain frame-space interpolation.
    ``pan_fov_deg`` is an optional calibration override.
  * Optional Session 2 blocks: ``voiceover`` (narration takes placed
    on the OUTPUT timeline, plus duck/loudnorm mix settings),
    ``captions`` (cues on the output timeline), ``callouts`` (text
    with a leader arrow on the SOURCE timeline, anchored to a
    keyframe) and ``beats`` (slow-mo / freeze marks on the source
    timeline).  Absent blocks serialize absent — a Session 1 project
    file round-trips byte-identically.
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
class TelemetrySettings:
    """Optional Falcon telemetry source for camera compensation.

    ``track_file`` names the game's .track file (relative paths are
    resolved beside the project file at load, like ``source_video``).
    ``pan_fov_deg`` optionally overrides the pan calibration — the
    horizontal field of view the yaw compensation assumes (see
    tracking.CameraCalibration); None keeps the calibrated default.
    """

    track_file: str
    pan_fov_deg: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.track_file, str) or not self.track_file.strip():
            raise ValueError(
                f"telemetry.track_file must be a non-empty string, got {self.track_file!r}"
            )
        if self.pan_fov_deg is not None:
            self.pan_fov_deg = _num("telemetry.pan_fov_deg", self.pan_fov_deg, 20.0, 180.0)

    def to_dict(self) -> dict:
        out = {"track_file": self.track_file}
        if self.pan_fov_deg is not None:
            out["pan_fov_deg"] = self.pan_fov_deg
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "TelemetrySettings":
        if not isinstance(data, dict):
            raise ValueError(f"telemetry must be an object, got {data!r}")
        try:
            return cls(
                track_file=data["track_file"],
                pan_fov_deg=data.get("pan_fov_deg"),
            )
        except KeyError as exc:
            raise ValueError(f"telemetry missing field {exc}") from None



@dataclass
class VoiceoverTake:
    """One imported narration take, placed on the OUTPUT timeline.

    ``file`` is a wav/m4a/mp3 (a phone voice memo is fine); relative
    paths resolve beside the project file at load, like
    ``source_video``.  ``start`` is in OUTPUT seconds — the rendered
    clip's own clock, freeze intro included — because a take is
    recorded against the finished cut, and the mix, the ducking and
    the captions all live on that clock.  ``gain_db`` is a per-take
    trim applied before the mix.
    """

    file: str
    start: float
    gain_db: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.file, str) or not self.file.strip():
            raise ValueError(
                f"voiceover take file must be a non-empty string, got {self.file!r}"
            )
        self.start = _num("voiceover take.start", self.start, 0.0, 1e6)
        self.gain_db = _num("voiceover take.gain_db", self.gain_db, -40.0, 20.0)

    def to_dict(self) -> dict:
        out = {"file": self.file, "start": self.start}
        if self.gain_db:
            out["gain_db"] = self.gain_db
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceoverTake":
        if not isinstance(data, dict):
            raise ValueError(f"voiceover take must be an object, got {data!r}")
        try:
            return cls(
                file=data["file"],
                start=data["start"],
                gain_db=data.get("gain_db", 0.0),
            )
        except KeyError as exc:
            raise ValueError(f"voiceover take missing field {exc}") from None


@dataclass
class VoiceoverSettings:
    """Narration mix settings (spec Feature 3).

    While a take speaks, the game audio ducks ``duck_db`` below it;
    the final mix is loudness-normalized to ``target_lufs``.
    """

    takes: List[VoiceoverTake] = field(default_factory=list)
    duck_db: float = 12.0
    target_lufs: float = -16.0

    def __post_init__(self) -> None:
        self.duck_db = _num("voiceover.duck_db", self.duck_db, 0.0, 40.0)
        self.target_lufs = _num("voiceover.target_lufs", self.target_lufs, -40.0, -5.0)
        starts = [t.start for t in self.takes]
        if any(b < a for a, b in zip(starts, starts[1:])):
            raise ValueError("voiceover takes must be ordered by start")

    def to_dict(self) -> dict:
        return {
            "duck_db": self.duck_db,
            "target_lufs": self.target_lufs,
            "takes": [t.to_dict() for t in self.takes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceoverSettings":
        if not isinstance(data, dict):
            raise ValueError(f"voiceover must be an object, got {data!r}")
        return cls(
            takes=[VoiceoverTake.from_dict(t) for t in data.get("takes", [])],
            duck_db=data.get("duck_db", 12.0),
            target_lufs=data.get("target_lufs", -16.0),
        )


@dataclass
class CaptionCue:
    """One caption, on the OUTPUT timeline (the clock of the VO take
    it was transcribed from).  ``text`` may carry newlines from the
    human edit pass; the renderer re-wraps to at most two lines."""

    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        self.start = _num("caption.start", self.start, 0.0, 1e6)
        self.end = _num("caption.end", self.end, 0.0, 1e6)
        if self.end <= self.start:
            raise ValueError(
                f"caption end ({self.end}) must be after start ({self.start})"
            )
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(f"caption text must be a non-empty string, got {self.text!r}")
        self.text = self.text.strip()

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict) -> "CaptionCue":
        if not isinstance(data, dict):
            raise ValueError(f"caption must be an object, got {data!r}")
        try:
            return cls(start=data["start"], end=data["end"], text=data["text"])
        except KeyError as exc:
            raise ValueError(f"caption missing field {exc}") from None


@dataclass
class Callout:
    """A text callout with a leader arrow (spec Feature 5).

    Shown while the SOURCE clock is inside [start, end]; the arrow
    points at the position of keyframe ``keyframe`` (an index into
    the project's keyframes) — the annotated moment of the play.
    """

    text: str
    start: float
    end: float
    keyframe: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(f"callout text must be a non-empty string, got {self.text!r}")
        self.text = self.text.strip()
        self.start = _num("callout.start", self.start, 0.0, 1e9)
        self.end = _num("callout.end", self.end, 0.0, 1e9)
        if self.end <= self.start:
            raise ValueError(
                f"callout end ({self.end}) must be after start ({self.start})"
            )
        if int(self.keyframe) != self.keyframe or int(self.keyframe) < 0:
            raise ValueError(
                f"callout keyframe must be a non-negative int index, got {self.keyframe!r}"
            )
        self.keyframe = int(self.keyframe)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "keyframe": self.keyframe,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Callout":
        if not isinstance(data, dict):
            raise ValueError(f"callout must be an object, got {data!r}")
        try:
            return cls(
                text=data["text"],
                start=data["start"],
                end=data["end"],
                keyframe=data["keyframe"],
            )
        except KeyError as exc:
            raise ValueError(f"callout missing field {exc}") from None


BEAT_SLOWMO = "slowmo"
BEAT_FREEZE = "freeze"
MIN_SLOWMO_RATE = 0.25
MAX_FREEZE_S = 5.0


@dataclass
class Beat:
    """An editorial beat on the SOURCE timeline (spec Feature 5).

    kind ``slowmo``: source [start, end] plays at ``rate`` (0.5x by
    default).  kind ``freeze``: playback holds the frame at ``start``
    for ``duration`` output seconds, then resumes from the same
    instant (``end`` mirrors ``start``; serialized as ``at``).
    """

    kind: str
    start: float
    end: float = 0.0
    rate: float = 0.5
    duration: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in (BEAT_SLOWMO, BEAT_FREEZE):
            raise ValueError(
                f"beat kind must be 'slowmo' or 'freeze', got {self.kind!r}"
            )
        self.start = _num("beat.start", self.start, 0.0, 1e9)
        if self.kind == BEAT_SLOWMO:
            self.end = _num("beat.end", self.end, 0.0, 1e9)
            if self.end <= self.start:
                raise ValueError(
                    f"slowmo beat end ({self.end}) must be after start ({self.start})"
                )
            self.rate = _num("beat.rate", self.rate, MIN_SLOWMO_RATE, 1.0)
        else:
            self.end = self.start
            self.duration = _num("beat.duration", self.duration, 0.05, MAX_FREEZE_S)

    def to_dict(self) -> dict:
        if self.kind == BEAT_SLOWMO:
            return {
                "kind": self.kind,
                "start": self.start,
                "end": self.end,
                "rate": self.rate,
            }
        return {"kind": self.kind, "at": self.start, "duration": self.duration}

    @classmethod
    def from_dict(cls, data: dict) -> "Beat":
        if not isinstance(data, dict):
            raise ValueError(f"beat must be an object, got {data!r}")
        kind = data.get("kind")
        try:
            if kind == BEAT_SLOWMO:
                return cls(
                    kind=kind,
                    start=data["start"],
                    end=data["end"],
                    rate=data.get("rate", 0.5),
                )
            if kind == BEAT_FREEZE:
                return cls(kind=kind, start=data["at"], duration=data.get("duration", 1.0))
        except KeyError as exc:
            raise ValueError(f"beat missing field {exc}") from None
        raise ValueError(f"beat kind must be 'slowmo' or 'freeze', got {kind!r}")


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
    telemetry: Optional[TelemetrySettings] = None
    voiceover: Optional[VoiceoverSettings] = None
    captions: List[CaptionCue] = field(default_factory=list)
    callouts: List[Callout] = field(default_factory=list)
    beats: List[Beat] = field(default_factory=list)

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
        for callout in self.callouts:
            if callout.keyframe >= len(self.keyframes):
                raise ValueError(
                    f"callout keyframe index {callout.keyframe} out of range "
                    f"({len(self.keyframes)} keyframes)"
                )
            if not (self.window.start <= callout.start and callout.end <= self.window.end):
                raise ValueError(
                    f"callout [{callout.start}, {callout.end}] lies outside the "
                    f"clip window [{self.window.start}, {self.window.end}]"
                )
        last_beat_start = None
        last_slowmo_end = None
        for beat in self.beats:
            if not (self.window.start <= beat.start and beat.end <= self.window.end):
                raise ValueError(
                    f"beat at {beat.start} lies outside the clip window "
                    f"[{self.window.start}, {self.window.end}]"
                )
            if last_beat_start is not None and beat.start <= last_beat_start:
                raise ValueError("beats must have strictly increasing start times")
            if last_slowmo_end is not None and beat.start < last_slowmo_end:
                raise ValueError("beats must not overlap a slow-mo segment")
            if beat.kind == BEAT_SLOWMO:
                last_slowmo_end = beat.end
            last_beat_start = beat.start

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
        out = {
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
        if self.telemetry is not None:
            out["telemetry"] = self.telemetry.to_dict()
        if self.voiceover is not None:
            out["voiceover"] = self.voiceover.to_dict()
        if self.captions:
            out["captions"] = [c.to_dict() for c in self.captions]
        if self.callouts:
            out["callouts"] = [c.to_dict() for c in self.callouts]
        if self.beats:
            out["beats"] = [b.to_dict() for b in self.beats]
        return out

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
        telemetry_raw = data.get("telemetry")
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
            telemetry=(
                TelemetrySettings.from_dict(telemetry_raw)
                if telemetry_raw is not None
                else None
            ),
            voiceover=(
                VoiceoverSettings.from_dict(data["voiceover"])
                if data.get("voiceover") is not None
                else None
            ),
            captions=[CaptionCue.from_dict(c) for c in data.get("captions", [])],
            callouts=[Callout.from_dict(c) for c in data.get("callouts", [])],
            beats=[Beat.from_dict(b) for b in data.get("beats", [])],
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
    project file is resolved to that absolute path; the telemetry
    ``track_file`` gets the same treatment.
    """
    src = Path(path)
    data = json.loads(src.read_text(encoding="utf-8"))
    project = HighlightProject.from_dict(data)
    video = Path(project.source_video)
    if not video.is_absolute():
        beside = src.resolve().parent / video
        if beside.exists():
            project.source_video = str(beside)
    if project.telemetry is not None:
        track = Path(project.telemetry.track_file)
        if not track.is_absolute():
            beside = src.resolve().parent / track
            if beside.exists():
                project.telemetry.track_file = str(beside)
    if project.voiceover is not None:
        for take in project.voiceover.takes:
            take_file = Path(take.file)
            if not take_file.is_absolute():
                beside = src.resolve().parent / take_file
                if beside.exists():
                    take.file = str(beside)
    return project
