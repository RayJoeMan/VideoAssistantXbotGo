"""Falcon Player marker bridge — export our moments as ``.mark.fp`` files.

TekScene's Falcon Player (a free web player for FALCON footage) keeps
user markers in a JSON file it calls ``<stem>.mark.fp``, stored in a
``.data`` subfolder beside the video.  This module writes files in that
format from our own detections — tracked-detector events and no-track
nominations — so a coach can open a game in the player and jump
straight to every moment we found.  The implementation here is ours;
only the file-format facts below were taken from the player's public
page (they are the interop contract, listed so a format change in a
future player version is easy to spot):

Format contract (Falcon Player, as of 2026-10):
  * Path: ``<video folder>/.data/<stem>.mark.fp`` where ``stem`` is the
    video file name minus its ``.mp4`` extension, and minus a trailing
    ``.h264`` as well (a converted ``<stem>.h264.mp4`` copy shares the
    original recording's stem).
  * Content: a UTF-8 JSON array, pretty-printed with a 2-space indent
    (``JSON.stringify(markers, null, 2)``), sorted by time ascending.
  * Entry: an object with ``"type"`` (string) and ``"time"`` (video
    seconds, number).  The player rounds times it creates to 3 decimal
    places.  It reads only ``type``/``time`` and preserves any extra
    fields verbatim when it re-saves the file.
  * Camera markers use types ``"click"`` and ``"start"`` and live in a
    sibling ``<stem>.mark`` file (same JSON shape, in ``.data``).
  * Player-defined user types are ``"fp_marker"``, ``"fp_home_score"``
    and ``"fp_away_score"``.  Any type beginning ``fp_`` is treated as
    a user marker: it joins prev/next navigation and is drawn on the
    timeline (unregistered codes get the default light-gray tick).
  * If a ``.mark.fp`` exists it is the player's source of truth and
    shadows the camera ``.mark`` entirely — so this writer merges the
    camera markers into the file it writes, exactly as the player's
    own first save does.

Our type codes (all ``fp_`` user markers):
  detector events -> ``fp_goal``, ``fp_shot``, ``fp_save``,
  ``fp_faceoff``, ``fp_transition``, ``fp_turnover``, ``fp_penalty``,
  ``fp_timeout`` (anything else -> ``fp_event``); nominations ->
  ``fp_nomination``.  We deliberately never emit the score types: the
  player derives a running score from their counts, and we have no
  home/away attribution for our detections.  Each of our entries also
  carries ``label`` and ``score`` extras (and ``start``/``end`` for
  nominations) — ignored by the player, handy for a human reading the
  file, and preserved across player re-saves.

Times handed to this module must already be VIDEO seconds.  Detector
events are born in track time; map them through
``telemetry.video_sync`` first (``scripts/event_review.py markers``
does).  Nominations are natively in video seconds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Union

# The player's own add-marker rule: a new user marker is refused when a
# marker of the same type already sits within half a second.  Merging
# with the same window keeps bridge re-runs idempotent instead of
# piling up near-duplicate ticks.
SAME_TYPE_WINDOW_SEC = 0.5

CAMERA_MARKER_TYPES = ("click", "start")

EVENT_TYPE_CODES = {
    "goal": "fp_goal",
    "shot": "fp_shot",
    "save": "fp_save",
    "face_off": "fp_faceoff",
    "transition": "fp_transition",
    "turnover": "fp_turnover",
    "penalty": "fp_penalty",
    "timeout": "fp_timeout",
}
NOMINATION_CODE = "fp_nomination"
FALLBACK_EVENT_CODE = "fp_event"


# ══════════════════════════════════════════════════════════════════════
# Paths and stems
# ══════════════════════════════════════════════════════════════════════

def marker_stem(video_name: str) -> str:
    """The player's stem rule for a video file name.

    Strips a trailing ``.mp4`` (any case), then a trailing ``.h264``
    (any case) — a converted copy shares the original's stem.
    """
    stem = video_name
    if stem.lower().endswith(".mp4"):
        stem = stem[: -len(".mp4")]
    if stem.lower().endswith(".h264"):
        stem = stem[: -len(".h264")]
    return stem


def mark_fp_path(video_path: Union[Path, str]) -> Path:
    """Where the player's marker file for this video lives."""
    video_path = Path(video_path)
    return video_path.parent / ".data" / (marker_stem(video_path.name) + ".mark.fp")


def camera_mark_path(video_path: Union[Path, str]) -> Optional[Path]:
    """Locate the camera ``.mark`` for a video, or None.

    FALCON keeps telemetry in the ``.data`` subfolder; a loose copy
    beside the video is accepted as a fallback.
    """
    video_path = Path(video_path)
    stem = marker_stem(video_path.name)
    for candidate in (
        video_path.parent / ".data" / (stem + ".mark"),
        video_path.parent / (stem + ".mark"),
    ):
        if candidate.exists():
            return candidate
    return None


# ══════════════════════════════════════════════════════════════════════
# Parsing and serialization (the interop surface)
# ══════════════════════════════════════════════════════════════════════

def parse_markers(text: str) -> List[dict]:
    """Parse marker-file content per the format contract.

    Returns the entries as dicts (extra fields preserved).  Raises
    ValueError on anything that is not a JSON array of
    ``{"type": str, "time": number}`` objects.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"marker file is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("marker file must be a JSON array")
    markers = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"marker {i} is not an object")
        mtype = entry.get("type")
        mtime = entry.get("time")
        if not isinstance(mtype, str) or not mtype:
            raise ValueError(f"marker {i} has no string 'type'")
        if isinstance(mtime, bool) or not isinstance(mtime, (int, float)):
            raise ValueError(f"marker {i} has no numeric 'time'")
        markers.append(dict(entry))
    return markers


def load_marker_file(path: Union[Path, str]) -> List[dict]:
    """Read and parse a ``.mark`` / ``.mark.fp`` file."""
    return parse_markers(Path(path).read_text(encoding="utf-8"))


def _js_number(value: float) -> Union[int, float]:
    """Match JSON.stringify's number rendering: integral floats print
    without a fraction (``12`` not ``12.0``); other values round-trip
    through Python's shortest-repr, which agrees with JS formatting
    for the magnitudes a video timestamp takes."""
    value = round(float(value), 3)
    if value == int(value) and abs(value) < 1e15:
        return int(value)
    return value


def serialize_markers(markers: Iterable[dict]) -> str:
    """Render markers exactly as the player writes them: entries
    sorted by time, 2-space-indented JSON, core fields first."""
    ordered = sorted(markers, key=lambda m: float(m["time"]))
    rendered = []
    for m in ordered:
        entry = {"type": m["type"], "time": _js_number(m["time"])}
        for key, value in m.items():
            if key not in entry:
                entry[key] = value
        rendered.append(entry)
    return json.dumps(rendered, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
# Converting our moments to markers
# ══════════════════════════════════════════════════════════════════════

def _marker(code: str, time_sec: float, label: str = "",
            score: Optional[float] = None, **extra) -> dict:
    entry = {"type": code, "time": _js_number(max(float(time_sec), 0.0))}
    if label:
        entry["label"] = label
    if score is not None:
        entry["score"] = round(float(score), 3)
    entry.update(extra)
    return entry


def event_to_marker(event) -> dict:
    """One tracked-detector event -> one marker at its peak time.

    Accepts a ``telemetry.models.Event`` (or anything with
    ``event_type`` / ``peak_time_sec`` / ``confidence`` attributes).
    The event must already be in VIDEO time — see module docstring.
    """
    raw_type = getattr(event, "event_type", None)
    type_name = getattr(raw_type, "value", raw_type) or "unknown"
    code = EVENT_TYPE_CODES.get(str(type_name), FALLBACK_EVENT_CODE)
    label = getattr(event, "description", "") or str(type_name).replace("_", " ")
    return _marker(
        code,
        getattr(event, "peak_time_sec"),
        label=label,
        score=getattr(event, "confidence", None),
    )


def nomination_to_marker(nomination) -> dict:
    """One no-track nomination -> one ``fp_nomination`` marker at its
    peak.  Accepts the dict form from ``Nomination.to_dict()`` or a
    ``Nomination`` object."""
    if isinstance(nomination, dict):
        peak = nomination["peak_sec"]
        start = nomination.get("start_sec")
        end = nomination.get("end_sec")
        reasons = nomination.get("reasons") or []
        score = nomination.get("score")
    else:
        peak = nomination.peak_sec
        start = nomination.start_sec
        end = nomination.end_sec
        reasons = nomination.reasons
        score = nomination.score
    label = "nomination"
    if reasons:
        label += ": " + ", ".join(str(r) for r in reasons)
    extra = {}
    if start is not None:
        extra["start"] = _js_number(start)
    if end is not None:
        extra["end"] = _js_number(end)
    return _marker(NOMINATION_CODE, peak, label=label, score=score, **extra)


def markers_from_events(events: Iterable) -> List[dict]:
    return [event_to_marker(e) for e in events]


def markers_from_nominations(nominations: Iterable) -> List[dict]:
    return [nomination_to_marker(n) for n in nominations]


# ══════════════════════════════════════════════════════════════════════
# Merging and writing
# ══════════════════════════════════════════════════════════════════════

def merge_markers(base: Iterable[dict], new: Iterable[dict]) -> List[dict]:
    """Union of two marker sets, sorted by time.

    A new marker is dropped when an existing one has the same type
    within ``SAME_TYPE_WINDOW_SEC`` — the player's own duplicate rule,
    which also makes re-running the bridge idempotent.
    """
    merged = [dict(m) for m in base]
    for candidate in new:
        ctype, ctime = candidate["type"], float(candidate["time"])
        duplicate = any(
            m["type"] == ctype and abs(float(m["time"]) - ctime) < SAME_TYPE_WINDOW_SEC
            for m in merged
        )
        if not duplicate:
            merged.append(dict(candidate))
    return sorted(merged, key=lambda m: float(m["time"]))


def write_mark_fp(video_path: Union[Path, str], new_markers: Iterable[dict],
                  *, merge_camera: bool = True) -> Path:
    """Write ``new_markers`` into the video's ``.mark.fp`` file.

    The file is a source of truth that shadows the camera ``.mark``,
    so the base set is: the existing ``.mark.fp`` if there is one,
    else the camera markers (when ``merge_camera``), else empty.
    New markers merge in under the duplicate rule.  Creates the
    ``.data`` folder if needed.  Returns the file path.
    """
    video_path = Path(video_path)
    target = mark_fp_path(video_path)
    if target.exists():
        base = load_marker_file(target)
    elif merge_camera:
        cam = camera_mark_path(video_path)
        base = load_marker_file(cam) if cam is not None else []
    else:
        base = []
    merged = merge_markers(base, list(new_markers))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_markers(merged), encoding="utf-8")
    return target
