# Lacrosse Highlight Assistant

Telemetry-driven video editing assistant for lacrosse. Ingest FALCON camera
tracks, auto-detect key plays, and export highlight reels.

A **desktop application** (PyQt6) — an editing assistant that suggests and
streamlines highlight creation, not an automatic editor.

## Features

- Parse `.track` telemetry files from FALCON cameras
- Auto-detect key plays (goals, faceoffs, turnovers, penalties)
- Rank events by intensity; review and curate in a table
- Export highlight reels via FFmpeg (MP4, ProRes, GIF) with titles/slow-mo
- Batch individual clip export with sidecar metadata + manifest

## Quick Start (development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.ui.main_window   # launch the GUI
```

## Running the tests

```bash
.venv/bin/python -m pytest tests/ -v
```

## Building the executable

The app packages into a standalone desktop executable with PyInstaller.
The build uses `lacrosse_highlight_assistant.spec` (windowed GUI, no console).

```bash
# Default: onedir bundle (fast startup) → dist/Lacrosse Highlight Assistant/
make package

# Single-file executable → dist/Lacrosse Highlight Assistant
make package-onefile

# Bundle ffmpeg/ffprobe into the app so export works on machines without FFmpeg
make package-bundle-ffmpeg
```

Outputs land in `dist/`. The executable is fully self-contained except for
FFmpeg — unless you use `package-bundle-ffmpeg`, the target machine needs
`ffmpeg`/`ffprobe` on PATH (or a copy placed next to the executable, which the
app finds automatically).

### Platform notes

- **Linux / macOS**: `make package` (or `python scripts/build.py`).
- **Windows**: `\build.ps1` (or `python scripts/build.py`).
- **macOS**: builds always produce a Finder double-clickable `.app` bundle at
  `dist/Lacrosse Highlight Assistant.app`. For distribution, ad-hoc codesign
  with `codesign --force --deep --sign -` and — for wide distribution —
  notarize with an Apple Developer account.
- **Windows**: the built `.exe` may trigger a SmartScreen "Unknown publisher"
  warning until the app is code-signed.
- **Icons**: run `python scripts/make_icons.py` (or `make icons`) to generate
  `icon.ico` / `icon.icns` from `assets/icon.svg`. `icon.icns` is created
  automatically when building on macOS.

### Publishing & CI

Pushing the repo to GitHub triggers a 3-OS CI matrix (`.github/workflows/ci.yml`)
that runs tests, generates icons, builds the executable, headless-smoke-tests
it, and uploads the per-OS artifacts from `dist/`:

- `ubuntu-latest` — Linux bundle
- `windows-latest` — Windows `.exe` build
- `macos-latest` — macOS `.app` bundle

CI runs on every branch push and pull request. The intended remote (from
`pyproject.toml`) is `https://github.com/catch-tracker/lacrosse-video-assistant.git`.
If that repo doesn't exist yet, create it on GitHub, then either run:

```bash
git remote set-url origin <your-repo-url>
git push -u origin feat/executable-packaging
```

or publish the branch from VS Code's Source Control view.

## CLI tools

| Command | Purpose |
| --- | --- |
| `lva` | Launch the desktop app |
| `lva-parse` | Parse a `.track` file from the terminal |
| `lva-detect` | Run event detection on a track |
| `lva-export` | Build a highlight reel from the terminal |

## Keyboard shortcuts (GUI)

| Shortcut | Action |
| --- | --- |
| `Ctrl+O` / `Ctrl+T` | Open video / track |
| `Ctrl+D` | Detect events |
| `Ctrl+E` | Export highlight reel |
| `Space` | Play/pause (when video loaded) |
| `Ctrl+Q` | Quit |
