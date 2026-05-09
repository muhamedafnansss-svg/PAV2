"""
VAL Watchdog — Production RAM/CPU Monitor
==========================================
Background asyncio task. Runs every 5 seconds.

Thresholds (hard — no negotiation):
  RAM > 90%  → emit WARNING, request governor to unload active model
  RAM > 95%  → emit CRITICAL, set REJECT_MODE flag (all requests blocked)
  CPU > 95% for 10s → emit BACKPRESSURE signal

Health contract:
  - watchdog.is_healthy()  → bool   (used by /status endpoint)
  - watchdog.is_rejecting() → bool  (used by request gate)
  - watchdog.snapshot()    → dict   (full diagnostic)

Design rules:
  - Never raises. Any internal exception is caught and logged.
  - Never blocks. All operations are async or CPU-only.
  - Stateless externally: callers read atomic flags only.
  - governor is injected at start() to allow forced unload.
"""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("val.watchdog")

# ─── Thresholds ────────────────────────────────────────────────────────────────

RAM_WARN_PCT     = 90.0   # request governor unload
RAM_REJECT_PCT   = 95.0   # block all new requests
CPU_DANGER_PCT   = 95.0   # backpressure signal
CPU_DANGER_SECS  = 10.0   # consecutive seconds above CPU threshold before alerting
POLL_INTERVAL_S  = 5.0    # polling cadence


# ─── Snapshot ─────────────────────────────────────────────────────────────────

@dataclass
class SystemSnapshot:
    ram_used_gb:   float
    ram_pct:       float
    ram_free_gb:   float
    cpu_pct:       float
    is_healthy:    bool
    is_rejecting:  bool
    tier:          str           # 'normal' | 'warn' | 'critical'
    model_loaded:  Optional[str]
    timestamp:     float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "ram_used_gb":  round(self.ram_used_gb, 2),
            "ram_pct":      round(self.ram_pct, 1),
            "ram_free_gb":  round(self.ram_free_gb, 2),
            "cpu_pct":      round(self.cpu_pct, 1),
            "healthy":      self.is_healthy,
            "rejecting":    self.is_rejecting,
            "tier":         self.tier,
            "model_loaded": self.model_loaded,
            "polled_at":    self.timestamp,
        }


# ─── Watchdog ─────────────────────────────────────────────────────────────────

class Watchdog:
    """
    Singleton background health monitor.

    Usage:
        wd = get_watchdog()
        await wd.start(governor=my_governor)
        ...
        await wd.stop()

    Query at any time (thread-safe atomic reads):
        wd.is_healthy()    → True if RAM < 90%
        wd.is_rejecting()  → True if RAM > 95%
        wd.snapshot()      → SystemSnapshot
    """

    def __init__(self) -> None:
        self._healthy:    bool = True
        self._rejecting:  bool = False
        self._last:       Optional[SystemSnapshot] = None
        self._task:       Optional[asyncio.Task] = None
        self._governor    = None          # injected; avoids circular import
        self._cpu_danger_since: float = 0.0
        self._stop_event: asyncio.Event = asyncio.Event()

    # ── Public query API (synchronous, safe from any thread) ──────────────────

    def is_healthy(self) -> bool:
        return self._healthy

    def is_rejecting(self) -> bool:
        return self._rejecting

    def snapshot(self) -> Optional[SystemSnapshot]:
        return self._last

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, governor=None) -> None:
        """
        Start the background polling loop.
        governor: instance of Governor (optional — enables auto-unload on pressure).
        """
        self._governor = governor
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="val-watchdog")
        logger.info("[Watchdog] Started (interval=%.1fs)", POLL_INTERVAL_S)

    async def stop(self) -> None:
        """Gracefully stop the watchdog loop."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Watchdog] Stopped")

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._poll()
            except Exception as exc:           # NEVER crash the watchdog
                logger.error("[Watchdog] Poll error: %s", exc, exc_info=False)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=POLL_INTERVAL_S
                )
                break                          # stop_event was set
            except asyncio.TimeoutError:
                pass                           # normal — keep going

    async def _poll(self) -> None:
        ram_pct, ram_used, ram_free, cpu_pct = _read_system_metrics()
        model_loaded = (
            self._governor.active_model if self._governor else None
        )

        # ── Determine tier ────────────────────────────────────────────────────
        if ram_pct >= RAM_REJECT_PCT:
            tier = "critical"
        elif ram_pct >= RAM_WARN_PCT:
            tier = "warn"
        else:
            tier = "normal"

        self._healthy   = tier == "normal"
        self._rejecting = tier == "critical"

        # ── Actions ───────────────────────────────────────────────────────────
        if tier == "critical":
            logger.critical(
                "[Watchdog] CRITICAL: RAM %.1f%% >= %.0f%% — REJECTING requests",
                ram_pct, RAM_REJECT_PCT,
            )
            if self._governor and model_loaded:
                logger.critical("[Watchdog] Force-unloading %s to survive", model_loaded)
                try:
                    await self._governor.force_unload(reason="watchdog-critical")
                except Exception as e:
                    logger.error("[Watchdog] Force-unload failed: %s", e)

        elif tier == "warn":
            # v3: Do NOT auto-unload on warn — keep model resident for speed.
            # Only log the warning. User explicitly chose to keep model loaded.
            logger.warning(
                "[Watchdog] WARN: RAM %.1f%% >= %.0f%% — model stays resident (operator mode)",
                ram_pct, RAM_WARN_PCT,
            )

        # ── CPU backpressure ──────────────────────────────────────────────────
        now = time.monotonic()
        if cpu_pct >= CPU_DANGER_PCT:
            if self._cpu_danger_since == 0.0:
                self._cpu_danger_since = now
            elif now - self._cpu_danger_since >= CPU_DANGER_SECS:
                logger.warning(
                    "[Watchdog] CPU backpressure: %.1f%% for %.0fs",
                    cpu_pct, now - self._cpu_danger_since,
                )
        else:
            self._cpu_danger_since = 0.0

        # ── GPU VRAM monitoring ───────────────────────────────────────────────
        gpu_used_gb = 0.0
        gpu_total_gb = 0.0
        try:
            import torch
            if torch.cuda.is_available():
                gpu_used_gb = torch.cuda.memory_allocated(0) / (1024 ** 3)
                gpu_total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                gpu_pct = (gpu_used_gb / gpu_total_gb * 100) if gpu_total_gb > 0 else 0
                if gpu_pct > 90:
                    logger.warning("[Watchdog] GPU VRAM high: %.1f%% (%.1fGB/%.1fGB)", gpu_pct, gpu_used_gb, gpu_total_gb)
        except Exception:
            pass

        # ── Store snapshot ────────────────────────────────────────────────────
        self._last = SystemSnapshot(
            ram_used_gb=ram_used,
            ram_pct=ram_pct,
            ram_free_gb=ram_free,
            cpu_pct=cpu_pct,
            is_healthy=self._healthy,
            is_rejecting=self._rejecting,
            tier=tier,
            model_loaded=model_loaded,
        )

        if tier != "normal":
            logger.debug("[Watchdog] %s", self._last.as_dict())


# ─── System metric helpers ────────────────────────────────────────────────────

def _read_system_metrics() -> tuple[float, float, float, float]:
    """
    Returns (ram_pct, ram_used_gb, ram_free_gb, cpu_pct).
    Safe: falls back to 0.0 if psutil unavailable.
    """
    try:
        import psutil
        vm  = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)   # non-blocking
        return (
            vm.percent,
            vm.used  / (1024 ** 3),
            vm.available / (1024 ** 3),
            cpu,
        )
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


# ─── Singleton ────────────────────────────────────────────────────────────────

_watchdog: Optional[Watchdog] = None


def get_watchdog() -> Watchdog:
    """Return (and create if needed) the process-wide Watchdog singleton."""
    global _watchdog
    if _watchdog is None:
        _watchdog = Watchdog()
    return _watchdog
