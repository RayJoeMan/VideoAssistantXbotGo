#!/usr/bin/env python3
"""Generate application icon assets from assets/icon.svg.

Produces (into assets/):
  icon.png           512x512 — used at runtime for the window/taskbar icon
  icon.ico           Windows multi-size ICO (requires Pillow)
  icon.icns          macOS icon (requires macOS `iconutil`). On other
                     platforms the intermediate icon.iconset/ is written so the
                     .icns can be produced on a Mac:
                       iconutil -c icns assets/icon.iconset -o assets/icon.icns

Usage:
    python scripts/make_icons.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SVG = ASSETS / "icon.svg"
PNG = ASSETS / "icon.png"
ICO = ASSETS / "icon.ico"
ICNS = ASSETS / "icon.icns"
ICONSET = ASSETS / "icon.iconset"

RENDER_SIZE = 1024
PNG_SIZE = 512


def render_png() -> None:
    """Render the SVG to a high-res PNG via QtSvg (PyQt6)."""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    if not SVG.exists():
        raise SystemExit(f"missing source icon: {SVG}")
    renderer = QSvgRenderer(str(SVG))
    image = QImage(RENDER_SIZE, RENDER_SIZE, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, RENDER_SIZE, RENDER_SIZE))
    painter.end()
    if not image.save(str(PNG)):
        raise SystemExit(f"failed to render {PNG}")
    print(f"wrote {PNG}")


def make_ico() -> None:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed — skipping icon.ico (pip install pillow)")
        return
    image = Image.open(PNG).convert("RGBA")
    image.save(
        ICO,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {ICO}")


def make_icns() -> None:
    from PIL import Image

    ICONSET.mkdir(exist_ok=True)
    image = Image.open(PNG).convert("RGBA")
    for size in (16, 32, 128, 256, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            ICONSET / f"icon_{size}x{size}.png"
        )
        if size * 2 <= 1024:
            image.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
                ICONSET / f"icon_{size}x{size}@2x.png"
            )
    if sys.platform == "darwin" and shutil.which("iconutil"):
        subprocess.run(
            ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)], check=True
        )
        print(f"wrote {ICNS}")
    else:
        print(
            f"wrote {ICONSET}/ — convert on macOS with: "
            "iconutil -c icns assets/icon.iconset -o assets/icon.icns"
        )


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    render_png()
    make_ico()
    make_icns()
    print("icons done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
