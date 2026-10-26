"""Captions — SRT data, faster-whisper transcription, the edit pass.

Caption cues live IN the project file (project.CaptionCue) on the
OUTPUT timeline — the same clock as the voiceover takes they were
transcribed from.  This module owns everything around that data:

  * SRT serialization (``cues_to_srt`` / ``parse_srt`` / file IO) —
    the rendered .srt sidecar, and the format a human editor can
    round-trip for the edit pass the spec requires (names/terms get
    fixed by a person before the final render);
  * line wrapping for burn-in (bold white, black outline, lower
    third, max 2 lines — the renderer draws from ``wrap_caption_lines``);
  * transcription: a VO take -> cues via a local faster-whisper model
    (lazy import; the package is an optional dependency), with word
    timings used to split long segments into readable cues.

CLI: ``python -m highlight.captions project.json [--take-index N]
[--model small] [--language en]`` transcribes the project's VO takes
and stores the cues back into project.json.  Re-running for a take
replaces the cues inside that take's span (see ``merge_take_cues``),
so the command is idempotent per take; hand-edited cues outside every
re-transcribed span survive.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .project import CaptionCue, HighlightProject, load_project, save_project

MAX_CUE_S = 6.0        # longest single cue on screen
MAX_CUE_CHARS = 84     # ~2 lines x 42 chars
WRAP_CHARS = 42        # per burned-in line

_TIMESTAMP_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})"
)


# ══════════════════════════════════════════════════════════════════════════
# SRT serialization
# ══════════════════════════════════════════════════════════════════════════

def format_srt_timestamp(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS,mmm`` (SRT style)."""
    total_ms = int(round(max(float(seconds), 0.0) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _parse_srt_timestamp(text: str) -> float:
    match = _TIMESTAMP_RE.search(text.strip())
    if not match:
        raise ValueError(f"bad SRT timestamp {text!r}")
    hours, minutes, secs, ms = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + secs + ms / 1000.0


def cues_to_srt(cues: Sequence[CaptionCue]) -> str:
    """Serialize cues (sorted by start) as an SRT document."""
    blocks = []
    for i, cue in enumerate(sorted(cues, key=lambda c: c.start), start=1):
        blocks.append(
            f"{i}\n"
            f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}\n"
            f"{cue.text.strip()}\n"
        )
    return "\n".join(blocks) + ("\n" if blocks else "")


def parse_srt(text: str) -> List[CaptionCue]:
    """Parse an SRT document back into cues (sorted by start).

    Tolerant of a missing numeric index line and of '.' millisecond
    separators, since the file may come back from a human editor.
    """
    cues: List[CaptionCue] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", normalized.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        timing_at = next(
            (i for i, ln in enumerate(lines) if "-->" in ln), None
        )
        if timing_at is None:
            raise ValueError(f"SRT block has no timing line: {block!r}")
        start_text, end_text = lines[timing_at].split("-->", 1)
        body = "\n".join(lines[timing_at + 1:]).strip()
        cues.append(
            CaptionCue(
                start=_parse_srt_timestamp(start_text),
                end=_parse_srt_timestamp(end_text),
                text=body,
            )
        )
    return sorted(cues, key=lambda c: c.start)


def write_srt(cues: Sequence[CaptionCue], path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cues_to_srt(cues), encoding="utf-8")
    return out


def read_srt(path) -> List[CaptionCue]:
    return parse_srt(Path(path).read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# Burn-in wrapping
# ══════════════════════════════════════════════════════════════════════════

def wrap_caption_lines(text: str, max_chars: int = WRAP_CHARS) -> List[str]:
    """Wrap cue text into at most two display lines.

    Explicit newlines (from the edit pass) are honored first.  The
    split point is chosen to balance line lengths; a cue that still
    overflows puts the remainder on line two, which may run long —
    two lines is the hard rule, width is the soft one.
    """
    flat = " ".join(text.split())
    if not flat:
        return []
    explicit = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if len(explicit) >= 2:
        return [" ".join(explicit[:-1]), explicit[-1]] if len(explicit) > 2 else explicit
    if len(flat) <= max_chars:
        return [flat]
    words = flat.split()
    best = None  # (overflow, balance, split_index)
    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])
        overflow = max(len(line1), len(line2)) - max_chars
        balance = abs(len(line1) - len(line2))
        key = (max(overflow, 0), balance)
        if best is None or key < best[0]:
            best = (key, i)
    i = best[1]
    return [" ".join(words[:i]), " ".join(words[i:])]


# ══════════════════════════════════════════════════════════════════════════
# Transcription (faster-whisper segments -> cues)
# ══════════════════════════════════════════════════════════════════════════

def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _word_chunks(words, max_cue_s: float, max_chars: int):
    """Group word dicts/objects into (start, end, text) cue chunks."""
    chunks = []
    current = []
    for word in words:
        w_start = float(_get(word, "start", 0.0))
        w_end = float(_get(word, "end", w_start))
        w_text = str(_get(word, "word", "")).strip()
        if not w_text:
            continue
        entry = (w_start, w_end, w_text)
        if current:
            span = w_end - current[0][0]
            text_len = len(" ".join(w[2] for w in current)) + 1 + len(w_text)
            if span > max_cue_s or text_len > max_chars:
                chunks.append(current)
                current = []
        current.append(entry)
    if current:
        chunks.append(current)
    return [
        (chunk[0][0], chunk[-1][1], " ".join(w[2] for w in chunk))
        for chunk in chunks
    ]


def cues_from_segments(
    segments,
    offset: float = 0.0,
    max_cue_s: float = MAX_CUE_S,
    max_chars: int = MAX_CUE_CHARS,
) -> List[CaptionCue]:
    """Build cues from faster-whisper segments (objects or dicts).

    One cue per segment, except segments that run long or wide, which
    are split on their word timings.  *offset* (the take's start on
    the output timeline) is added to every time.
    """
    cues: List[CaptionCue] = []
    for segment in segments:
        text = str(_get(segment, "text", "")).strip()
        if not text:
            continue
        start = float(_get(segment, "start", 0.0))
        end = float(_get(segment, "end", start))
        if end <= start:
            continue
        words = _get(segment, "words") or []
        if words and (end - start > max_cue_s or len(text) > max_chars):
            pieces = _word_chunks(words, max_cue_s, max_chars)
        else:
            pieces = [(start, end, text)]
        for p_start, p_end, p_text in pieces:
            if p_end <= p_start or not p_text.strip():
                continue
            cues.append(
                CaptionCue(
                    start=offset + p_start,
                    end=offset + p_end,
                    text=p_text.strip(),
                )
            )
    return sorted(cues, key=lambda c: c.start)


def merge_take_cues(
    existing: Sequence[CaptionCue],
    new_cues: Sequence[CaptionCue],
    span_start: float,
    span_end: float,
) -> List[CaptionCue]:
    """Replace the cues inside one take's span with *new_cues*.

    An old cue is dropped when its midpoint falls inside
    [span_start, span_end) — the span the take occupies — so cues a
    human edited elsewhere in the clip are untouched.
    """
    kept = [
        cue
        for cue in existing
        if not (span_start <= (cue.start + cue.end) / 2.0 < span_end)
    ]
    return sorted([*kept, *new_cues], key=lambda c: c.start)


def transcribe_take_cues(
    take_file,
    take_start: float,
    model_size: str = "small",
    language: Optional[str] = None,
) -> List[CaptionCue]:
    """Transcribe one VO take locally and return its cues, offset by
    *take_start* onto the output timeline.

    faster-whisper is an optional dependency, imported lazily; a
    missing install raises RuntimeError with the remedy.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed; install it with "
            "`pip install faster-whisper` to transcribe captions"
        ) from None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(take_file),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    return cues_from_segments(segments, offset=take_start)


# ══════════════════════════════════════════════════════════════════════════
# CLI: fill a project's captions from its VO takes
# ══════════════════════════════════════════════════════════════════════════

def fill_project_captions(
    project: HighlightProject,
    take_indexes: Optional[Sequence[int]] = None,
    model_size: str = "small",
    language: Optional[str] = None,
) -> int:
    """Transcribe the selected takes into project.captions (in place).

    Returns the number of cues written.  Each take's old cues (by
    span) are replaced, so re-running is safe.
    """
    from .audio import probe_duration  # local: keeps module import light

    if project.voiceover is None or not project.voiceover.takes:
        raise ValueError("project has no voiceover takes to transcribe")
    takes = project.voiceover.takes
    selected = (
        list(range(len(takes))) if take_indexes is None else list(take_indexes)
    )
    written = 0
    for index in selected:
        take = takes[index]
        cues = transcribe_take_cues(
            take.file, take.start, model_size=model_size, language=language
        )
        duration = probe_duration(take.file)
        span_end = take.start + duration if duration else float("inf")
        project.captions = merge_take_cues(
            project.captions, cues, take.start, span_end
        )
        written += len(cues)
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lva-captions",
        description="Transcribe a highlight project's VO takes into caption cues.",
    )
    parser.add_argument("project", help="path to project.json")
    parser.add_argument("--take-index", type=int, default=None,
                        help="only this take (default: all takes)")
    parser.add_argument("--model", default="small",
                        help="faster-whisper model size (default: small)")
    parser.add_argument("--language", default=None,
                        help="language code (default: auto-detect)")
    args = parser.parse_args(argv)

    project = load_project(args.project)
    indexes = None if args.take_index is None else [args.take_index]
    try:
        count = fill_project_captions(
            project, take_indexes=indexes,
            model_size=args.model, language=args.language,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    save_project(project, args.project)
    print(f"wrote {count} caption cues into {args.project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
