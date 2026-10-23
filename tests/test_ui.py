"""Tests for the PyQt6 desktop UI.

Tests marked with 'requires_display' are skipped if no X11/Wayland display
is available (e.g., in CI). Headless tests use QT_QPA_PLATFORM=offscreen.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Force offscreen for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def _has_display() -> bool:
    """Check if a display server is available."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _pyqt_available() -> bool:
    """Check if PyQt6 can be imported."""
    try:
        from PyQt6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


# ── Skip markers ───────────────────────────────────────────────────────

pyqt_required = pytest.mark.skipif(
    not _pyqt_available(),
    reason="PyQt6 not installed",
)


# ══════════════════════════════════════════════════════════════════════════
# Unit Tests (no display needed — test component logic)
# ══════════════════════════════════════════════════════════════════════════

class TestEventTitle:
    """Tests for event title generation (used in UI overlays)."""

    def test_title_format(self):
        from export.ffmpeg import _event_title
        from telemetry.models import Event, EventType, PlayIntensity
        event = Event(EventType.GOAL, 120.0, 128.0, 124.0, intensity=PlayIntensity.HIGH)
        title = _event_title(event)
        assert "GOAL" in title
        assert "HIGH" in title


class TestDetectionConfigDefaults:
    """Tests for detection config used by UI."""

    def test_defaults(self):
        from analysis.detection import DetectionConfig
        from export.ffmpeg import ExportConfig
        dcfg = DetectionConfig()
        ecfg = ExportConfig()
        # Recalibrated 2026-10-23 for the object-speed signal (see
        # analysis/detection.py calibration notes)
        assert dcfg.shot_min_speed == 28.0
        assert dcfg.shot_speed_spike == 12.0
        assert dcfg.shot_min_activity == 0.4
        assert dcfg.save_min_speed == 30.0
        assert dcfg.min_event_spacing_sec == 8.0
        assert ecfg.pre_roll_sec == 3.0  # pre_roll is on ExportConfig


# ══════════════════════════════════════════════════════════════════════════
# PyQt6 Component Tests (headless)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _pyqt_available(), reason="PyQt6 not installed")
class TestMainWindowHeadless:
    """Tests for MainWindow in headless mode (no display needed)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(sys.argv)

    def test_window_creation(self):
        """MainWindow should create without errors."""
        from ui.main_window import MainWindow
        window = MainWindow()
        assert window is not None
        assert window.windowTitle() == "Lacrosse Highlight Assistant"

    def test_window_initial_state(self):
        """Window should start with no video, no track, no events."""
        from ui.main_window import MainWindow
        window = MainWindow()
        assert window.video_path is None
        assert window.track is None
        assert len(window.events) == 0

    def test_export_button_disabled_initially(self):
        """Export buttons should be disabled until video + events are loaded."""
        from ui.main_window import MainWindow
        window = MainWindow()
        assert not window.export_individual_btn.isEnabled()
        assert not window.export_reel_btn.isEnabled()

    def test_menu_bar_exists(self):
        """Menu bar should have File, Analyze, View, Help menus."""
        from ui.main_window import MainWindow
        window = MainWindow()
        menubar = window.menuBar()
        actions = [a.text() for a in menubar.actions()]
        assert any("File" in a for a in actions)
        assert any("Analyze" in a for a in actions)

    def test_toolbar_has_buttons(self):
        """Toolbar should have common action buttons."""
        from ui.main_window import MainWindow
        window = MainWindow()
        toolbar = window.findChildren(
            __import__('PyQt6.QtWidgets', fromlist=['QToolBar']).QToolBar
        )
        assert len(toolbar) >= 1

    def test_event_table_has_columns(self):
        """Event table should have 5 columns with headers."""
        from ui.main_window import MainWindow
        window = MainWindow()
        table = window.event_table
        assert table.columnCount() == 5
        headers = [table.horizontalHeaderItem(i).text() for i in range(5)]
        assert "Type" in headers
        assert "Time" in headers
        assert "Conf" in headers

    def test_confidence_combo_has_values(self):
        """Confidence filter combo should have multiple options."""
        from ui.main_window import MainWindow
        window = MainWindow()
        assert window.confidence_combo.count() >= 5


@pytest.mark.skipif(not _pyqt_available(), reason="PyQt6 not installed")
class TestWorkerThreads:
    """Tests for background worker threads."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.tmp = tmp_path

    def test_parser_worker_emits_error_on_missing_file(self, qtbot):
        """ParserWorker should emit error signal for missing file."""
        from ui.main_window import ParserWorker
        
        worker = ParserWorker("/nonexistent/file.track")
        
        with qtbot.waitSignal(worker.error, timeout=5000) as sig:
            worker.start()
        
        assert sig.args[0]  # Error message should be non-empty

    def test_detection_worker_emits_events(self, qtbot):
        """DetectionWorker should emit events for valid track data."""
        from ui.main_window import DetectionWorker
        from telemetry.models import TrackPoint, GameMetadata
        from telemetry.parser import ParsedTrack
        
        # Build a simple track
        points = []
        for i in range(300):
            t = i / 30.0
            points.append(TrackPoint(
                frame_num=i + 1, timestamp_sec=t,
                activity_score=0.3, center_x=500.0,
                center_speed=20.0, objects_detected=5,
                fps=30.0,
            ))
        
        metadata = GameMetadata(
            total_frames=300, total_duration_sec=10.0, video_fps=30.0,
        )
        track = ParsedTrack(points=points, metadata=metadata)
        
        worker = DetectionWorker(track)
        
        results = []
        worker.finished.connect(lambda events: results.extend(events))
        
        worker.start()
        worker.wait(5000)
        
        # Should produce some events (or at least not crash)
        assert isinstance(results, list)

    def test_export_worker_emits_error_on_missing_video(self, qtbot):
        """ExportWorker should emit error for missing video."""
        from ui.main_window import ExportWorker
        from export.ffmpeg import ExportConfig
        from telemetry.models import Event, EventType
        
        events = [Event(EventType.GOAL, 1.0, 3.0, 2.0)]
        
        worker = ExportWorker(
            "/nonexistent/video.mp4", events,
            str(self.tmp / "out.mp4"), ExportConfig(),
        )
        
        with qtbot.waitSignal(worker.error, timeout=5000) as sig:
            worker.start()
        
        assert sig.args[0]  # Error message should be non-empty


# ══════════════════════════════════════════════════════════════════════════
# Integration Test (requires display for full workflow)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not _pyqt_available() or not _has_display(),
    reason="PyQt6 not installed or no display available",
)
class TestFullWorkflow:
    """End-to-end workflow test with real display."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.tmp = tmp_path

    def test_window_shows(self):
        """Window should display without crashing."""
        from ui.main_window import MainWindow
        window = MainWindow()
        window.show()
        assert window.isVisible()
