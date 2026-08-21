# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Lacrosse Highlight Assistant.

Build with:
    pyinstaller --noconfirm lacrosse_highlight_assistant.spec

Environment knobs (set before building):
    LVA_ONE_FILE=1        Single-file executable (slower startup, one binary).
                          Default is onedir (faster startup, folder layout).
    LVA_BUNDLE_FFMPEG=1   Bundle ffmpeg/ffprobe found on PATH into the app so
                          highlight export works on machines without FFmpeg.

The produced executable is a windowed GUI app (no console window).
"""

import os
import shutil

block_cipher = None

APP_NAME = "Lacrosse Highlight Assistant"
ENTRY = ["src/ui/main_window.py"]

ONE_FILE = os.environ.get("LVA_ONE_FILE", "0") == "1"
BUNDLE_FFMPEG = os.environ.get("LVA_BUNDLE_FFMPEG", "0") == "1"

datas = [("README.md", ".")]
binaries = []
hiddenimports = []

# ── Optional: bundle ffmpeg/ffprobe for offline export ─────────────────
if BUNDLE_FFMPEG:
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            binaries.append((path, "."))
            print(f"[spec] bundling {tool} from {path}")
        else:
            print(f"[spec] WARNING: LVA_BUNDLE_FFMPEG=1 but '{tool}' not on PATH; skipping")

a = Analysis(
    ENTRY,
    pathex=["src"],  # project packages live under src/ (telemetry, analysis, export)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONE_FILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=APP_NAME,
    )
