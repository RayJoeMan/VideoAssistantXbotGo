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
import sys

block_cipher = None

APP_NAME = "Lacrosse Highlight Assistant"
ENTRY = ["src/ui/main_window.py"]

# macOS always builds a Finder double-clickable .app (onedir + BUNDLE);
# PyInstaller cannot produce a onefile .app, so ignore LVA_ONE_FILE there.
if sys.platform == "darwin":
    ONE_FILE = False
else:
    ONE_FILE = os.environ.get("LVA_ONE_FILE", "0") == "1"
BUNDLE_FFMPEG = os.environ.get("LVA_BUNDLE_FFMPEG", "0") == "1"

ASSETS = os.path.join(SPECPATH, "assets")

# Platform-specific icon (Windows .ico, macOS .icns); generated from
# assets/icon.svg by scripts/make_icons.py.
ICON = None
if sys.platform == "win32":
    _ico = os.path.join(ASSETS, "icon.ico")
    if os.path.exists(_ico):
        ICON = _ico
elif sys.platform == "darwin":
    _icns = os.path.join(ASSETS, "icon.icns")
    if os.path.exists(_icns):
        ICON = _icns

datas = [("README.md", ".")]
# Bundle the PNG so the app can set its window/taskbar icon at runtime.
_png = os.path.join(ASSETS, "icon.png")
if os.path.exists(_png):
    datas.append((_png, "assets"))
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
        icon=ICON,
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
        icon=ICON,
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

# macOS: wrap the onedir build in a proper .app bundle (double-clickable in
# Finder). PyInstaller only processes BUNDLE on macOS.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APP_NAME + ".app",
        icon=ICON,
        bundle_identifier="com.catchtracker.lacrosse-highlight-assistant",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "CFBundleDisplayName": APP_NAME,
            "NSHighResolutionCapable": True,
        },
    )
