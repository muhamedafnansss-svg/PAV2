"""
VAL Logger — Fixed Edition
===========================
Fix: JSONLHandler.stream is None when RotatingFileHandler closes the stream
     during a rollover check. Guard all writes with a stream-open check.
"""

import logging
import logging.handlers
import json
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

from val.config.settings import LOGS_DIR, get_config


class LogCategory(str, Enum):
    SYSTEM    = "system"
    AGENT     = "agent"
    ERRORS    = "errors"
    SECURITY  = "security"
    INFERENCE = "inference"


# ─── JSONL Handler (fixed) ────────────────────────────────────────────────────

class JSONLHandler(logging.handlers.RotatingFileHandler):
    """Writes log records as structured JSONL entries."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Ensure file is open before writing
            if self.stream is None:
                try:
                    self.stream = self._open()
                except Exception:
                    self.handleError(record)
                    return

            entry = {
                "ts":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
                "level":    record.levelname,
                "category": getattr(record, "category", "system"),
                "logger":   record.name,
                "msg":      record.getMessage(),
            }
            if record.exc_info:
                entry["exc"] = traceback.format_exception(*record.exc_info)
            if hasattr(record, "extra"):
                entry["extra"] = record.extra

            # Check rollover BEFORE writing (correct order)
            if self.shouldRollover(record):
                self.doRollover()

            # After rollover, stream may have changed — check again
            if self.stream is None:
                self.stream = self._open()

            self.stream.write(json.dumps(entry, default=str) + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)


# ─── Logger Factory ───────────────────────────────────────────────────────────

_loggers: Dict[str, logging.Logger] = {}
_initialized = False


def _init_logging() -> None:
    global _initialized
    if _initialized:
        return

    cfg = get_config()
    log_cfg = cfg.logging
    level = getattr(logging, log_cfg.level.upper(), logging.INFO)
    log_dir = Path(log_cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("val")
    root.setLevel(level)
    root.propagate = False

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    ))
    root.addHandler(console)

    # Per-category JSONL files
    if log_cfg.enable_jsonl:
        max_bytes = log_cfg.max_file_mb * 1024 * 1024
        for cat in log_cfg.categories:
            fh = JSONLHandler(
                filename=log_dir / f"{cat}.jsonl",
                maxBytes=max_bytes,
                backupCount=log_cfg.backup_count,
                encoding="utf-8",
            )
            fh.setLevel(level)
            root.addHandler(fh)

    _initialized = True


def get_logger(name: str, category: LogCategory = LogCategory.SYSTEM) -> "ValLogger":
    """Get or create a named VAL logger."""
    _init_logging()
    return ValLogger(name, category)


class ValLogger:
    """
    Thin wrapper around Python logging with VAL-specific category support
    and structured extra fields.
    """

    def __init__(self, name: str, category: LogCategory = LogCategory.SYSTEM):
        _init_logging()
        self._logger = logging.getLogger(f"val.{name}")
        self._category = category

    def _log(self, level: int, msg: str, extra: Optional[Dict[str, Any]] = None, **kwargs):
        record_extra = {"category": self._category.value}
        if extra:
            record_extra["extra"] = extra
        try:
            self._logger.log(level, msg, extra=record_extra, **kwargs)
        except Exception:
            # Never crash the caller due to logging errors
            pass

    def debug(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.DEBUG, msg, extra)

    def info(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.INFO, msg, extra)

    def warning(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.WARNING, msg, extra)

    def error(self, msg: str, extra: Optional[Dict] = None, exc_info: bool = False):
        self._log(logging.ERROR, msg, extra, exc_info=exc_info)

    def critical(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.CRITICAL, msg, extra)

    def security(self, msg: str, extra: Optional[Dict] = None):
        """Dedicated entry point for security events."""
        self._category = LogCategory.SECURITY
        self._log(logging.WARNING, f"[SECURITY] {msg}", extra)

    def inference(self, msg: str, extra: Optional[Dict] = None):
        """Log inference metadata: model, tokens, latency."""
        self._category = LogCategory.INFERENCE
        self._log(logging.DEBUG, f"[INFERENCE] {msg}", extra)
