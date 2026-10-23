"""
Track-Time ↔ Video-Time Synchronization

FALCON recordings do not start the telemetry clock and the video file
at the same instant, and the telemetry clock keeps running through
recording pauses (halftime) that the video file omits. Event times are
therefore NOT video times: on a calibrated game (2026-06-14) the video
started 47.2s before tracking, and a 191.2s halftime gap meant second-
half events sat a further ~3 minutes away from their video position.
Exporting clips at raw track times cuts the wrong play.

The mapping needs three facts, all recorded at parse/export time:
  - the track's wall-clock start (ParsedTrack.start_utc)
  - the video's wall-clock start (the .vdata sidecar's file_time)
  - the track's recording gaps (ParsedTrack.gaps)

    video_t = track_t + (track_start - video_start)
              - sum of gap durations fully before track_t

Usage:
    from telemetry.parser import parse_track_file
    from telemetry.video_sync import sync_for

    track = parse_track_file("game.track")
    sync = sync_for(track, "game.mp4")      # None if no .vdata found
    if sync:
        event = sync.map_event(event)       # copy with video times
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from .logging_setup import get_logger
from .models import Event
from .parser import ParsedTrack

log = get_logger(__name__)


def read_vdata(video_path: Path | str) -> Optional[dict]:
    """Read the FALCON .vdata sidecar for a video file, if present.

    FALCON keeps it in a `.data` subfolder next to the video, sharing
    the video's stem:  game.mp4 -> .data/game.vdata
    """
    video = Path(video_path)
    candidates = [
        video.parent / ".data" / (video.stem + ".vdata"),
        video.parent / (video.stem + ".vdata"),
    ]
    for cand in candidates:
        if cand.exists():
            try:
                # Real FALCON .vdata files can be NUL-terminated; strip
                # trailing NULs/whitespace before parsing.
                return json.loads(cand.read_text().rstrip("\x00 \t\r\n"))
            except (ValueError, OSError) as exc:
                log.warning(f"unreadable vdata {cand}: {exc}")
                return None
    return None


def video_start_time(video_path: Path | str) -> Optional[datetime]:
    """The video file's wall-clock start from its .vdata sidecar."""
    data = read_vdata(video_path)
    if not data:
        return None
    raw = data.get("file_time")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    log.warning(f"unparseable vdata file_time: {raw!r}")
    return None


@dataclass
class TrackVideoSync:
    """Converts track-relative seconds to video-file seconds."""

    track: ParsedTrack
    video_start: datetime

    @property
    def head_offset_sec(self) -> float:
        """Seconds the video ran before tracking started (can be < 0)."""
        if self.track.start_utc is None:
            return 0.0
        return (self.track.start_utc - self.video_start).total_seconds()

    def to_video_time(self, track_t: float) -> float:
        """Map one track timestamp to its position in the video file."""
        vt = track_t + self.head_offset_sec
        for gap_start, gap_end in self.track.gaps:
            if track_t >= gap_end:
                vt -= gap_end - gap_start
            elif track_t > gap_start:
                # Inside a gap there is no video; clamp to the moment
                # recording paused.
                vt -= track_t - gap_start
        return max(vt, 0.0)

    def map_event(self, event: Event) -> Event:
        """A copy of the event with start/peak/end in video time."""
        return replace(
            event,
            start_time_sec=self.to_video_time(event.start_time_sec),
            end_time_sec=self.to_video_time(event.end_time_sec),
            peak_time_sec=self.to_video_time(event.peak_time_sec),
        )


def sync_for(
    track: ParsedTrack,
    video_path: Path | str,
) -> Optional[TrackVideoSync]:
    """Build a sync for a track/video pair, or None if it can't be made.

    Returns None when the track has no wall-clock start or the video
    has no readable .vdata — callers should warn, because raw track
    times will then be used and clips may be offset.
    """
    if track.start_utc is None:
        log.warning("track has no start UTC; cannot sync to video")
        return None
    start = video_start_time(video_path)
    if start is None:
        return None
    sync = TrackVideoSync(track=track, video_start=start)
    log.info(
        "video sync: head offset %.1fs, %d gap(s) totalling %.1fs",
        sync.head_offset_sec,
        len(track.gaps),
        sum(ge - gs for gs, ge in track.gaps),
    )
    return sync
