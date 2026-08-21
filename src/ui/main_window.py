"""
Lacrosse Highlight Assistant — Main Window

PyQt6 desktop application for telemetry-driven highlight editing.

Workflow:
  1. File → Open Video  (.mp4, .mov, .avi)
  2. File → Open Track  (.track from FALCON camera)
  3. Analyze → Detect Events  (auto-detects plays)
  4. Review events in the list, check/uncheck clips
  5. File → Export Highlight Reel  (select format & destination)

Keyboard shortcuts:
  Ctrl+O    Open Video
  Ctrl+T    Open Track
  Ctrl+D    Detect Events
  Ctrl+E    Export Reel
  Ctrl+Q    Quit
  Space     Play/Pause (when video loaded)
  F5        Refresh

Usage:
    python -m src.ui.main_window
    python src/ui/main_window.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar, QMenu, QStatusBar,
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QProgressBar, QCheckBox,
    QGroupBox, QTextEdit, QToolBar, QStyle, QSpinBox,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize,
)
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QFont

from telemetry.logging_setup import configure_logging, get_logger
from telemetry.parser import parse_track_file
from telemetry.models import Event, EventType, PlayIntensity
from analysis.detection import detect_events, DetectionConfig
from analysis.metrics import rank_events
from export.ffmpeg import build_highlight_reel, ExportConfig

log = get_logger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

APP_TITLE = "Lacrosse Highlight Assistant"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
MIN_EVENT_CONFIDENCE = 0.3  # Default filter threshold


# ══════════════════════════════════════════════════════════════════════════
# Worker Threads (keep UI responsive during long operations)
# ══════════════════════════════════════════════════════════════════════════

class ParserWorker(QThread):
    """Background thread for parsing .track files."""
    finished = pyqtSignal(object)   # ParsedTrack
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, track_path: str):
        super().__init__()
        self.track_path = track_path
    
    def run(self):
        try:
            self.progress.emit("Parsing track file...")
            track = parse_track_file(self.track_path)
            self.finished.emit(track)
        except Exception as e:
            self.error.emit(str(e))


class DetectionWorker(QThread):
    """Background thread for event detection."""
    finished = pyqtSignal(list)    # List[Event]
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, track, config: Optional[DetectionConfig] = None):
        super().__init__()
        self.track = track
        self.config = config
    
    def run(self):
        try:
            self.progress.emit("Detecting events...")
            events = detect_events(self.track, self.config)
            self.finished.emit(events)
        except Exception as e:
            self.error.emit(str(e))


class ExportWorker(QThread):
    """Background thread for video export."""
    finished = pyqtSignal(str)     # Output path
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, video_path: str, events: List[Event],
                 output_path: str, config: ExportConfig,
                 add_titles: bool = True,
                 save_metadata: bool = True):
        super().__init__()
        self.video_path = video_path
        self.events = events
        self.output_path = output_path
        self.config = config
        self.add_titles = add_titles
        self.save_metadata = save_metadata
    
    def run(self):
        try:
            self.progress.emit("Building highlight reel...")
            self.config.save_metadata = self.save_metadata
            self.config.save_manifest = self.save_metadata
            path = build_highlight_reel(
                self.video_path, self.events, self.output_path,
                max_clips=min(len(self.events), 20),
                config=self.config,
                add_titles=self.add_titles,
                add_slowmo=False,
            )
            self.finished.emit(str(path))
        except Exception as e:
            self.error.emit(str(e))


class IndividualExportWorker(QThread):
    """Background thread for exporting individual clips (one file per event).
    
    Processes clips in small batches to avoid memory/CPU overload.
    Each batch is followed by a short cooldown pause.
    """
    finished = pyqtSignal(str)     # Output message
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, video_path: str, events: list,
                 output_dir: str, config: ExportConfig,
                 add_titles: bool = False,
                 save_metadata: bool = True,
                 batch_size: int = 3):
        super().__init__()
        self.video_path = video_path
        self.events = events
        self.output_dir = output_dir
        self.config = config
        self.add_titles = add_titles
        self.save_metadata = save_metadata
        self.batch_size = batch_size
    
    def run(self):
        import time
        from pathlib import Path
        from export.ffmpeg import extract_clip_from_event, _save_metadata_sidecars
        
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.config.save_metadata = self.save_metadata
        self.config.save_manifest = self.save_metadata
        
        total = len(self.events)
        success = 0
        batch_num = 0
        
        for batch_start in range(0, total, self.batch_size):
            batch_num += 1
            batch_end = min(batch_start + self.batch_size, total)
            batch = self.events[batch_start:batch_end]
            
            self.progress.emit(
                f"Batch {batch_num}: clips {batch_start+1}–{batch_end} of {total} "
                f"({len(batch)} clips)"
            )
            
            for j, event in enumerate(batch):
                i = batch_start + j
                clip_name = f"clip_{i:03d}_{event.event_type.value}.mp4"
                clip_path = out / clip_name
                
                try:
                    self.progress.emit(
                        f"  [{batch_num}] {event.event_type.value} "
                        f"@{event.peak_time_sec:.1f}s ({j+1}/{len(batch)})"
                    )
                    extract_clip_from_event(
                        self.video_path, event, clip_path,
                        config=self.config, add_title=self.add_titles,
                    )
                    success += 1
                except Exception as e:
                    self.progress.emit(f"  ⚠ Skipped: {e}")
            
            # Cooldown between batches — let FFmpeg processes fully exit
            if batch_end < total:
                remaining = total - batch_end
                self.progress.emit(
                    f"  ⏸ Batch {batch_num} done. Cooling down (2s)... "
                    f"{remaining} clips remaining"
                )
                time.sleep(2.0)
        
        if self.save_metadata:
            self.progress.emit("Writing metadata sidecars...")
            _save_metadata_sidecars(out, self.events, out, self.config)
        
        self.finished.emit(
            f"Exported {success}/{total} clips to {out}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Main application window for the Lacrosse Highlight Assistant."""
    
    def __init__(self):
        super().__init__()
        
        # ── State ──
        self.video_path: Optional[str] = None
        self.track_path: Optional[str] = None
        self.track: Optional[object] = None   # ParsedTrack
        self.events: List[Event] = []
        self.export_config = ExportConfig(pre_roll_sec=10.0, post_roll_sec=5.0)
        self.detection_config = DetectionConfig()
        
        # ── Setup UI ──
        self._setup_window()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_statusbar()
        
        self._update_state()
    
    # ── Window Setup ─────────────────────────────────────────────────
    
    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(800, 500)
    
    def _setup_menu(self):
        """Build the menu bar."""
        menubar = self.menuBar()
        
        # ── File menu ──
        file_menu = menubar.addMenu("&File")
        
        open_video_action = QAction("&Open Video...", self)
        open_video_action.setShortcut(QKeySequence("Ctrl+O"))
        open_video_action.triggered.connect(self._on_open_video)
        file_menu.addAction(open_video_action)
        
        open_track_action = QAction("Open &Track...", self)
        open_track_action.setShortcut(QKeySequence("Ctrl+T"))
        open_track_action.triggered.connect(self._on_open_track)
        file_menu.addAction(open_track_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("&Export Highlight Reel...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # ── Analyze menu ──
        analyze_menu = menubar.addMenu("&Analyze")
        
        detect_action = QAction("&Detect Events", self)
        detect_action.setShortcut(QKeySequence("Ctrl+D"))
        detect_action.triggered.connect(self._on_detect_events)
        analyze_menu.addAction(detect_action)
        
        # ── View menu ──
        view_menu = menubar.addMenu("&View")
        
        refresh_action = QAction("&Refresh", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self._on_refresh)
        view_menu.addAction(refresh_action)
        
        # ── Help menu ──
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_toolbar(self):
        """Build the toolbar with common actions."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)
        
        # Open Video
        open_btn = QPushButton("📹 Open Video")
        open_btn.clicked.connect(self._on_open_video)
        toolbar.addWidget(open_btn)
        
        # Open Track
        track_btn = QPushButton("📊 Open Track")
        track_btn.clicked.connect(self._on_open_track)
        toolbar.addWidget(track_btn)
        
        toolbar.addSeparator()
        
        # Detect
        detect_btn = QPushButton("🔍 Detect Events")
        detect_btn.clicked.connect(self._on_detect_events)
        toolbar.addWidget(detect_btn)
        
        toolbar.addSeparator()
        
        # Export
        export_btn = QPushButton("📤 Export Reel")
        export_btn.clicked.connect(self._on_export)
        toolbar.addWidget(export_btn)
    
    def _setup_central_widget(self):
        """Build the main splitter layout."""
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main horizontal splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)
        
        # ── Left panel: Event list ──
        left_panel = self._build_event_panel()
        splitter.addWidget(left_panel)
        
        # ── Center: Video + info ──
        center_panel = self._build_center_panel()
        splitter.addWidget(center_panel)
        
        # ── Right panel: Export controls ──
        right_panel = self._build_export_panel()
        splitter.addWidget(right_panel)
        
        # Set ratios: 30% | 45% | 25%
        splitter.setSizes([380, 560, 320])
    
    def _build_event_panel(self) -> QWidget:
        """Build the left panel with event list."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("🎯 Detected Events")
        header.setFont(QFont(header.font().family(), 12, QFont.Weight.Bold))
        layout.addWidget(header)
        
        # Confidence filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Min confidence:"))
        self.confidence_combo = QComboBox()
        self.confidence_combo.addItems(["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7"])
        self.confidence_combo.setCurrentText("0.3")
        self.confidence_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.confidence_combo)
        layout.addLayout(filter_row)
        
        # Select all / deselect all
        select_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._select_all(True))
        select_row.addWidget(select_all_btn)
        deselect_btn = QPushButton("Deselect All")
        deselect_btn.clicked.connect(lambda: self._select_all(False))
        select_row.addWidget(deselect_btn)
        layout.addLayout(select_row)
        
        # Event table
        self.event_table = QTableWidget(0, 5)
        self.event_table.setHorizontalHeaderLabels(
            ["✓", "Type", "Time", "Conf", "Intensity"]
        )
        self.event_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.event_table.setColumnWidth(0, 30)
        self.event_table.setColumnWidth(1, 80)
        self.event_table.setColumnWidth(2, 60)
        self.event_table.setColumnWidth(3, 50)
        self.event_table.setColumnWidth(4, 70)
        self.event_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.event_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.event_table)
        
        # Event count label
        self.event_count_label = QLabel("No events detected")
        layout.addWidget(self.event_count_label)
        
        return panel
    
    def _build_center_panel(self) -> QWidget:
        """Build the center panel with video placeholder."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Video area
        video_group = QGroupBox("📹 Video")
        video_layout = QVBoxLayout(video_group)
        
        self.video_label = QLabel(
            "No video loaded.\n\n"
            "Use File → Open Video to load a game recording,\n"
            "or drag & drop a video file here."
        )
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet(
            "background-color: #1a1a1a; color: #888; "
            "border: 2px dashed #444; border-radius: 8px; "
            "padding: 40px; font-size: 14px;"
        )
        self.video_label.setMinimumHeight(300)
        video_layout.addWidget(self.video_label)
        
        layout.addWidget(video_group)
        
        # File info
        self.file_info = QTextEdit()
        self.file_info.setReadOnly(True)
        self.file_info.setMaximumHeight(150)
        self.file_info.setPlaceholderText(
            "File information will appear here after loading a video and track file."
        )
        layout.addWidget(self.file_info)
        
        return panel
    
    def _build_export_panel(self) -> QWidget:
        """Build the right panel with export controls."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("📤 Export")
        header.setFont(QFont(header.font().family(), 12, QFont.Weight.Bold))
        layout.addWidget(header)
        
        # ── Event type filter ──
        filter_group = QGroupBox("Event types to export")
        filter_layout = QVBoxLayout(filter_group)
        self.type_checks: dict = {}
        for ev_type, label in [
            (EventType.GOAL, "🥍 Goals"), (EventType.SHOT, "🎯 Shots"),
            (EventType.SAVE, "🧤 Saves"), (EventType.TRANSITION, "🏃 Transitions"),
            (EventType.FACE_OFF, "⚡ Face-offs"), (EventType.TURNOVER, "↩️ Turnovers"),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(self._on_filter_changed)
            self.type_checks[ev_type.value] = cb
            filter_layout.addWidget(cb)
        layout.addWidget(filter_group)
        
        # ── Clip length ──
        length_group = QGroupBox("Clip length")
        length_layout = QVBoxLayout(length_group)
        
        pre_row = QHBoxLayout()
        pre_row.addWidget(QLabel("Pre-roll:"))
        self.pre_roll_spin = QSpinBox()
        self.pre_roll_spin.setRange(0, 30)
        self.pre_roll_spin.setValue(10)
        self.pre_roll_spin.setSuffix("s")
        self.pre_roll_spin.valueChanged.connect(self._on_length_changed)
        pre_row.addWidget(self.pre_roll_spin)
        length_layout.addLayout(pre_row)
        
        post_row = QHBoxLayout()
        post_row.addWidget(QLabel("Post-roll:"))
        self.post_roll_spin = QSpinBox()
        self.post_roll_spin.setRange(0, 30)
        self.post_roll_spin.setValue(5)
        self.post_roll_spin.setSuffix("s")
        self.post_roll_spin.valueChanged.connect(self._on_length_changed)
        post_row.addWidget(self.post_roll_spin)
        length_layout.addLayout(post_row)
        
        self.clip_length_label = QLabel(
            f"Total: ~{self.pre_roll_spin.value() + 5 + self.post_roll_spin.value()}s per clip"
        )
        length_layout.addWidget(self.clip_length_label)
        layout.addWidget(length_group)
        
        # ── Format ──
        format_group = QGroupBox("Output Format")
        format_layout = QVBoxLayout(format_group)
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "MP4 (H.264) — Social Media",
            "MP4 (H.264) — High Quality",
        ])
        format_layout.addWidget(self.format_combo)
        layout.addWidget(format_group)
        
        # ── Options ──
        self.title_check = QCheckBox("Add title overlays")
        self.title_check.setChecked(False)
        layout.addWidget(self.title_check)
        
        self.metadata_check = QCheckBox("Save telemetry metadata (.json sidecar)")
        self.metadata_check.setChecked(True)
        self.metadata_check.setToolTip(
            "Saves event type, confidence, timestamps, and telemetry "
            "alongside each clip for AI training datasets"
        )
        layout.addWidget(self.metadata_check)
        
        clips_layout = QHBoxLayout()
        clips_layout.addWidget(QLabel("Max clips:"))
        self.max_clips_combo = QComboBox()
        self.max_clips_combo.addItems(["5", "10", "15", "20", "All"])
        self.max_clips_combo.setCurrentText("All")
        clips_layout.addWidget(self.max_clips_combo)
        layout.addLayout(clips_layout)
        
        # Batch size
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch size:"))
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 20)
        self.batch_size_spin.setValue(3)
        self.batch_size_spin.setToolTip(
            "Process clips in small batches to avoid memory pressure. "
            "Lower = safer, higher = faster."
        )
        batch_layout.addWidget(self.batch_size_spin)
        layout.addLayout(batch_layout)
        
        layout.addStretch()
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)
        
        # ── Export buttons ──
        self.export_individual_btn = QPushButton("📤 Export Individual Clips (for review)")
        self.export_individual_btn.setMinimumHeight(40)
        self.export_individual_btn.setEnabled(False)
        self.export_individual_btn.setToolTip(
            "Export each selected event as a separate MP4 file with metadata "
            "sidecar. Best for building a verified training dataset."
        )
        self.export_individual_btn.clicked.connect(self._on_export_individual)
        layout.addWidget(self.export_individual_btn)
        
        self.export_reel_btn = QPushButton("🎬 Export Highlight Reel")
        self.export_reel_btn.setMinimumHeight(36)
        self.export_reel_btn.setEnabled(False)
        self.export_reel_btn.setToolTip(
            "Concatenate all selected clips into a single highlight reel."
        )
        self.export_reel_btn.clicked.connect(self._on_export)
        layout.addWidget(self.export_reel_btn)
        
        # Selected count
        self.selected_label = QLabel("0 clips selected")
        layout.addWidget(self.selected_label)
        
        return panel
    
    def _setup_statusbar(self):
        """Configure the status bar."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready — Open a video and track file to begin.")
    
    # ── State Management ─────────────────────────────────────────────
    
    def _update_state(self):
        """Enable/disable UI elements based on current state."""
        has_video = self.video_path is not None
        has_track = self.track is not None
        has_events = len(self.events) > 0
        
        # Export buttons enabled only when everything is ready
        self.export_individual_btn.setEnabled(has_video and has_events)
        self.export_reel_btn.setEnabled(has_video and has_events)
        
        # Update file info
        info_lines = []
        if self.video_path:
            info_lines.append(f"🎬 Video: {Path(self.video_path).name}")
        else:
            info_lines.append("🎬 Video: (none)")
        
        if self.track_path:
            info_lines.append(f"📊 Track: {Path(self.track_path).name}")
        if self.track:
            info_lines.append(f"   Frames: {len(self.track.points)}")
            info_lines.append(f"   Duration: {self.track.metadata.total_duration_sec:.1f}s")
            info_lines.append(f"   Version: {self.track.metadata.track_version or 'unknown'}")
        else:
            info_lines.append("📊 Track: (none)")
        
        if has_events:
            info_lines.append(f"🎯 Events: {len(self.events)} detected")
        else:
            info_lines.append("🎯 Events: (none — run Detect Events)")
        
        self.file_info.setText("\n".join(info_lines))
    
    def _select_all(self, checked: bool):
        """Check/uncheck all events in the table."""
        for row in range(self.event_table.rowCount()):
            widget = self.event_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(checked)
        self._update_selected_count()
    
    def _update_selected_count(self):
        """Update the selected clip count label."""
        count = 0
        for row in range(self.event_table.rowCount()):
            widget = self.event_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                count += 1
        self.selected_label.setText(f"{count} clips selected")
    
    def _get_selected_events(self) -> List[Event]:
        """Get the list of events selected in the table."""
        selected = []
        for row in range(self.event_table.rowCount()):
            widget = self.event_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                if row < len(self.events):
                    selected.append(self.events[row])
        return selected
    
    # ── Event List Population ────────────────────────────────────────
    
    def _populate_event_list(self):
        """Fill the event table with detected events."""
        threshold = float(self.confidence_combo.currentText())
        filtered = [e for e in self.events if e.confidence >= threshold]
        
        # Apply type filter if type_checks are available
        if hasattr(self, 'type_checks'):
            enabled_types = {t for t, cb in self.type_checks.items() if cb.isChecked()}
            if enabled_types:
                filtered = [e for e in filtered if e.event_type.value in enabled_types]
        
        self.event_table.setRowCount(0)
        
        for i, event in enumerate(filtered):
            row = self.event_table.rowCount()
            self.event_table.insertRow(row)
            
            # Checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.toggled.connect(lambda: self._update_selected_count())
            self.event_table.setCellWidget(row, 0, checkbox)
            
            # Type
            icons = {
                EventType.GOAL: "🥍 Goal",
                EventType.SHOT: "🎯 Shot",
                EventType.SAVE: "🧤 Save",
                EventType.TRANSITION: "🏃 Transition",
                EventType.FACE_OFF: "⚡ Face-off",
                EventType.TURNOVER: "↩️ Turnover",
                EventType.UNKNOWN: "❓ Unknown",
            }
            type_str = icons.get(event.event_type, event.event_type.value)
            self.event_table.setItem(row, 1, QTableWidgetItem(type_str))
            
            # Time
            mins = int(event.peak_time_sec // 60)
            secs = int(event.peak_time_sec % 60)
            time_str = f"{mins}:{secs:02d}"
            self.event_table.setItem(row, 2, QTableWidgetItem(time_str))
            
            # Confidence
            conf_str = f"{event.confidence:.0%}"
            conf_item = QTableWidgetItem(conf_str)
            if event.confidence >= 0.7:
                conf_item.setForeground(Qt.GlobalColor.darkGreen)
            elif event.confidence >= 0.5:
                conf_item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                conf_item.setForeground(Qt.GlobalColor.darkRed)
            self.event_table.setItem(row, 3, conf_item)
            
            # Intensity
            int_item = QTableWidgetItem(event.intensity.value.upper())
            self.event_table.setItem(row, 4, int_item)
        
        self.event_count_label.setText(
            f"{len(filtered)} events shown (filtered from {len(self.events)} total)"
        )
        self._update_selected_count()
    
    # ── Slots / Actions ──────────────────────────────────────────────
    
    def _on_open_video(self):
        """Open a video file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video File", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
        )
        if path:
            self.video_path = path
            self.video_label.setText(
                f"✅ Video loaded: {Path(path).name}\n\n"
                f"Open a track file to continue."
            )
            self.video_label.setStyleSheet(
                "background-color: #1a2a1a; color: #8f8; "
                "border: 2px solid #2a4a2a; border-radius: 8px; "
                "padding: 40px; font-size: 14px;"
            )
            self.statusbar.showMessage(f"Loaded video: {Path(path).name}")
            self._update_state()
    
    def _on_open_track(self):
        """Open a FALCON .track file and parse it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Track File", "",
            "Track Files (*.track);;All Files (*)",
        )
        if not path:
            return
        
        self.track_path = path
        self.statusbar.showMessage("Parsing track file...")
        
        self.worker = ParserWorker(path)
        self.worker.progress.connect(
            lambda msg: self.statusbar.showMessage(msg)
        )
        self.worker.finished.connect(self._on_track_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_track_loaded(self, track):
        """Handle successfully parsed track."""
        self.track = track
        self.statusbar.showMessage(
            f"Loaded {len(track.points)} frames from {Path(self.track_path).name}"
        )
        self._update_state()
        
        # Auto-detect events
        self._on_detect_events()
    
    def _on_detect_events(self):
        """Run event detection on the loaded track."""
        if self.track is None:
            QMessageBox.warning(self, "No Track", "Open a track file first.")
            return
        
        self.statusbar.showMessage("Detecting events...")
        
        self.worker = DetectionWorker(self.track, self.detection_config)
        self.worker.progress.connect(
            lambda msg: self.statusbar.showMessage(msg)
        )
        self.worker.finished.connect(self._on_events_detected)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_events_detected(self, events: List[Event]):
        """Handle event detection results."""
        self.events = events
        self._populate_event_list()
        self._update_state()
        
        n = len(events)
        goals = sum(1 for e in events if e.event_type == EventType.GOAL)
        self.statusbar.showMessage(
            f"Detected {n} events ({goals} goals, "
            f"{n - goals} other plays)"
        )
    
    def _on_export(self):
        """Export highlight reel from selected events."""
        if not self.video_path:
            QMessageBox.warning(self, "No Video", "Open a video file first.")
            return
        
        selected = self._get_selected_events()
        if not selected:
            QMessageBox.warning(
                self, "No Clips Selected",
                "Check at least one event in the list to export."
            )
            return
        
        # Choose output path
        output, _ = QFileDialog.getSaveFileName(
            self, "Save Highlight Reel", "highlights.mp4",
            "MP4 Video (*.mp4);;All Files (*)",
        )
        if not output:
            return
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_label.setText("Building highlight reel...")
        self.export_individual_btn.setEnabled(False)
        self.export_reel_btn.setEnabled(False)
        
        self.worker = ExportWorker(
            self.video_path, selected, output,
            self.export_config, self.title_check.isChecked(),
            save_metadata=self.metadata_check.isChecked(),
        )
        self.worker.progress.connect(
            lambda msg: self.progress_label.setText(msg)
        )
        self.worker.finished.connect(self._on_export_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_export_finished(self, output_path: str):
        """Handle export completion."""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.export_individual_btn.setEnabled(True)
        self.export_reel_btn.setEnabled(True)
        
        size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        self.statusbar.showMessage(
            f"Exported: {Path(output_path).name} ({size_mb:.1f} MB)"
        )
        
        QMessageBox.information(
            self, "Export Complete",
            f"Highlight reel saved to:\n{output_path}\n\n"
            f"Size: {size_mb:.1f} MB"
        )
    
    def _on_filter_changed(self):
        """Re-filter the event list when confidence or type filters change."""
        if self.events:
            self._populate_event_list()
    
    def _on_length_changed(self):
        """Update clip length label and config when pre/post roll changes."""
        total = self.pre_roll_spin.value() + 5 + self.post_roll_spin.value()
        self.clip_length_label.setText(f"Total: ~{total}s per clip")
        self.export_config.pre_roll_sec = float(self.pre_roll_spin.value())
        self.export_config.post_roll_sec = float(self.post_roll_spin.value())
    
    def _on_export_individual(self):
        """Export each selected event as a separate MP4 file."""
        if not self.video_path:
            QMessageBox.warning(self, "No Video", "Open a video file first.")
            return
        
        selected = self._get_selected_events()
        if not selected:
            QMessageBox.warning(
                self, "No Clips Selected",
                "Check at least one event in the list to export."
            )
            return
        
        # Choose output directory (not file)
        out_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory for Individual Clips"
        )
        if not out_dir:
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText(f"Exporting {len(selected)} individual clips...")
        self.export_individual_btn.setEnabled(False)
        self.export_reel_btn.setEnabled(False)
        
        self.worker = IndividualExportWorker(
            self.video_path, selected, out_dir,
            self.export_config, self.title_check.isChecked(),
            save_metadata=self.metadata_check.isChecked(),
            batch_size=self.batch_size_spin.value(),
        )
        self.worker.progress.connect(lambda msg: self.progress_label.setText(msg))
        self.worker.finished.connect(self._on_export_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_refresh(self):
        """Refresh the UI state."""
        self._update_state()
        if self.events:
            self._populate_event_list()
    
    def _on_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, f"About {APP_TITLE}",
            f"<h3>{APP_TITLE}</h3>"
            f"<p>Telemetry-driven video editing assistant for lacrosse.</p>"
            f"<p><b>Version:</b> 0.1.0 (MVP)</p>"
            f"<p><b>Workflow:</b> Load Video → Load Track → "
            f"Detect Events → Export Reel</p>"
            f"<p>Built with PyQt6, NumPy, and FFmpeg.</p>"
        )
    
    def _on_error(self, message: str):
        """Handle errors from worker threads."""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.export_individual_btn.setEnabled(True)
        self.export_reel_btn.setEnabled(True)
        
        self.statusbar.showMessage(f"Error: {message[:100]}")
        QMessageBox.critical(self, "Error", message)
    
    # ── Drag & Drop ──────────────────────────────────────────────────
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
    
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.endswith(".track"):
                self.track_path = path
                self._on_open_track()
            elif path.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                self.video_path = path
                self._on_open_video()


# ══════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════

def _load_app_icon() -> Optional[QIcon]:
    """Load the bundled app icon (assets/icon.png) if present.

    Works both from a source checkout and from a frozen PyInstaller build
    (where assets/ is bundled via the spec).
    """
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(bundle_root / "assets" / "icon.png")
        candidates.append(Path(sys.executable).parent / "assets" / "icon.png")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png")
    for candidate in candidates:
        if candidate.exists():
            icon = QIcon(str(candidate))
            if not icon.isNull():
                return icon
    return None


def main():
    """Launch the Lacrosse Highlight Assistant desktop application."""
    configure_logging(level="INFO")
    
    # Auto-detect headless: use offscreen platform directly.
    # Only Linux relies on DISPLAY/WAYLAND_DISPLAY env vars — on Windows and
    # macOS the native window server is always present, so never force
    # offscreen there unless --headless is explicitly requested.
    argv = sys.argv[:1]  # Keep program name only
    is_linux = sys.platform.startswith("linux")
    headless = "--headless" in sys.argv
    if headless or (
        is_linux
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        log.info("no display detected — using offscreen mode")
        argv += ["-platform", "offscreen"]
    
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("Lacrosse Video Assistant")
    
    # Apply the app icon (window + taskbar/dock) where available
    app_icon = _load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)
    
    # Apply dark theme
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
