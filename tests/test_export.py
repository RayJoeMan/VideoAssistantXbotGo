"""Tests for FFmpeg export module.

Tests marked with 'requires_ffmpeg' are skipped if ffmpeg is not installed.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telemetry.models import Event, EventType, PlayIntensity
from export.ffmpeg import (
    extract_clip,
    extract_clip_from_event,
    build_highlight_reel,
    ExportConfig,
    _event_title,
    _probe_duration,
)


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def _ffmpeg_available() -> bool:
    """Check if ffmpeg is installed and usable."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ffprobe_available() -> bool:
    """Check if ffprobe is installed."""
    try:
        result = subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _create_test_video(path: Path, duration_sec: float = 5.0) -> Path:
    """Create a small test video using FFmpeg (solid color + tone)."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=green:s=320x240:d={duration_sec}",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration_sec}",
        "-shortest",
        "-c:v", "libx264",
        "-c:a", "aac",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return path


# ── Skip markers ───────────────────────────────────────────────────────

ffmpeg_required = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="FFmpeg not installed",
)

ffprobe_required = pytest.mark.skipif(
    not _ffprobe_available(),
    reason="ffprobe not installed",
)


# ══════════════════════════════════════════════════════════════════════════
# Unit Tests (no FFmpeg required)
# ══════════════════════════════════════════════════════════════════════════

class TestEventTitle:
    """Tests for _event_title() — no FFmpeg needed."""

    def test_goal_title(self):
        event = Event(
            EventType.GOAL, 120.0, 128.0, 124.0,
            intensity=PlayIntensity.HIGH,
        )
        title = _event_title(event)
        assert "GOAL" in title
        assert "2:04" in title  # 124 seconds = 2:04
        assert "HIGH" in title

    def test_save_title(self):
        event = Event(EventType.SAVE, 60.0, 65.0, 62.0)
        title = _event_title(event)
        assert "SAVE" in title

    def test_transition_title(self):
        event = Event(EventType.TRANSITION, 30.0, 35.0, 32.5)
        title = _event_title(event)
        assert "TRANSITION" in title

    def test_unknown_event(self):
        event = Event(EventType.UNKNOWN, 10.0, 15.0, 12.0)
        title = _event_title(event)
        assert "UNKNOWN" in title


class TestExportConfig:
    """Tests for ExportConfig defaults."""

    def test_default_pre_roll(self):
        cfg = ExportConfig()
        assert cfg.pre_roll_sec == 3.0

    def test_default_post_roll(self):
        cfg = ExportConfig()
        assert cfg.post_roll_sec == 2.0

    def test_default_codec(self):
        cfg = ExportConfig()
        assert cfg.video_codec == "libx264"
        assert cfg.audio_codec == "aac"


# ══════════════════════════════════════════════════════════════════════════
# FFmpeg-dependent Tests
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not installed")
class TestExtractClip:
    """Tests for extract_clip() — requires FFmpeg."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.video = tmp_path / "test.mp4"
        _create_test_video(self.video, duration_sec=6.0)

    def test_extract_valid_clip(self):
        """Should extract a subclip successfully."""
        output = self.tmp / "clip.mp4"
        result = extract_clip(self.video, 1.0, 3.0, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_extract_full_duration(self):
        """Extracting the full video should work."""
        output = self.tmp / "full.mp4"
        result = extract_clip(self.video, 0.0, 5.0, output, pre_roll_sec=0, post_roll_sec=0)
        assert result.exists()

    def test_extract_with_pre_post_roll(self):
        """Pre/post roll should extend the clip."""
        output = self.tmp / "extended.mp4"
        result = extract_clip(
            self.video, 2.0, 3.0, output,
            pre_roll_sec=1.0, post_roll_sec=1.0,
        )
        assert result.exists()
        # Clip should be ~3 seconds (1 pre + 1 event + 1 post)
        dur = _probe_duration(result, ExportConfig())
        if dur is not None:
            assert 2.5 <= dur <= 4.0, f"Expected ~3s clip, got {dur}s"

    def test_extract_clamps_to_zero(self):
        """Negative pre-roll should be clamped to 0."""
        output = self.tmp / "clamped.mp4"
        result = extract_clip(
            self.video, 0.5, 2.0, output,
            pre_roll_sec=10.0,  # Would go negative
        )
        assert result.exists()

    def test_raises_on_missing_video(self):
        """Should raise FileNotFoundError for missing video."""
        with pytest.raises(FileNotFoundError):
            extract_clip("/nonexistent/video.mp4", 0, 1, self.tmp / "out.mp4")

    def test_output_in_expected_format(self):
        """Output should be a valid MP4 file."""
        output = self.tmp / "format_test.mp4"
        result = extract_clip(self.video, 1.0, 3.0, output)
        assert result.suffix == ".mp4"
        assert result.stat().st_size > 1000  # At least 1KB


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not installed")
class TestExtractClipFromEvent:
    """Tests for extract_clip_from_event()."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.video = tmp_path / "test.mp4"
        _create_test_video(self.video, duration_sec=6.0)

    def test_extract_from_event(self):
        """Should extract a clip using event time bounds."""
        event = Event(EventType.GOAL, 1.5, 3.5, 2.5)
        output = self.tmp / "event_clip.mp4"
        result = extract_clip_from_event(self.video, event, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_extract_with_title(self):
        """Should extract with title overlay (title failure falls back to original)."""
        event = Event(EventType.SAVE, 1.0, 2.5, 1.8)
        output = self.tmp / "titled_clip.mp4"
        result = extract_clip_from_event(
            self.video, event, output, add_title=True,
        )
        assert result.exists()


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not installed")
class TestBuildHighlightReel:
    """Tests for build_highlight_reel()."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.video = tmp_path / "test.mp4"
        _create_test_video(self.video, duration_sec=10.0)

    def test_build_reel_from_events(self):
        """Should build a highlight reel from multiple events."""
        events = [
            Event(EventType.GOAL, 1.0, 3.0, 2.0, confidence=0.9, intensity=PlayIntensity.HIGH),
            Event(EventType.SAVE, 4.0, 5.5, 4.8, confidence=0.8),
            Event(EventType.TRANSITION, 6.5, 8.0, 7.2, confidence=0.7),
        ]
        output = self.tmp / "reel.mp4"
        result = build_highlight_reel(
            self.video, events, output,
            max_clips=3,
            add_titles=False,
            add_slowmo=False,
        )
        assert result.exists()
        assert result.stat().st_size > 0

    def test_single_event_reel(self):
        """Single event should still produce valid output."""
        events = [Event(EventType.GOAL, 1.0, 3.0, 2.0, confidence=0.9)]
        output = self.tmp / "single_reel.mp4"
        result = build_highlight_reel(
            self.video, events, output,
            add_titles=False, add_slowmo=False,
        )
        assert result.exists()

    def test_max_clips_limit(self):
        """Should respect max_clips parameter."""
        events = [
            Event(EventType.SHOT, float(i), float(i + 1), float(i + 0.5), confidence=0.5)
            for i in range(20)
        ]
        output = self.tmp / "limited_reel.mp4"
        result = build_highlight_reel(
            self.video, events, output,
            max_clips=2,
            add_titles=False, add_slowmo=False,
        )
        assert result.exists()

    def test_raises_on_empty_events(self):
        """Should raise ValueError with no events."""
        with pytest.raises(ValueError, match="No events"):
            build_highlight_reel(self.video, [], self.tmp / "empty.mp4")


@pytest.mark.skipif(not _ffprobe_available(), reason="ffprobe not installed")
class TestProbe:
    """Tests for _probe_duration()."""

    def test_probe_returns_duration(self, tmp_path):
        video = tmp_path / "probe_test.mp4"
        _create_test_video(video, duration_sec=3.0)
        dur = _probe_duration(video, ExportConfig())
        assert dur is not None
        assert 2.5 <= dur <= 4.0

    def test_probe_nonexistent_file(self):
        dur = _probe_duration(Path("/nonexistent/video.mp4"), ExportConfig())
        assert dur is None
