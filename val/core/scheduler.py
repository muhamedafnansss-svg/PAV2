"""
VAL Hybrid Scheduler v14.1 — Latency-Targeted Inference Scheduling
====================================================================
Manages inference scheduling with per-tier latency targets.

| Task               | Tokens  | Target    |
| SOC triage         | 32–64   | 150–300ms |
| Command suggestion | 64      | 200ms     |
| Exploit generation | 128–256 | 400–800ms |
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger("val.scheduler")


@dataclass
class LatencyTarget:
    name: str
    min_tokens: int
    max_tokens: int
    target_min_ms: float
    target_max_ms: float


# ─── Latency targets per task type ────────────────────────────────────────────

TARGETS: Dict[str, LatencyTarget] = {
    "soc_triage": LatencyTarget("soc_triage", 32, 64, 150, 300),
    "command_suggestion": LatencyTarget("command_suggestion", 32, 64, 100, 200),
    "exploit_generation": LatencyTarget("exploit_generation", 128, 256, 400, 800),
    "threat_analysis": LatencyTarget("threat_analysis", 32, 64, 150, 300),
    "code_generation": LatencyTarget("code_generation", 128, 256, 400, 800),
    "chat": LatencyTarget("chat", 32, 128, 200, 500),
    "default": LatencyTarget("default", 64, 192, 200, 600),
}

# Map intents to task types
_INTENT_TO_TASK = {
    "soc_triage": "soc_triage",
    "security": "threat_analysis",
    "exploit_gen": "exploit_generation",
    "payload_craft": "exploit_generation",
    "coding": "code_generation",
    "analyze": "code_generation",
    "recon": "threat_analysis",
    "firewall": "threat_analysis",
    "chat": "chat",
    "reasoning": "chat",
    "research": "chat",
    "trivial": "command_suggestion",
    "knowledge": "chat",
}


class LatencyTracker:
    """Per-tier moving-average latency tracker."""

    def __init__(self, window: int = 50):
        self._window = window
        self._samples: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def record(self, task_type: str, latency_ms: float) -> None:
        with self._lock:
            if task_type not in self._samples:
                self._samples[task_type] = deque(maxlen=self._window)
            self._samples[task_type].append(latency_ms)

    def average(self, task_type: str) -> float:
        with self._lock:
            samples = self._samples.get(task_type)
            if not samples:
                return 0.0
            return sum(samples) / len(samples)

    def p95(self, task_type: str) -> float:
        with self._lock:
            samples = self._samples.get(task_type)
            if not samples:
                return 0.0
            sorted_s = sorted(samples)
            idx = int(len(sorted_s) * 0.95)
            return sorted_s[min(idx, len(sorted_s) - 1)]

    def stats(self) -> dict:
        with self._lock:
            return {
                task: {
                    "avg_ms": round(sum(s) / len(s), 1) if s else 0,
                    "p95_ms": round(sorted(s)[int(len(s) * 0.95)] if s else 0, 1),
                    "samples": len(s),
                }
                for task, s in self._samples.items()
            }


class HybridScheduler:
    """
    Schedules inference with latency awareness.
    Calculates optimal token budgets based on tier and measured latency.
    """

    def __init__(self):
        self._tracker = LatencyTracker()
        self._lock = threading.Lock()

    def get_token_budget(self, intent: str, prompt_length: int = 0) -> Tuple[int, str]:
        """
        Calculate optimal token budget for a given intent.

        Returns:
            (max_tokens, task_type)
        """
        task_type = _INTENT_TO_TASK.get(intent, "default")
        target = TARGETS.get(task_type, TARGETS["default"])

        avg = self._tracker.average(task_type)

        if avg > 0 and avg > target.target_max_ms:
            # Running slow — reduce tokens
            tokens = target.min_tokens
            logger.debug("[Scheduler] %s running slow (%.0fms > %.0fms), capping to %d tokens",
                         task_type, avg, target.target_max_ms, tokens)
        elif avg > 0 and avg < target.target_min_ms:
            # Running fast — can afford more tokens
            tokens = target.max_tokens
        else:
            # Use midpoint
            tokens = (target.min_tokens + target.max_tokens) // 2

        return tokens, task_type

    def record_latency(self, intent: str, latency_ms: float) -> None:
        """Record measured latency for adaptive budgeting."""
        task_type = _INTENT_TO_TASK.get(intent, "default")
        self._tracker.record(task_type, latency_ms)

    def is_meeting_target(self, intent: str) -> bool:
        """Check if we're meeting latency targets for an intent."""
        task_type = _INTENT_TO_TASK.get(intent, "default")
        target = TARGETS.get(task_type, TARGETS["default"])
        avg = self._tracker.average(task_type)
        return avg <= target.target_max_ms if avg > 0 else True

    def stats(self) -> dict:
        latency_stats = self._tracker.stats()
        meeting_targets = {}
        for task_type, target in TARGETS.items():
            avg = self._tracker.average(task_type)
            meeting_targets[task_type] = {
                "target_range_ms": f"{target.target_min_ms}-{target.target_max_ms}",
                "actual_avg_ms": round(avg, 1),
                "meeting_target": avg <= target.target_max_ms if avg > 0 else None,
                "token_range": f"{target.min_tokens}-{target.max_tokens}",
            }
        return {
            "latency": latency_stats,
            "targets": meeting_targets,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_scheduler: Optional[HybridScheduler] = None


def get_scheduler() -> HybridScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = HybridScheduler()
    return _scheduler
