#!/usr/bin/env python3
"""Package the built executable into a properly named release asset.

Usage:
    python scripts/package_release.py <version>

Expected build outputs (from scripts/build.py):
  Windows (onefile): dist/Lacrosse Highlight Assistant.exe
  macOS (onedir):    dist/Lacrosse Highlight Assistant.app
  Linux (onedir):    dist/Lacrosse Highlight Assistant/

Produces in release/:
  Lacrosse-Highlight-Assistant-<ver>-Windows-x86_64.exe
  Lacrosse-Highlight-Assistant-<ver>-macOS-x86_64.zip
  Lacrosse-Highlight-Assistant-<ver>-Linux-x86_64[.tar.gz]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
APP = "Lacrosse Highlight Assistant"


def version_arg() -> str:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/package_release.py <version>")
    return sys.argv[1].lstrip("v")


def package_windows(version: str) -> Path:
    exe = DIST / f"{APP}.exe"
    if exe.exists():
        out = RELEASE / f"{APP}-{version}-Windows-x86_64.exe"
        shutil.copyfile(exe, out)
        return out
    folder = DIST / APP
    out = RELEASE / f"{APP}-{version}-Windows-x86_64.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in folder.rglob("*"):
            zf.write(p, p.relative_to(DIST))
    return out


def package_macos(version: str) -> Path:
    app = DIST / f"{APP}.app"
    out = RELEASE / f"{APP}-{version}-macOS-x86_64.zip"
    if shutil.which("ditto"):
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(out)],
            check=True,
        )
    else:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in app.rglob("*"):
                zf.write(p, p.relative_to(DIST))
    return out


def package_linux(version: str) -> Path:
    single = DIST / APP
    if single.is_file():  # onefile build → ship the single binary
        out = RELEASE / f"{APP}-{version}-Linux-x86_64"
        shutil.copyfile(single, out)
        out.chmod(0o755)
        return out
    folder = DIST / APP  # onedir build → tar.gz the folder
    out = RELEASE / f"{APP}-{version}-Linux-x86_64.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(folder, arcname=APP)
    return out


def main() -> int:
    version = version_arg()
    RELEASE.mkdir(exist_ok=True)
    if sys.platform == "win32":
        out = package_windows(version)
    elif sys.platform == "darwin":
        out = package_macos(version)
    else:
        out = package_linux(version)
    print(f"[package] {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
