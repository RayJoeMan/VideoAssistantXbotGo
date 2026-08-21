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
