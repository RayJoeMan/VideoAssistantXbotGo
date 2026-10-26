"""Tests for captions (highlight/captions.py): SRT IO, wrapping,
segment->cue construction, per-take replacement, and the
transcription entry point (with a fake faster-whisper module).
"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.captions import (
    cues_from_segments,
    cues_to_srt,
    format_srt_timestamp,
    merge_take_cues,
    parse_srt,
    transcribe_take_cues,
    wrap_caption_lines,
)
from highlight.project import CaptionCue


# ── SRT serialization ───────────────────────────────────────────────

def test_timestamp_format():
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"
    assert format_srt_timestamp(59.9999) == "00:01:00,000"  # ms rounding carries


def test_srt_round_trip():
    cues = [
        CaptionCue(1.0, 2.5, "First line"),
        CaptionCue(3.0, 4.25, "Two\nlines here"),
    ]
    parsed = parse_srt(cues_to_srt(cues))
    assert [(c.start, c.end, c.text) for c in parsed] == [
        (1.0, 2.5, "First line"),
        (3.0, 4.25, "Two\nlines here"),
    ]


def test_parse_srt_tolerates_missing_index_and_dot_separator():
    text = "00:00:01.000 --> 00:00:02.500\nNo index line\n"
    cues = parse_srt(text)
    assert len(cues) == 1
    assert cues[0].start == 1.0 and cues[0].end == 2.5


def test_parse_srt_rejects_block_without_timing():
    with pytest.raises(ValueError):
        parse_srt("just some text\n")


# ── wrapping ─────────────────────────────────────────────────────────

def test_wrap_short_text_single_line():
    assert wrap_caption_lines("Nice play.") == ["Nice play."]


def test_wrap_long_text_two_balanced_lines():
    lines = wrap_caption_lines("She picks up the ground ball and looks up field early")
    assert len(lines) == 2
    assert all(len(line) <= 42 for line in lines)


def test_wrap_honors_explicit_newlines_and_caps_at_two():
    assert wrap_caption_lines("line one\nline two") == ["line one", "line two"]
    assert len(wrap_caption_lines("a\nb\nc")) == 2


# ── segments -> cues ─────────────────────────────────────────────────

def test_cues_from_segments_apply_offset_and_trim():
    segments = [{"start": 0.0, "end": 2.0, "text": "  Hello there. "}]
    cues = cues_from_segments(segments, offset=5.0)
    assert len(cues) == 1
    assert cues[0].start == 5.0 and cues[0].end == 7.0
    assert cues[0].text == "Hello there."


def test_cues_from_segments_skip_empty_and_broken():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "   "},
        {"start": 2.0, "end": 2.0, "text": "zero length"},
        {"start": 3.0, "end": 4.0, "text": "kept"},
    ]
    cues = cues_from_segments(segments)
    assert [c.text for c in cues] == ["kept"]


def test_long_segment_splits_on_word_timings():
    words = [
        {"start": float(i), "end": i + 0.9, "word": f" word{i}"}
        for i in range(14)
    ]
    segments = [{"start": 0.0, "end": 14.0, "text": "long", "words": words}]
    cues = cues_from_segments(segments, max_cue_s=6.0)
    assert len(cues) == 3
    assert cues[0].start == 0.0 and cues[0].end == pytest.approx(5.9)
    assert cues[-1].end == pytest.approx(13.9)
    assert all(c.end - c.start <= 6.0 for c in cues)


def test_long_segment_without_words_stays_one_cue():
    segments = [{"start": 0.0, "end": 14.0, "text": "no word timings"}]
    cues = cues_from_segments(segments)
    assert len(cues) == 1 and cues[0].end == 14.0


# ── per-take replacement ─────────────────────────────────────────────

def test_merge_take_cues_replaces_only_the_take_span():
    existing = [
        CaptionCue(1.0, 2.0, "before"),
        CaptionCue(5.0, 6.0, "old take cue"),
        CaptionCue(9.0, 10.0, "after"),
    ]
    new = [CaptionCue(5.0, 7.0, "fresh cue")]
    merged = merge_take_cues(existing, new, 4.0, 8.0)
    assert [c.text for c in merged] == ["before", "fresh cue", "after"]


def test_merge_take_cues_keeps_cue_at_span_end_boundary():
    existing = [CaptionCue(7.5, 8.5, "midpoint exactly at span end")]
    merged = merge_take_cues(existing, [], 4.0, 8.0)
    assert len(merged) == 1


# ── transcription entry (fake faster-whisper) ────────────────────────

def test_transcribe_take_cues_with_fake_whisper(monkeypatch):
    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, path, **kwargs):
            segments = [
                SimpleNamespace(start=0.0, end=1.5, text="Nice play.", words=[])
            ]
            return segments, SimpleNamespace(language="en")

    fake = ModuleType("faster_whisper")
    fake.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)

    cues = transcribe_take_cues("take.m4a", take_start=4.0)
    assert len(cues) == 1
    assert cues[0].start == 4.0 and cues[0].end == 5.5
    assert cues[0].text == "Nice play."
