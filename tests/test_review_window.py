"""Tests for the interactive review window + label-sheet helpers.

The label helpers (make_label_record / load_labels / write_labels) are pure
and fast. The ReviewWindow tests exercise the label flow end-to-end without
needing playback assertions (frames stream via bundled ffmpeg, but we only
check the JSONL side).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from telemetry.models import Event, EventType  # noqa: E402
from ui.review_window import (  # noqa: E402
    make_label_record, load_labels, write_labels,
)


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _tiny_video(path: Path) -> None:
    """2s solid-color video via ffmpeg (like test_export)."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


@pytest.fixture
def sample_events():
    return [
        Event(EventType.GOAL, 5.0, 8.0, 6.5, confidence=0.9),
        Event(EventType.TURNOVER, 20.0, 22.0, 21.0, confidence=0.6),
        Event(EventType.SAVE, 40.0, 43.0, 41.5, confidence=0.8),
    ]


# ══════════════════════════════════════════════════════════════════════════

class TestLabelHelpers:
    def test_record_shape(self, sample_events):
        rec = make_label_record(1, sample_events[0])
        assert rec["id"] == 1
        assert rec["predicted_type"] == "goal"
        assert rec["peak_sec"] == 6.5
        assert rec["correct"] is None
        assert rec["actual_type"] is None
        assert rec["notes"] == ""
        # Keys must match what event_review.py's evaluate reads
        assert {"correct", "actual_type", "notes"} <= set(rec)

    def test_record_correct(self, sample_events):
        rec = make_label_record(0, sample_events[0], correct=True)
        assert rec["correct"] is True
        assert rec["actual_type"] is None

    def test_record_wrong_with_actual(self, sample_events):
        rec = make_label_record(
            1, sample_events[1], correct=False,
            actual_type="shot", notes="clear shot, not turnover",
        )
        assert rec["correct"] is False
        assert rec["actual_type"] == "shot"
        assert rec["notes"] == "clear shot, not turnover"

    def test_write_and_load_roundtrip(self, sample_events, tmp_path):
        out = tmp_path / "labels.jsonl"
        records = {
            i: make_label_record(i, e)
            for i, e in enumerate(sample_events)
        }
        records[1]["correct"] = True
        write_labels(out, records)
        loaded = load_labels(out)
        assert set(loaded) == {0, 1, 2}
        assert loaded[1]["correct"] is True
        # each line is valid JSON
        for line in out.read_text().splitlines():
            json.loads(line)

    def test_load_ignores_garbage_lines(self, tmp_path):
        out = tmp_path / "labels.jsonl"
        out.write_text('{"id": 0, "correct": true}\nnot json\n{"id": 1}\n')
        loaded = load_labels(out)
        assert set(loaded) == {0, 1}


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not installed")
class TestReviewWindow:
    @pytest.fixture
    def app(self, qapp):
        return qapp

    def test_labeling_writes_jsonl(self, app, sample_events, tmp_path):
        from ui.review_window import ReviewWindow
        video = tmp_path / "mini.mp4"
        _tiny_video(video)
        labels = tmp_path / "labels.jsonl"
        window = ReviewWindow(
            str(video), sample_events, labels_file=str(labels),
        )
        try:
            # label event 0 correct
            window._select(0)
            window._apply_label(True)
            # label event 1 wrong as a shot
            window._select(1)
            window.type_combo.setCurrentIndex(
                window.type_combo.findData("shot"))
            window.notes_edit.setText("was a shot")
            window._apply_label(False)

            records = load_labels(labels)
            assert records[0]["correct"] is True
            assert records[1]["correct"] is False
            assert records[1]["actual_type"] == "shot"
            assert records[1]["notes"] == "was a shot"
            # event 2 untouched
            assert records[2]["correct"] is None
        finally:
            window.done(0)

    def test_resume_loads_existing_labels(self, app, sample_events, tmp_path):
        from ui.review_window import ReviewWindow
        video = tmp_path / "mini.mp4"
        _tiny_video(video)
        labels = tmp_path / "labels.jsonl"
        write_labels(labels, {0: make_label_record(0, sample_events[0], correct=True)})
        window = ReviewWindow(
            str(video), sample_events, labels_file=str(labels),
        )
        try:
            assert window.records[0]["correct"] is True
            # list shows reviewed status for event 0
            assert "✓" in window.list_widget.item(0).text()
        finally:
            window.done(0)

    def test_auto_advance_after_label(self, app, sample_events, tmp_path):
        from ui.review_window import ReviewWindow
        video = tmp_path / "mini.mp4"
        _tiny_video(video)
        labels = tmp_path / "labels.jsonl"
        window = ReviewWindow(
            str(video), sample_events, labels_file=str(labels),
        )
        try:
            window._select(0)
            window._apply_label(True)
            assert window.current_idx == 1
        finally:
            window.done(0)
