"""Tests for FALCON .track file parser."""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telemetry.parser import parse_track_file
from telemetry.models import TrackPoint, GameMetadata, ActivityWindow


# ══════════════════════════════════════════════════════════════════════════
# Sample track data (synthesized from FALCON SDK V1.2.0 format)
# ══════════════════════════════════════════════════════════════════════════

SAMPLE_TRACK_HEADER = """\
SDKV1.2.0-RGJK-Type15
Sensor: FALCON-AI-FC1
Lacrosse yawLim45.0 areaTH500 pitchInit5.0
Gear:TELE Drive:5Hz

"""


def _make_frame_block(
    frame_num: int,
    timestamp_str: str,
    fast_level: int = 0,
    filter_p: int = 0,
    mot: int = 0,
    crowd_x: float = 0.0,
    fin_v: float = 0.0,
    center_x: float = 0.0,
    fps: int = 30,
    zoom: int = 1,
    yaw: float = 0.0,
    pitch: float = 0.0,
) -> str:
    """Build a single frame block in FALCON .track format."""
    lines = [
        f"UTC{timestamp_str}",
        f"Frame{frame_num} SZ{zoom} Yaw{yaw} Pit{pitch} fps{fps}",
    ]
    if filter_p > 0 or mot > 0:
        lines.append(f"AFilterP{filter_p} mot{mot}")
    
    # Deque with 3 tracked objects (placeholder)
    lines.append(f"Deque3(V0.0,x0.0)(V0.0,x0.0)(V0.0,x0.0)")
    lines.append(f"Fast{fast_level}")
    
    if crowd_x != 0.0:
        lines.append(f"Crowdx{crowd_x}")
    
    lines.append(f"FIN:x{center_x} V{fin_v}")
    lines.append(f"centerResX{center_x}")
    lines.append(f"Zoom:CPSz{zoom}")
    lines.append("")
    
    return "\n".join(lines)


def build_sample_track(*, num_frames: int = 300, include_active: bool = True) -> str:
    """Build a complete .track file as a string.
    
    Args:
        num_frames: Total number of frame blocks (300 = ~10 seconds)
        include_active: Whether to include high-activity frames
    
    Returns:
        String content of a valid .track file
    """
    parts = [SAMPLE_TRACK_HEADER]
    base_time = datetime(2026, 6, 20, 14, 0, 0, 0)
    
    for i in range(num_frames):
        ts = base_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        base_time = datetime.fromtimestamp(base_time.timestamp() + 1.0 / 30.0)
        
        if include_active and 80 <= i <= 160:
            # Active period: shot buildup + attempt (~2.7 seconds, 80 frames)
            # Keep fast >= 2 (activity >= 0.5) throughout for detection
            fast = max(2, min(4, 2 + abs(i - 120) // 20))
            filter_p = 10 + i % 8
            mot = 5 + i % 4
            crowd = 200.0 + (i - 80) * 2
            fin_v = 30.0 + abs(i - 120) * 1.5
            center = 500.0 + (i - 120) * 5
        elif include_active and 220 <= i <= 270:
            # Active period: transition (~1.7 seconds, 50 frames)
            fast = 3
            filter_p = 8
            mot = 4
            crowd = -100.0
            fin_v = 80.0
            center = 300.0
        else:
            # Inactive period
            fast = 0 if i % 3 != 0 else 1
            filter_p = 0 if i % 2 == 0 else 3
            mot = 0
            crowd = 0.0
            fin_v = 0.0
            center = 0.0
        
        block = _make_frame_block(
            frame_num=i + 1,
            timestamp_str=ts,
            fast_level=fast,
            filter_p=filter_p,
            mot=mot,
            crowd_x=crowd,
            fin_v=fin_v,
            center_x=center,
        )
        parts.append(block)
    
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_track_file():
    """Create a temporary .track file for testing."""
    content = build_sample_track(num_frames=300)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".track", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def inactive_track_file():
    """Create a track file with no activity."""
    content = build_sample_track(num_frames=150, include_active=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".track", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def raw_falcon_sample():
    """Return raw FALCON content for format testing."""
    return build_sample_track(num_frames=10)


# ══════════════════════════════════════════════════════════════════════════
# Parsing Tests
# ══════════════════════════════════════════════════════════════════════════

class TestParseTrackFile:
    """Tests for parse_track_file()."""

    def test_parses_valid_file(self, sample_track_file):
        """Should parse a valid .track file without errors."""
        result = parse_track_file(sample_track_file)
        assert result is not None
        assert len(result.points) == 300

    def test_extracts_frame_numbers(self, sample_track_file):
        """Frame numbers should be sequential starting from 1."""
        result = parse_track_file(sample_track_file)
        frame_nums = [p.frame_num for p in result.points]
        assert frame_nums[0] == 1
        assert frame_nums[-1] == 300
        assert frame_nums == list(range(1, 301))

    def test_computes_timestamps(self, sample_track_file):
        """Timestamps should be monotonically increasing."""
        result = parse_track_file(sample_track_file)
        times = [p.timestamp_sec for p in result.points]
        assert times[0] >= 0.0
        assert times[-1] > times[0]
        for i in range(1, len(times)):
            assert times[i] >= times[i - 1], f"Time decreased at index {i}"

    def test_extracts_activity_scores(self, sample_track_file):
        """Activity scores should be normalized 0-1."""
        result = parse_track_file(sample_track_file)
        for p in result.points:
            assert 0.0 <= p.activity_score <= 1.0, \
                f"Activity score {p.activity_score} out of range at frame {p.frame_num}"

    def test_detects_high_activity_frames(self, sample_track_file):
        """Frames 80-160 should have high activity."""
        result = parse_track_file(sample_track_file)
        active_scores = [p.activity_score for p in result.points[79:160]]
        avg_active = sum(active_scores) / len(active_scores)
        assert avg_active > 0.45, f"Expected high activity in frames 80-160, got avg {avg_active:.2f}"

    def test_detects_inactive_frames(self, sample_track_file):
        """First 10 frames should be low activity."""
        result = parse_track_file(sample_track_file)
        inactive_scores = [p.activity_score for p in result.points[:10]]
        avg_inactive = sum(inactive_scores) / len(inactive_scores)
        assert avg_inactive < 0.4, f"Expected low activity in early frames, got avg {avg_inactive:.2f}"

    def test_extracts_metadata(self, sample_track_file):
        """Should extract version and sport metadata."""
        result = parse_track_file(sample_track_file)
        assert "V1.2.0" in result.metadata.track_version
        assert result.metadata.sport == "lacrosse"

    def test_computes_summary(self, sample_track_file):
        """Summary should include aggregate statistics."""
        result = parse_track_file(sample_track_file)
        summary = result.summary
        assert summary is not None
        assert summary.total_frames == 300
        assert summary.duration_sec > 0
        assert summary.activity_pct > 0
        assert summary.avg_objects_per_frame >= 0
        assert summary.max_objects >= 0

    def test_detects_activity_windows(self, sample_track_file):
        """Should detect activity windows in summary."""
        result = parse_track_file(sample_track_file)
        assert result.summary is not None
        windows = result.summary.active_windows
        # We have 2 active periods: frames 40-60 and 80-90
        assert len(windows) >= 1, f"Expected at least 1 activity window, got {len(windows)}"

    def test_raises_on_missing_file(self):
        """Should raise FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            parse_track_file("/nonexistent/path.track")

    def test_raises_on_empty_file(self, tmp_path):
        """Should raise ValueError for file with no frames."""
        empty_file = tmp_path / "empty.track"
        empty_file.write_text("SDKV1.0\n")  # Header but no frames
        with pytest.raises(ValueError, match="No frames found"):
            parse_track_file(empty_file)


class TestInactiveTrack:
    """Tests for tracks with no activity."""

    def test_all_frames_low_activity(self, inactive_track_file):
        """All frames should have near-zero activity."""
        result = parse_track_file(inactive_track_file)
        scores = [p.activity_score for p in result.points]
        avg = sum(scores) / len(scores)
        assert avg < 0.3, f"Expected low activity, got avg {avg:.2f}"

    def test_summary_has_zero_activity(self, inactive_track_file):
        """Summary should show near-zero activity percentage."""
        result = parse_track_file(inactive_track_file)
        assert result.summary is not None
        assert result.summary.activity_pct < 20.0


class TestActivityWindows:
    """Tests for activity window detection."""

    def test_windows_have_valid_bounds(self, sample_track_file):
        """Activity windows should have start < end."""
        result = parse_track_file(sample_track_file)
        for w in result.summary.active_windows:
            assert w.start_time_sec < w.end_time_sec
            assert w.duration_sec > 0
            assert w.frame_count > 0

    def test_windows_are_non_overlapping(self, sample_track_file):
        """Activity windows should not overlap."""
        result = parse_track_file(sample_track_file)
        windows = result.summary.active_windows
        for i in range(len(windows) - 1):
            assert windows[i].end_time_sec <= windows[i + 1].start_time_sec, \
                f"Window {i} overlaps with window {i + 1}"


# ══════════════════════════════════════════════════════════════════════════
# Model Tests
# ══════════════════════════════════════════════════════════════════════════

class TestModels:
    """Tests for domain model dataclasses."""

    def test_track_point_defaults(self):
        """TrackPoint should have sensible defaults."""
        tp = TrackPoint(frame_num=1, timestamp_sec=0.0)
        assert tp.activity_score == 0.0
        assert tp.objects_detected == 0
        assert tp.raw_fields == {}

    def test_activity_window_duration(self):
        """ActivityWindow.duration_sec should be computed correctly."""
        w = ActivityWindow(start_time_sec=10.0, end_time_sec=15.0)
        assert w.duration_sec == 5.0


# ══════════════════════════════════════════════════════════════════════════
# Format Validation Tests
# ══════════════════════════════════════════════════════════════════════════

class TestFormatCompatibility:
    """Tests that the parser handles FALCON format edge cases."""

    def test_handles_ffilterp_variant(self, tmp_path):
        """Should parse FFilterP (older FALCON format) same as AFilterP."""
        content = SAMPLE_TRACK_HEADER + _make_frame_block(
            1, "2026-06-20 14:00:00.000", fast_level=2, filter_p=15, mot=7,
        ).replace("AFilterP", "FFilterP")
        track_file = tmp_path / "ffilter.track"
        track_file.write_text(content)
        
        result = parse_track_file(track_file)
        assert result.points[0].objects_detected == 15
        assert result.points[0].motion_objects == 7

    def test_handles_autocenterx_variant(self, tmp_path):
        """Should parse autoCenterX variant of center position."""
        content = SAMPLE_TRACK_HEADER + _make_frame_block(
            1, "2026-06-20 14:00:00.000", center_x=450.0,
        ).replace("centerResX", "autoCenterX")
        track_file = tmp_path / "autocenter.track"
        track_file.write_text(content)
        
        result = parse_track_file(track_file)
        assert result.points[0].center_x == 450.0

    def test_handles_missing_optional_fields(self, tmp_path):
        """Should not crash on missing optional fields like Crowdx."""
        content = SAMPLE_TRACK_HEADER + _make_frame_block(
            1, "2026-06-20 14:00:00.000", fast_level=1,
        ).replace("Crowdx0.0\n", "")  # Remove Crowdx line
        track_file = tmp_path / "no_crowdx.track"
        track_file.write_text(content)
        
        result = parse_track_file(track_file)
        assert len(result.points) == 1
        assert result.points[0].crowd_x == 0.0  # Default

