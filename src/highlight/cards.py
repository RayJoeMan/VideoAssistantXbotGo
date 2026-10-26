"""Title / end cards for the dual exports (Session 3).

Cards are rasterized PNGs in the same spirit as the renderer's
overlays: PIL typesetting on a solid brand field, composited by
ffmpeg as short still segments at the head/tail of an export.  The
line builders are pure functions of the project, so the wording is
unit-testable without touching PIL; ``render_card_png`` is the only
function here that draws.

Card set (spec Feature 6):
  * recruiting end card — player name / class + position / team /
    contact, from the project's ``player`` block;
  * vertical title card — the series masthead "LACROSSE IQ with
    ABBY", plus the play's title when the project names one;
  * vertical end card — the masthead again, plus the athlete's
    handle when known.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PIL import Image, ImageDraw, ImageFont

from .project import HighlightProject

SERIES_NAME = "LACROSSE IQ with ABBY"
TITLE_CARD_S = 1.0   # spec: the vertical opens on a 1 s title card
END_CARD_S = 2.0     # both exports close on a 2 s end card

CARD_BG_RGB = (9, 32, 55)        # deep navy (Don't Be a Bump house color)
CARD_FG_RGB = (255, 255, 255)
CARD_ACCENT_RGB = (255, 199, 44)  # the ring's gold

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _load_font(size: int):
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


# ══════════════════════════════════════════════════════════════════════════
# Card wording (pure)
# ══════════════════════════════════════════════════════════════════════════

def recruiting_end_card_lines(project: HighlightProject) -> List[str]:
    """Lines for the recruiting cut's end card, biggest first.

    Empty when the project carries no player info — the export then
    ships the cut without a card rather than inventing one.
    """
    player = project.player
    if player is None:
        return []
    lines = [player.name]
    sub = []
    if player.class_year:
        sub.append(f"Class of {player.class_year}")
    if player.position:
        sub.append(player.position)
    if sub:
        lines.append(" · ".join(sub))
    if player.team:
        lines.append(player.team)
    if player.contact:
        lines.append(player.contact)
    return lines


def vertical_title_card_lines(project: HighlightProject) -> List[str]:
    """The vertical's opening card: series masthead + play title."""
    lines = [SERIES_NAME]
    if project.play_title:
        lines.append(project.play_title)
    return lines


def vertical_end_card_lines(project: HighlightProject) -> List[str]:
    """The vertical's closing card: masthead + the athlete's handle."""
    lines = [SERIES_NAME]
    if project.player is not None and project.player.handle:
        lines.append(project.player.handle)
    return lines


# ══════════════════════════════════════════════════════════════════════════
# Rasterization
# ══════════════════════════════════════════════════════════════════════════

def render_card_png(lines: List[str], path, width: int, height: int) -> Path:
    """Draw *lines* centered on a navy field; save as a PNG.

    The first line is the headline (largest, white); a gold rule
    separates it from the supporting lines when there are any.
    Sizes key off the smaller frame dimension so the same wording
    sits proportionally on a 1920x1080 end card and a 1080x1920
    title card.
    """
    if not lines:
        raise ValueError("a card needs at least one line")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), CARD_BG_RGB)
    draw = ImageDraw.Draw(img)
    base = min(width, height)
    sizes = [max(20, int(round(base * 0.072)))]
    sizes += [max(16, int(round(base * 0.044)))] * (len(lines) - 1)
    gap = int(round(base * 0.030))
    rule_h = max(3, int(round(base * 0.006)))
    rule_w = int(round(width * 0.36))

    measured = []
    total_h = 0
    for text, size in zip(lines, sizes):
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        measured.append((text, font, bbox, tw, th))
        total_h += th
    total_h += gap * (len(lines) - 1)
    if len(lines) > 1:
        total_h += gap + rule_h

    y = (height - total_h) / 2.0
    for i, (text, font, bbox, tw, th) in enumerate(measured):
        x = (width - tw) / 2.0 - bbox[0]
        draw.text((x, y - bbox[1]), text, font=font, fill=CARD_FG_RGB)
        y += th
        if i == 0 and len(lines) > 1:
            y += gap
            draw.rectangle(
                [(width - rule_w) / 2.0, y, (width + rule_w) / 2.0, y + rule_h],
                fill=CARD_ACCENT_RGB,
            )
            y += rule_h
        y += gap
    img.save(out)
    return out
