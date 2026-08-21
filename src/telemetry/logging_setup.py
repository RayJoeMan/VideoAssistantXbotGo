"""
Structured logging and debugging infrastructure.

Provides consistent logging across all modules with:
- Configurable levels (DEBUG, INFO, WARN, ERROR) via --debug flag
- JSON-lines format for machine parsing
- Console output (colorized for humans) + file output (JSON for tools)
- FFmpeg stderr capture with [ffmpeg] prefix
- Crash dump on unhandled exceptions
- Module-level loggers with contextual metadata

Usage:
    from src.telemetry.logging_setup import get_logger, configure_logging

    configure_logging(level="DEBUG", log_file="app.log")
    log = get_logger(__name__)
    log.info("parsing track file", file="game1.track", frames=5400)
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Module-level state ───────────────────────────────────────────────────

_log_initialized = False
_log_file_path: Optional[Path] = None


# ── JSON Formatter ───────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit log records as JSON lines with structured context.
    
    Console output is colorized with level prefixes.
    File output is pure JSON lines (one record per line).
    """
    
    LEVEL_COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"
    
    def __init__(self, *, colorize: bool = True):
        super().__init__()
        self.colorize = colorize
    
    def format(self, record: logging.LogRecord) -> str:
        # Build structured record
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        
        # Attach any extra context passed via `extra=` kwarg
        for key in ("file", "frame", "event", "duration_ms", "error",
                     "expected", "actual", "context"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        
        # Attach exception info if present
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
            entry["traceback"] = traceback.format_exception(*record.exc_info)
        
        # Colorize for console
        if self.colorize:
            color = self.LEVEL_COLORS.get(record.levelname, "")
            prefix = f"{color}[{record.levelname}]{self.RESET}"
            return f"{prefix} {record.getMessage()}"
        
        return json.dumps(entry, default=str)


# ── FFmpeg Log Adapter ───────────────────────────────────────────────────

class FFmpegLogAdapter(logging.LoggerAdapter):
    """Prefix log messages with [ffmpeg] for FFmpeg stderr capture."""
    
    def process(self, msg, kwargs):
        return f"[ffmpeg] {msg}", kwargs


# ── Configuration ────────────────────────────────────────────────────────

def configure_logging(
    level: str = "INFO",
    log_file: Optional[str | Path] = None,
    colorize: bool = True,
) -> None:
    """Configure global logging for the application.
    
    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL
        log_file: Path to write JSON-lines log output (None = console only)
        colorize: Whether to colorize console output
    """
    global _log_initialized, _log_file_path
    
    if _log_initialized:
        return
    
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove any existing handlers
    root.handlers.clear()
    
    # Console handler (colorized, human-readable)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_handler.setFormatter(JsonFormatter(colorize=colorize))
    root.addHandler(console_handler)
    
    # File handler (JSON-lines, machine-parseable)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_file_path = log_path
        
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always DEBUG for file
        file_handler.setFormatter(JsonFormatter(colorize=False))
        root.addHandler(file_handler)
    
    _log_initialized = True
    
    # Register crash handler
    _install_excepthook()
    
    log = get_logger(__name__)
    log.info("logging configured: %s, file=%s", level, str(log_file) if log_file else "none")


# ── Logger Factory ───────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module, auto-configured with structured context.
    
    Args:
        name: Usually __name__ from the calling module
    
    Returns:
        A standard logging.Logger (use .debug(), .info(), .warning(), .error())
    """
    return logging.getLogger(name)


def get_ffmpeg_logger() -> logging.LoggerAdapter:
    """Get a logger for FFmpeg stderr output with [ffmpeg] prefix."""
    return FFmpegLogAdapter(logging.getLogger("ffmpeg"), {})


# ── Crash Handler ────────────────────────────────────────────────────────

def _install_excepthook() -> None:
    """Install a crash dump handler for unhandled exceptions."""
    original_hook = sys.excepthook
    
    def crash_handler(exc_type, exc_value, exc_tb):
        # Write crash dump
        crash_path = Path(f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
        try:
            with open(crash_path, "w") as f:
                f.write(f"Crash time: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Platform: {sys.platform}\n")
                f.write(f"Exception: {exc_type.__name__}: {exc_value}\n\n")
                f.write("Traceback:\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n\nLocal variables:\n")
                if exc_tb:
                    f.write(str(exc_tb.tb_frame.f_locals))
            sys.stderr.write(f"\n💥 Crash dump written to {crash_path}\n")
        except Exception:
            pass
        
        # Call original hook
        original_hook(exc_type, exc_value, exc_tb)
    
    sys.excepthook = crash_handler


# ── Convenience ──────────────────────────────────────────────────────────

def log_parse_error(
    log: logging.Logger,
    frame_num: int,
    field: str,
    expected: str,
    actual: str,
    line: str = "",
) -> None:
    """Log a structured telemetry parse error.
    
    Args:
        log: Logger instance
        frame_num: Frame number where error occurred
        field: Field name that failed to parse
        expected: Expected format description
        actual: Actual value encountered
        line: Raw line from the track file (truncated to 200 chars)
    """
    log.warning(
        f"parse error at frame {frame_num}: {field} — expected {expected}, got {actual!r}",
        extra={
            "frame": frame_num,
            "field": field,
            "expected": expected,
            "actual": str(actual)[:200],
            "line": line[:200] if line else "",
        },
    )
