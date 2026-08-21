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
package:
	pyinstaller --name="Lacrosse Highlight Assistant" \
		--windowed \
		--add-data "README.md:." \
		src/ui/main_window.py

# ── Setup ────────────────────────────────────────────────────────────────
setup:
	pip install -r requirements.txt
