"""VAL Utils Package"""
from .logger import get_logger, ValLogger, LogCategory

# ── memory_monitor public API (new lean version) ──────────────────────────────
from .memory_monitor import (
    cleanup_old_logs,
    start_watchdog,
    stop_watchdog,
)

# ── Backward-compat shims — old callers still work ────────────────────────────
# Functions moved to ram_guard; re-exported here so existing imports don't break.
from .ram_guard import (
    ram_used_gb        as _ram_used_gb,
    ram_pct            as _ram_pct,
    run_gc             as aggressive_gc,
    MAX_RAM_GB         as TOTAL_LIMIT_GB,
    snapshot           as _snapshot,
)

import time as _time

# Constants that used to live in memory_monitor
VRAM_LIMIT_GB = 5.0
RAM_LIMIT_GB  = 5.0

def get_memory_usage() -> float:
    """Total system RAM used in GB (replaces old RAM+VRAM metric)."""
    return _ram_used_gb()

def get_memory_snapshot():
    """Return a RamSnapshot (superset of the old MemorySnapshot)."""
    return _snapshot()

def get_memory_pressure_model():
    """Return forced model name under pressure, or None."""
    from .ram_guard import pressure_tier
    tier = pressure_tier()
    if tier == "ultra_low":
        return "tinyllama"
    if tier == "low":
        return "gemma"
    return None

def is_within_budget():
    """Return (bool, used_gb). True if RAM below hard cap."""
    used = _ram_used_gb()
    return used <= TOTAL_LIMIT_GB, used

class MemoryGuard:
    """
    Backward-compat no-op context manager.
    Real budget enforcement now happens inside ModelOrchestrator._pre_exec_check().
    """
    def __init__(self, label: str = "operation", strict: bool = False):
        self._label = label

    def __enter__(self):
        return self

    def __exit__(self, *_):
        aggressive_gc()
        return False


__all__ = [
    # logger
    "get_logger", "ValLogger", "LogCategory",
    # memory (compat)
    "get_memory_usage", "get_memory_snapshot", "get_memory_pressure_model",
    "is_within_budget", "aggressive_gc", "MemoryGuard",
    # monitor
    "cleanup_old_logs", "start_watchdog", "stop_watchdog",
    # constants
    "TOTAL_LIMIT_GB", "VRAM_LIMIT_GB", "RAM_LIMIT_GB",
]
