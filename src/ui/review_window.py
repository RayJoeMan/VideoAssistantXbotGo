"""Interactive event review window.

Watch each detected event's clip and label it (correct / wrong + what it
actually was) so the classifier can be recalibrated with real ground truth.

Labels are written incrementally to a JSONL file that is compatible with
``scripts/event_review.py evaluate`` — so after a session you can run::

    python scripts/event_review.py evaluate <track> labels.jsonl

Playback is frame-based and pipes JPEG frames out of the *bundled* FFmpeg
(via QProcess), so it works identically in the packaged app — no GStreamer or
QtMultimedia backend required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    Qt, QObject, QProcess, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QImage, QPixmap, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QComboBox, QLineEdit, QProgressBar, QFileDialog,
    QMessageBox, QGroupBox, QFrame,
)

from telemetry.models import Event, EventType
from export.ffmpeg import resolve_tool

# ══════════════════════════════════════════════════════════════════════════
# Label record helpers (mirror scripts/event_review.py:_event_dict)
# ══════════════════════════════════════════════════════════════════════════

EVENT_TYPE_LABELS = {
    EventType.GOAL: "goal",
    EventType.SAVE: "save",
    EventType.SHOT: "shot",
    EventType.TRANSITION: "transition",
    EventType.TURNOVER: "turnover",
    EventType.FACE_OFF: "face_off",
    EventType.PENALTY: "penalty",
    EventType.UNKNOWN: "unknown",
}

# Values shown in the "actual type" picker (empty = leave predicted).
ACTUAL_TYPE_CHOICES = [
    ("", "— leave predicted —"),
    ("not_an_event", "❌ Not an event"),
    ("goal", "🥍 Goal"),
    ("save", "🧤 Save"),
    ("shot", "🎯 Shot"),
    ("transition", "🏃 Transition"),
    ("turnover", "↩️ Turnover"),
    ("face_off", "⚡ Face-off"),
    ("penalty", "🟨 Penalty"),
    ("unknown", "❓ Unknown / can't tell"),
]


def make_label_record(idx: int, event: Event, *,
                      correct: Optional[bool] = None,
                      actual_type: Optional[str] = None,
                      notes: str = "") -> dict:
    """Build a label-sheet record in the same shape as event_review.py."""
    return {
        "id": idx,
        "predicted_type": event.event_type.value,
        "start_sec": round(event.start_time_sec, 2),
        "end_sec": round(event.end_time_sec, 2),
        "peak_sec": round(event.peak_time_sec, 2),
        "duration_sec": round(event.duration_sec, 2),
        "confidence": round(event.confidence, 3),
        "frame_range": list(event.frame_range),
        "tags": list(event.tags),
        "description": event.description,
        "correct": correct,
        "actual_type": actual_type,
        "notes": notes,
    }


def load_labels(path: Path) -> Dict[int, dict]:
    """Load a JSONL label sheet, keyed by record id."""
    records: Dict[int, dict] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = rec.get("id")
        if rid is not None:
            records[int(rid)] = rec
    return records


def write_labels(path: Path, records: Dict[int, dict]) -> None:
    """Write the label sheet back to disk (all records, one JSON per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rid in sorted(records):
            f.write(json.dumps(records[rid]) + "\n")


# ══════════════════════════════════════════════════════════════════════════
# Frame-based clip player (pipes JPEG frames out of bundled FFmpeg)
# ══════════════════════════════════════════════════════════════════════════

class FrameStreamPlayer(QObject):
    """Plays a video segment by streaming MJPEG frames from FFmpeg via QProcess."""

    frameReady = pyqtSignal(object)   # QImage
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)
        self._buffer = bytearray()
        self._frames: List[QImage] = []
        self._idx = 0
        self.fps = 10.0
        self._playing = False

    # ── public API ───────────────────────────────────────────────────

    def play(self, video_path: str, start_sec: float,
             duration_sec: float, fps: float = 10.0,
             width: int = 960) -> None:
        """Stream frames of [start, start+duration) from the video."""
        self.stop()
        self._frames = []
        self._idx = 0
        self.fps = max(1.0, fps)
        ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
        args = [
            "-loglevel", "error",
            "-ss", f"{max(0.0, start_sec):.3f}",
            "-i", video_path,
            "-t", f"{max(0.5, duration_sec):.3f}",
            "-vf", f"fps={self.fps},scale={width}:-2",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "5",
            "pipe:1",
        ]
        self._proc.start(ffmpeg, args)
        self._timer.start(int(1000.0 / self.fps))
        self._playing = True

    def pause(self) -> None:
        self._timer.stop()
        self._playing = False

    def resume(self) -> None:
        if self._frames:
            self._timer.start(int(1000.0 / self.fps))
            self._playing = True

    def stop(self) -> None:
        self._timer.stop()
        self._playing = False
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(1000)

    def is_playing(self) -> bool:
        return self._playing

    # ── internals ────────────────────────────────────────────────────

    def _on_stdout(self) -> None:
        data = bytes(self._proc.readAllStandardOutput())
        if not data:
            return
        self._buffer += data
        # Split the byte stream into JPEG frames (FFD8 ... FFD9).
        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start == -1:
                self._buffer.clear()
                break
            end = self._buffer.find(b"\xff\xd9", start)
            if end == -1:
                # keep the partial frame for the next chunk
                del self._buffer[:start]
                break
            jpeg = bytes(self._buffer[start:end + 2])
            img = QImage.fromData(jpeg, "JPG")
            if not img.isNull():
                self._frames.append(img)
            del self._buffer[:end + 2]

    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        if err != QProcess.ProcessError.Crashed:
            self.error.emit(f"ffmpeg error: {err.name}")

    def _advance(self) -> None:
        if not self._frames:
            return
        if self._idx >= len(self._frames):
            self._idx = 0  # loop the clip
        self.frameReady.emit(self._frames[self._idx])
        self._idx += 1


# ══════════════════════════════════════════════════════════════════════════
# Review Window
# ══════════════════════════════════════════════════════════════════════════

class ReviewWindow(QDialog):
    """Watch each event clip and label it — correct / wrong + actual type."""

    def __init__(self, video_path: str, events: List[Event],
                 parent: Optional[QWidget] = None,
                 labels_file: Optional[str] = None):
        super().__init__(parent)
        self.video_path = video_path
        self.events = list(events)
        self.labels_file: Optional[Path] = None
        self.records: Dict[int, dict] = {}
        self.current_idx = 0

        self.player = FrameStreamPlayer(self)
        self.player.frameReady.connect(self._on_frame)
        self.player.error.connect(self._on_player_error)

        self.setWindowTitle("Review Events — Lacrosse Highlight Assistant")
        self.resize(1100, 680)
        self._build_ui()
        if labels_file:
            self.labels_file = Path(labels_file)
            existing = load_labels(self.labels_file)
            if existing:
                self.records = existing
        else:
            self._pick_labels_file()
        self._rebuild_list()
        if self.events:
            self._select(0)

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # ── Left: event list ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        left_layout.addWidget(QLabel("Events (click to review)"))
        left_layout.addWidget(self.list_widget)
        splitter.addWidget(left)

        # ── Right: video + labels ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel("Select an event to preview its clip.")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumHeight(320)
        self.video_label.setStyleSheet(
            "background-color: #111; color: #888; border: 1px solid #333;"
        )
        right_layout.addWidget(self.video_label, 1)

        # Playback controls
        controls = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.play_btn = QPushButton("⏸ Pause")
        self.play_btn.clicked.connect(self._toggle_play)
        self.restart_btn = QPushButton("⟲ Restart")
        self.restart_btn.clicked.connect(lambda: self._select(self.current_idx))
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(lambda: self._step(1))
        for b in (self.prev_btn, self.play_btn, self.restart_btn, self.next_btn):
            controls.addWidget(b)
        controls.addStretch()
        right_layout.addLayout(controls)

        # Event info
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        right_layout.addWidget(self.info_label)

        # ── Label controls ──
        label_group = QGroupBox("Your call — is this event correct?")
        label_layout = QVBoxLayout(label_group)

        self.correct_btn = QPushButton("✓ Correct — detector got it right")
        self.correct_btn.setStyleSheet(
            "QPushButton { background:#1e5a2e; color:white; font-weight:bold;"
            " padding:8px; } QPushButton:hover { background:#287a3c; }"
        )
        self.correct_btn.clicked.connect(lambda: self._apply_label(True))
        label_layout.addWidget(self.correct_btn)

        self.wrong_btn = QPushButton("✗ Wrong — it was something else")
        self.wrong_btn.setStyleSheet(
            "QPushButton { background:#6a2020; color:white; font-weight:bold;"
            " padding:8px; } QPushButton:hover { background:#8a2c2c; }"
        )
        self.wrong_btn.clicked.connect(lambda: self._apply_label(False))
        label_layout.addWidget(self.wrong_btn)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Actually a:"))
        self.type_combo = QComboBox()
        for value, label in ACTUAL_TYPE_CHOICES:
            self.type_combo.addItem(label, value)
        self.type_combo.setToolTip(
            "When you mark an event wrong, pick what it really was. "
            "This teaches the classifier the correct type."
        )
        type_row.addWidget(self.type_combo, 1)
        label_layout.addLayout(type_row)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("Notes:"))
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("optional — e.g. 'goal off a rebound'")
        notes_row.addWidget(self.notes_edit, 1)
        label_layout.addLayout(notes_row)

        skip_row = QHBoxLayout()
        self.skip_btn = QPushButton("⏭ Skip for now")
        self.skip_btn.clicked.connect(self._skip)
        skip_row.addWidget(self.skip_btn)
        skip_row.addStretch()
        label_layout.addLayout(skip_row)

        right_layout.addWidget(label_group)

        # Progress
        self.progress_label = QLabel("")
        right_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)

        splitter.addWidget(right)
        splitter.setSizes([340, 760])

        # Bottom row: save/close
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.save_btn = QPushButton("💾 Save & Close")
        self.save_btn.clicked.connect(self.accept)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

        self._update_shortcuts()

    def _update_shortcuts(self) -> None:
        """Keyboard mapping: space = play, arrows = prev/next, C/W = label."""
        for key, fn in [
            (Qt.Key.Key_Space, self._toggle_play),
            (Qt.Key.Key_Left, lambda: self._step(-1)),
            (Qt.Key.Key_Right, lambda: self._step(1)),
            (Qt.Key.Key_C, lambda: self._apply_label(True)),
            (Qt.Key.Key_W, lambda: self._apply_label(False)),
            (Qt.Key.Key_S, self._skip),
            (Qt.Key.Key_R, lambda: self._select(self.current_idx)),
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    # ── label file handling ──────────────────────────────────────────

    def _pick_labels_file(self) -> None:
        """Ask where to save labels; resume from the file if it exists."""
        suggested = f"labels_{Path(self.video_path).stem}.jsonl" \
            if self.video_path else "labels.jsonl"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save labels to (JSONL)", suggested,
            "Label sheets (*.jsonl *.json);;All Files (*)",
        )
        if not path:
            return
        self.labels_file = Path(path)
        existing = load_labels(self.labels_file)
        if existing:
            self.records = existing
            self.status_message(
                f"Resumed {len(existing)} existing label(s) from {path}"
            )

    # ── list + selection ─────────────────────────────────────────────

    def _rebuild_list(self) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for i, e in enumerate(self.events):
            status = "·"
            if i in self.records and self.records[i].get("correct") is not None:
                status = "✓" if self.records[i]["correct"] else "✗"
            mins = int(e.peak_time_sec // 60)
            secs = int(e.peak_time_sec % 60)
            item = QListWidgetItem(
                f"{status}  #{i + 1}  {e.event_type.value.upper():11s}"
                f" @ {mins}:{secs:02d}  ({e.confidence:.0%})"
            )
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._update_progress()

    def _update_progress(self) -> None:
        reviewed = sum(
            1 for r in self.records.values()
            if r.get("correct") is not None
        )
        total = len(self.events)
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(reviewed)
        self.progress_label.setText(
            f"Labeled {reviewed} / {total} events"
            f" — saved to {self.labels_file or '(choose a file on close)'}"
        )

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self.events):
            self._select(row)

    def _select(self, idx: int) -> None:
        if not self.events or not (0 <= idx < len(self.events)):
            return
        self.current_idx = idx
        self.list_widget.blockSignals(True)
        self.list_widget.setCurrentRow(idx)
        self.list_widget.blockSignals(False)

        event = self.events[idx]
        mins = int(event.peak_time_sec // 60)
        secs = int(event.peak_time_sec % 60)
        self.info_label.setText(
            f"#{idx + 1} · {event.event_type.value.upper()} · "
            f"peak {mins}:{secs:02d} ({event.peak_time_sec:.1f}s) · "
            f"conf {event.confidence:.0%} · {event.duration_sec:.1f}s clip"
        )

        # Restore any existing label for this event
        rec = self.records.get(idx, {})
        self.play_btn.setText("⏸ Pause")
        actual = rec.get("actual_type")
        combo_idx = self.type_combo.findData(actual)
        self.type_combo.setCurrentIndex(combo_idx if combo_idx >= 0 else 0)
        self.notes_edit.setText(rec.get("notes", ""))

        # Start playback of this event's clip
        if self.video_path:
            start = max(0.0, event.start_time_sec - 1.0)
            dur = min(15.0, (event.end_time_sec + 2.0) - start)
            self.player.play(self.video_path, start, dur, fps=10.0, width=960)
        else:
            self.video_label.setText("(no video loaded)")
            self.player.stop()

    # ── labeling ─────────────────────────────────────────────────────

    def _apply_label(self, correct: bool) -> None:
        if not self.events or not (0 <= self.current_idx < len(self.events)):
            return
        idx = self.current_idx
        event = self.events[idx]
        actual = None if correct else self.type_combo.currentData() or None
        notes = self.notes_edit.text().strip()
        self.records[idx] = make_label_record(
            idx, event, correct=correct, actual_type=actual, notes=notes,
        )
        self._ensure_all_records()
        if self.labels_file:
            write_labels(self.labels_file, self.records)
        self._rebuild_list()
        # Auto-advance
        if idx + 1 < len(self.events):
            self._select(idx + 1)
        else:
            self.status_message("All events reviewed! 🎉")

    def _ensure_all_records(self) -> None:
        """Make sure every event has a sheet row (unlabeled ones get
        correct=None), so evaluate() sees the full event count."""
        for i, e in enumerate(self.events):
            if i not in self.records:
                self.records[i] = make_label_record(i, e)

    def _skip(self) -> None:
        self._step(1)

    # ── navigation / playback ────────────────────────────────────────

    def _step(self, delta: int) -> None:
        n = len(self.events)
        if not n:
            return
        self._select((self.current_idx + delta) % n)

    def _toggle_play(self) -> None:
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.setText("▶ Play")
        else:
            self.player.resume()
            self.play_btn.setText("⏸ Pause")

    def _on_frame(self, img: QImage) -> None:
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        self.video_label.setPixmap(
            pix.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_player_error(self, msg: str) -> None:
        self.video_label.setText(f"Playback error:\n{msg}")

    def status_message(self, msg: str) -> None:
        if hasattr(self, "progress_label"):
            self.progress_label.setText(msg)

    # ── lifecycle ────────────────────────────────────────────────────

    def done(self, result: int) -> None:
        self.player.stop()
        self._ensure_all_records()
        if self.records and self.labels_file:
            write_labels(self.labels_file, self.records)
        super().done(result)
