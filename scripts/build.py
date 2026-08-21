#!/usr/bin/env python3
"""Cross-platform build entry point for the Lacrosse Highlight Assistant.

Wraps PyInstaller (spec: lacrosse_highlight_assistant.spec) so the same command
works on Linux, macOS, and Windows — no shell-specific tooling required.

Usage:
    python scripts/build.py                  # onedir bundle (fast startup)
    python scripts/build.py --onefile        # single-file executable (not macOS)
    python scripts/build.py --bundle-ffmpeg  # bundle ffmpeg/ffprobe from PATH
    python scripts/build.py --smoke          # build, then verify it launches
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "lacrosse_highlight_assistant.spec"
APP_NAME = "Lacrosse Highlight Assistant"
SMOKE_SECONDS = float(os.environ.get("SMOKE_SECONDS", "8"))


def find_pyinstaller() -> str:
    """Locate the PyInstaller console script (venv first, then PATH)."""
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates.append(str(ROOT / ".venv" / "Scripts" / "pyinstaller.exe"))
    else:
        candidates.append(str(ROOT / ".venv" / "bin" / "pyinstaller"))
    candidates.append(shutil.which("pyinstaller") or "")
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("PyInstaller not found. Install it with: pip install pyinstaller")


def locate_built_executable() -> Path:
    """Find the built executable in dist/ for the current platform/layout."""
    dist = ROOT / "dist"
    suffix = ".exe" if sys.platform == "win32" else ""
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(dist / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME)
    candidates.append(dist / APP_NAME / (APP_NAME + suffix))   # onedir layout
    candidates.append(dist / (APP_NAME + suffix))              # onefile layout
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"built executable not found under {dist}")


def smoke_test(exe: Path) -> int:
    """Launch the executable headless; it must stay alive, then we kill it."""
    print(f"[smoke] launching {exe} (--headless) for {SMOKE_SECONDS:.0f}s")
    proc = subprocess.Popen([str(exe), "--headless"])
    time.sleep(SMOKE_SECONDS)
    if proc.poll() is not None:
        print(f"[smoke] FAIL: exited early with code {proc.returncode}")
        return 1
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    print(f"[smoke] PASS: stayed up {SMOKE_SECONDS:.0f}s without crashing")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Lacrosse Highlight Assistant executable."
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="build a single-file executable (ignored on macOS, which always builds a .app)",
    )
    parser.add_argument(
        "--bundle-ffmpeg",
        action="store_true",
        help="bundle ffmpeg/ffprobe found on PATH into the app",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="after building, launch the executable headless to verify it starts",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    if sys.platform != "darwin":
        env["LVA_ONE_FILE"] = "1" if args.onefile else "0"
    env["LVA_BUNDLE_FFMPEG"] = "1" if args.bundle_ffmpeg else "0"

    pyinstaller = find_pyinstaller()
    cmd = [pyinstaller, "--noconfirm", str(SPEC)]
    print(f"[build] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    if args.smoke:
        return smoke_test(locate_built_executable())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
