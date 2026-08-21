# Lacrosse Highlight Assistant

.PHONY: test run clean package

# ── Development ──────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v --tb=short

test-cov:
	python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

run:
	python -m src.ui.main_window

# ── CLI tools ────────────────────────────────────────────────────────────
parse-track:
	python -m src.telemetry.parser $(TRACK)

analyze:
	python -m src.analysis.detection $(TRACK) $(VIDEO)

export:
	python -m src.export.ffmpeg $(VIDEO) $(EVENTS) $(OUTPUT)

# ── Maintenance ──────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/ 2>/dev/null || true

# ── Packaging (Phase 4+) ────────────────────────────────────────────────
# Builds the desktop app as a distributable executable via scripts/build.py
# (a cross-platform wrapper around PyInstaller). Output lands in dist/.
package:                ## Build distributable app (onedir — faster startup)
	.venv/bin/python scripts/build.py

package-onefile:        ## Build single-file executable
	.venv/bin/python scripts/build.py --onefile

package-bundle-ffmpeg:  ## Bundle ffmpeg/ffprobe into the app for offline export
	.venv/bin/python scripts/build.py --bundle-ffmpeg

smoke:                  ## Build, then verify the executable launches
	.venv/bin/python scripts/build.py --smoke

icons:                  ## (Re)generate icon assets from assets/icon.svg
	.venv/bin/python scripts/make_icons.py

# ── Setup ────────────────────────────────────────────────────────────────
setup:
	pip install -r requirements.txt
