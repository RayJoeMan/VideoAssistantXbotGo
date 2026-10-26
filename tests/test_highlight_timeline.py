"""Tests for the beats output timeline (highlight/timeline.py).

Pure math: segment tiling and the output<->source clock mappings,
including equivalence with the Session 1 frame clock when no beats
are present.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highlight.project import Beat, ClipWindow, HighlightProject, Keyframe
from highlight.render import frame_source_time
from highlight.timeline import SEG_FREEZE, SEG_PLAY, build_timeline


def test_no_beats_duration_is_freeze_plus_window():
    tl = build_timeline(100.0, 125.0, 1.0, [])
    assert tl.duration == pytest.approx(26.0)
    assert [s.kind for s in tl.segments] == [SEG_FREEZE, SEG_PLAY]


def test_no_beats_mapping_matches_session1_clock():
    project = HighlightProject(
        source_video="game.mp4",
        window=ClipWindow(100.0, 125.0),
        keyframes=[Keyframe(100.0, 0.5, 0.5), Keyframe(125.0, 0.5, 0.5)],
        freeze_intro_s=1.0,
    )
    tl = build_timeline(100.0, 125.0, 1.0, [])
    for frame in range(0, 781, 37):
        assert tl.source_time_at_output(frame / 30.0) == pytest.approx(
            frame_source_time(project, frame, 30)
        )


def test_mapping_clamps_to_window():
    tl = build_timeline(100.0, 125.0, 1.0, [])
    assert tl.source_time_at_output(-5.0) == 100.0
    assert tl.source_time_at_output(999.0) == 125.0


def test_slowmo_stretches_duration_and_mapping():
    tl = build_timeline(0.0, 20.0, 0.0, [Beat("slowmo", 5.0, 9.0, rate=0.5)])
    assert tl.duration == pytest.approx(24.0)  # 5 + (4 / 0.5) + 11
    assert tl.source_time_at_output(5.0) == pytest.approx(5.0)
    assert tl.source_time_at_output(9.0) == pytest.approx(7.0)   # halfway, half speed
    assert tl.source_time_at_output(13.0) == pytest.approx(9.0)  # segment end
    assert tl.source_time_at_output(24.0) == pytest.approx(20.0)


def test_freeze_holds_source_time():
    tl = build_timeline(0.0, 20.0, 0.0, [Beat("freeze", 10.0, duration=2.0)])
    assert tl.duration == pytest.approx(22.0)
    assert tl.source_time_at_output(10.0) == pytest.approx(10.0)
    assert tl.source_time_at_output(11.5) == pytest.approx(10.0)  # still held
    assert tl.source_time_at_output(12.0) == pytest.approx(10.0)  # hold ends here
    assert tl.source_time_at_output(13.0) == pytest.approx(11.0)  # rolling again


def test_combined_timeline_tiles_without_gaps():
    beats = [Beat("slowmo", 5.0, 9.0, rate=0.5), Beat("freeze", 12.0, duration=1.5)]
    tl = build_timeline(0.0, 20.0, 1.0, beats)
    # intro 1 + play 5 + slowmo 8 + play 3 + freeze 1.5 + play 8
    assert tl.duration == pytest.approx(26.5)
    assert len(tl.segments) == 6
    cursor = 0.0
    for seg in tl.segments:
        assert seg.out_start == pytest.approx(cursor)
        cursor += seg.out_duration
    assert cursor == pytest.approx(tl.duration)


def test_output_time_at_source_inverts_play_and_slowmo():
    tl = build_timeline(0.0, 20.0, 0.0, [Beat("slowmo", 5.0, 9.0, rate=0.5)])
    assert tl.output_time_at_source(2.0) == pytest.approx(2.0)
    assert tl.output_time_at_source(7.0) == pytest.approx(9.0)
    assert tl.output_time_at_source(9.0) == pytest.approx(13.0)
    assert tl.output_time_at_source(20.0) == pytest.approx(24.0)
    for src_t in (0.0, 3.0, 6.0, 8.5, 15.0, 20.0):
        out_t = tl.output_time_at_source(src_t)
        assert tl.source_time_at_output(out_t) == pytest.approx(src_t)


def test_output_time_at_source_freeze_is_hold_start():
    tl = build_timeline(0.0, 20.0, 0.0, [Beat("freeze", 10.0, duration=2.0)])
    assert tl.output_time_at_source(10.0) == pytest.approx(10.0)
    assert tl.output_time_at_source(15.0) == pytest.approx(17.0)


def test_builder_rejects_overlapping_beats_directly():
    with pytest.raises(ValueError):
        build_timeline(0.0, 20.0, 0.0,
                       [Beat("slowmo", 5.0, 10.0), Beat("slowmo", 8.0, 12.0)])


def test_zero_freeze_intro_has_no_freeze_segment():
    tl = build_timeline(0.0, 10.0, 0.0, [])
    assert [s.kind for s in tl.segments] == [SEG_PLAY]
    assert tl.duration == pytest.approx(10.0)
