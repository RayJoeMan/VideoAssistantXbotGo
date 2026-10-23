"""Tests for track-time <-> video-time synchronization."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telemetry.models import Event, EventType, GameMetadata, TrackPoint
from telemetry.parser import ParsedTrack
from telemetry.video_sync import TrackVideoSync, sync_for, video_start_time


def _track() -> ParsedTrack:
    """A track that starts 47.2s after its video, with a halftime gap."""
    points = [
        TrackPoint(frame_num=1, timestamp_sec=0.0),
        TrackPoint(frame_num=2, timestamp_sec=1500.0),
    ]
    return ParsedTrack(
        points=points,
        metadata=GameMetadata(),
        start_utc=datetime(2026, 6, 14, 12, 59, 57, 214000),
        gaps=[(1217.2, 1408.3)],
    )


def test_head_offset_applies_before_gap():
    sync = TrackVideoSync(_track(), datetime(2026, 6, 14, 12, 59, 10))
    # Track starts at 12:59:57.214, video at 12:59:10 -> offset +47.214s
    assert abs(sync.to_video_time(100.0) - 147.214) < 0.01


def test_gap_is_removed_after_halftime():
    sync = TrackVideoSync(_track(), datetime(2026, 6, 14, 12, 59, 10))
    # Gap is 1408.3 - 1217.2 = 191.1s: 1500 + 47.214 - 191.1 = 1356.114
    assert abs(sync.to_video_time(1500.0) - 1356.114) < 0.01


def test_map_event_shifts_all_times():
    sync = TrackVideoSync(_track(), datetime(2026, 6, 14, 12, 59, 10))
    ev = Event(EventType.SHOT, 1490.0, 1510.0, 1500.0)
    mapped = sync.map_event(ev)
    assert abs(mapped.peak_time_sec - 1356.114) < 0.01
    assert mapped.start_time_sec < mapped.peak_time_sec < mapped.end_time_sec
    # Original is untouched
    assert ev.peak_time_sec == 1500.0


def test_sync_for_reads_vdata(tmp_path):
    video = tmp_path / "game.mp4"
    video.write_bytes(b"")
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    (data_dir / "game.vdata").write_text(json.dumps({
        "file_name": "game.mp4",
        "file_time": "2026-06-14 12:59:10",
        "duration": 2908.9,
    }))
    assert video_start_time(video) == datetime(2026, 6, 14, 12, 59, 10)
    sync = sync_for(_track(), video)
    assert sync is not None
    assert abs(sync.head_offset_sec - 47.214) < 0.01


def test_sync_for_missing_vdata_returns_none(tmp_path):
    video = tmp_path / "game.mp4"
    video.write_bytes(b"")
    assert sync_for(_track(), video) is None
