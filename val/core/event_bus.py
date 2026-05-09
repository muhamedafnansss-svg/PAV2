"""
VAL Event Bus v14.1 — Pub-Sub Event System
=============================================
Cross-component communication for syncing Red/Blue panels,
streaming tool outputs, and triggering UI updates.

Event types:
  - tool.started, tool.completed, tool.failed
  - soc.threat_detected, soc.enrichment_complete
  - model.loading, model.ready, model.swapped
  - agent.step_completed, agent.finished
  - cache.hit, cache.miss
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set

logger = logging.getLogger("val.eventbus")


@dataclass
class Event:
    event_type: str
    data: Dict[str, Any]
    timestamp: float
    source: str = "system"

    def to_sse(self) -> str:
        payload = {
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }
        return f"data: {json.dumps(payload, default=str)}\n\n"


class EventBus:
    """
    Thread-safe pub-sub event bus with async streaming support.
    Subscribers receive events via asyncio queues.
    """

    def __init__(self, max_history: int = 100):
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._sync_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Event] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._event_count = 0

    def publish(self, event_type: str, data: Dict[str, Any], source: str = "system") -> None:
        """
        Publish an event to all subscribers of that type.
        Thread-safe. Can be called from sync or async context.
        """
        event = Event(
            event_type=event_type,
            data=data,
            timestamp=time.time(),
            source=source,
        )

        with self._lock:
            self._event_count += 1
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # Notify async subscribers
        queues = self._subscribers.get(event_type, []) + self._subscribers.get("*", [])
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is too slow

        # Notify sync callbacks
        for cb in self._sync_callbacks.get(event_type, []):
            try:
                cb(event)
            except Exception as e:
                logger.error("[EventBus] Callback error: %s", e)

    def subscribe_sync(self, event_type: str, callback: Callable) -> None:
        """Register a synchronous callback for an event type."""
        self._sync_callbacks[event_type].append(callback)

    async def stream(
        self,
        event_types: Optional[List[str]] = None,
        timeout: float = 300.0,
    ) -> AsyncIterator[Event]:
        """
        Async generator that yields events matching the given types.
        Use event_types=None or ["*"] for all events.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)

        # Subscribe to requested types
        types = event_types or ["*"]
        for et in types:
            self._subscribers[et].append(q)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=timeout)
                    yield event
                except asyncio.TimeoutError:
                    break
        finally:
            # Unsubscribe
            for et in types:
                try:
                    self._subscribers[et].remove(q)
                except ValueError:
                    pass

    def recent(self, count: int = 20, event_type: Optional[str] = None) -> List[dict]:
        """Get recent events, optionally filtered by type."""
        with self._lock:
            events = self._history
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            return [asdict(e) for e in events[-count:]]

    def stats(self) -> dict:
        with self._lock:
            types: Dict[str, int] = {}
            for e in self._history:
                types[e.event_type] = types.get(e.event_type, 0) + 1
            return {
                "total_events": self._event_count,
                "history_size": len(self._history),
                "subscriber_count": sum(len(v) for v in self._subscribers.values()),
                "event_types": types,
            }


# ─── Convenience publishers ──────────────────────────────────────────────────

def publish_tool_event(bus: EventBus, tool: str, status: str, **kwargs):
    bus.publish(f"tool.{status}", {"tool": tool, **kwargs}, source="tools")

def publish_model_event(bus: EventBus, model: str, status: str, **kwargs):
    bus.publish(f"model.{status}", {"model": model, **kwargs}, source="governor")

def publish_soc_event(bus: EventBus, event: str, **kwargs):
    bus.publish(f"soc.{event}", kwargs, source="soc")


# ─── Singleton ────────────────────────────────────────────────────────────────

_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus
