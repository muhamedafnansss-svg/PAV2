"""
VAL Memory Monitor v6
======================
Background watchdog that polls RAM every 30s and triggers GC + alerts.
Delegates all budget decisions to ram_guard.py.
"""

import time, threading
from pathlib import Path
from typing import Optional

from val.utils.logger import get_logger, LogCategory
from val.utils.ram_guard import (
    ram_pct, ram_used_gb, pressure_tier, run_gc, WARN_PCT, REJECT_PCT,
)

logger = get_logger('memory_monitor', LogCategory.SYSTEM)

MAX_LOG_SIZE_BYTES = 2 * 1024 * 1024
LOG_MAX_AGE_DAYS   = 3


def cleanup_old_logs(log_dir: Optional[Path] = None) -> int:
    if log_dir is None:
        from val.config.settings import LOGS_DIR
        log_dir = LOGS_DIR
    if not log_dir.exists():
        return 0
    cutoff = time.time() - (LOG_MAX_AGE_DAYS * 86400)
    cleaned = 0
    for f in log_dir.glob('*.jsonl'):
        try:
            st = f.stat()
            if st.st_mtime < cutoff:
                f.unlink(); cleaned += 1; continue
            if st.st_size > MAX_LOG_SIZE_BYTES:
                lines = f.read_text(encoding='utf-8', errors='replace').splitlines()
                f.write_text('\n'.join(lines[-500:]) + '\n', encoding='utf-8')
                cleaned += 1
        except Exception as e:
            logger.warning(f'Log cleanup error {f}: {e}')
    return cleaned


class MemoryWatchdog(threading.Thread):
    def __init__(self, poll_interval_s: float = 30.0):
        super().__init__(daemon=True, name='val-memory-watchdog')
        self._poll  = poll_interval_s
        self._stop  = threading.Event()
        self._last_cleanup = 0.0

    def run(self) -> None:
        logger.info('MemoryWatchdog started')
        cleanup_old_logs()
        self._last_cleanup = time.time()
        while not self._stop.wait(self._poll):
            try:
                pct  = ram_pct()
                used = ram_used_gb()
                tier = pressure_tier()
                if pct >= REJECT_PCT:
                    logger.warning(f'RAM CRITICAL {pct:.1f}% -- REJECT tier active')
                    run_gc(3, 'watchdog-critical')
                elif pct >= WARN_PCT:
                    logger.warning(f'RAM HIGH {pct:.1f}% -- ultra_low tier, {used:.1f}GB used')
                    run_gc(2, 'watchdog-high')
                else:
                    logger.debug(f'RAM OK {pct:.1f}% ({tier})')
                if time.time() - self._last_cleanup > 21600:
                    cleanup_old_logs()
                    self._last_cleanup = time.time()
            except Exception as e:
                logger.error(f'MemoryWatchdog error: {e}')

    def stop(self) -> None:
        self._stop.set()


_watchdog: Optional[MemoryWatchdog] = None


def start_watchdog(poll_interval_s: float = 30.0) -> MemoryWatchdog:
    global _watchdog
    if _watchdog is None or not _watchdog.is_alive():
        _watchdog = MemoryWatchdog(poll_interval_s=poll_interval_s)
        _watchdog.start()
    return _watchdog


def stop_watchdog() -> None:
    global _watchdog
    if _watchdog and _watchdog.is_alive():
        _watchdog.stop()
        _watchdog = None
