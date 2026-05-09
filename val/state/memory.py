"""
VAL Memory System — Persistent Production Memory
===============================================
Three distinct layers with strict boundaries:

  Layer 1 — Short-term memory (SQLite Persistent)
    - Last 8–10 conversation turns
    - Oldest turns discarded (no summarization)
    - Injected into every LLM prompt
    - Thread-safe (RLock)

  Layer 2 — Working memory 
    - Current task execution state
    - Cleared after task completes
    - Used by engine to track multi-step plan state

  Layer 3 — Long-term seed (FUTURE — NOT IMPLEMENTED YET)
    - Deferred: rule-based summarization triggered when idle
    - NEVER triggers model loads
    - NEVER blocks requests

Hard limits:
  - Short-term cap: MAX_TURNS = 10 (configurable)
  - Context window never exceeded: inject only what fits in ctx_limit()
  - Working memory has TTL: auto-cleared after WORKING_TTL_S seconds
"""

from __future__ import annotations

import time
import threading
import logging
import sqlite3
import os
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger("val.memory")

# ─── Limits ───────────────────────────────────────────────────────────────────

MAX_TURNS       = 10        # short-term window (8–10 turns as specified)
WORKING_TTL_S   = 300.0     # 5 minutes: auto-clear stale working memory
MAX_CTX_CHARS   = 3000      # max chars to inject into prompt context
DB_PATH         = "val_memory.sqlite3"

# ─── Turn ─────────────────────────────────────────────────────────────────────

@dataclass
class Turn:
    role:      str        # 'user' | 'assistant'
    content:   str
    model:     Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


# ─── Working Memory State ─────────────────────────────────────────────────────

@dataclass
class WorkingState:
    task_id:      str
    intent:       str
    model:        str
    step_index:   int = 0
    step_count:   int = 1
    tool_results: Dict[str, Any] = field(default_factory=dict)
    partial_text: str = ""
    started_at:   float = field(default_factory=time.time)
    updated_at:   float = field(default_factory=time.time)

    def advance(self) -> None:
        self.step_index += 1
        self.updated_at = time.time()

    def is_stale(self) -> bool:
        return (time.time() - self.updated_at) > WORKING_TTL_S

    def as_dict(self) -> dict:
        return {
            "task_id":    self.task_id,
            "intent":     self.intent,
            "model":      self.model,
            "step":       f"{self.step_index+1}/{self.step_count}",
            "started_at": self.started_at,
        }


# ─── Conversation Memory ──────────────────────────────────────────────────────

class ConversationMemory:
    """
    Per-session memory object backed by SQLite.

    Short-term:
        memory.add_turn(role, content, model)
        memory.get_context(ctx_limit_chars)  → List[dict]  (for prompt building)
        memory.clear()

    Working:
        memory.set_working(state)
        memory.get_working()   → Optional[WorkingState]
        memory.clear_working()
    """

    def __init__(self, session_id: str):
        self.session_id  = session_id
        self._working:   Optional[WorkingState] = None
        self._lock       = threading.RLock()
        self._created_at = time.time()
        self._init_db()

    def _init_db(self):
        with self._lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        model TEXT,
                        timestamp REAL NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON memory_turns(session_id, timestamp)")
                conn.commit()

    def _get_turns(self) -> List[Turn]:
        with self._lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute(
                    "SELECT role, content, model, timestamp FROM memory_turns WHERE session_id = ? ORDER BY timestamp ASC",
                    (self.session_id,)
                )
                return [Turn(role=row[0], content=row[1], model=row[2], timestamp=row[3]) for row in cursor.fetchall()]

    # ── Short-term ────────────────────────────────────────────────────────────

    def add_turn(self, role: str, content: str, model: Optional[str] = None) -> None:
        """
        Add a turn to short-term SQLite memory.
        Enforces MAX_TURNS by discarding oldest pair if exceeded.
        """
        with self._lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO memory_turns (session_id, role, content, model, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (self.session_id, role, content, model, time.time())
                )
                conn.commit()
                
            turns = self._get_turns()
            if len(turns) > MAX_TURNS:
                # Keep only the latest MAX_TURNS
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "DELETE FROM memory_turns WHERE session_id = ? AND id NOT IN (SELECT id FROM memory_turns WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?)",
                        (self.session_id, self.session_id, MAX_TURNS)
                    )
                    conn.commit()

    def get_context(self, max_chars: int = MAX_CTX_CHARS) -> List[dict]:
        """
        Return short-term turns for prompt injection.
        Respects max_chars budget — drops oldest turns first if over budget.
        Returns [{role, content}, ...] oldest-first.
        """
        turns = self._get_turns()

        if not turns:
            return []

        # Work from newest to oldest, collect until budget exceeded
        selected: List[Turn] = []
        budget = max_chars
        for turn in reversed(turns):
            cost = len(turn.content) + len(turn.role) + 10  # rough overhead
            if cost > budget:
                break
            selected.insert(0, turn)
            budget -= cost

        return [t.as_dict() for t in selected]

    def clear(self) -> None:
        """Clear all short-term turns for this session."""
        with self._lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM memory_turns WHERE session_id = ?", (self.session_id,))
                conn.commit()
        logger.debug("[Memory:%s] Short-term cleared", self.session_id)

    def turn_count(self) -> int:
        return len(self._get_turns())

    # ── Working memory ────────────────────────────────────────────────────────

    def set_working(self, state: WorkingState) -> None:
        """Set the active task state. Overwrites any previous working state."""
        with self._lock:
            self._working = state
        logger.debug(
            "[Memory:%s] Working state set: task=%s intent=%s",
            self.session_id, state.task_id, state.intent,
        )

    def get_working(self) -> Optional[WorkingState]:
        """Return current working state, or None if stale/absent."""
        with self._lock:
            if self._working and self._working.is_stale():
                logger.debug(
                    "[Memory:%s] Working state expired (task=%s)",
                    self.session_id, self._working.task_id,
                )
                self._working = None
            return self._working

    def clear_working(self) -> None:
        """Clear working memory after task completes."""
        with self._lock:
            self._working = None

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            working = self._working.as_dict() if self._working else None
        return {
            "session_id":  self.session_id,
            "turns":       self.turn_count(),
            "max_turns":   MAX_TURNS,
            "working":     working,
            "created_at":  self._created_at,
        }


# ─── Session Store ────────────────────────────────────────────────────────────

class MemoryStore:
    """
    Process-wide store of per-session ConversationMemory objects.
    Auto-creates sessions on first access.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, ConversationMemory] = {}
        self._lock = threading.RLock()

    def get(self, session_id: str) -> ConversationMemory:
        """Return (or create) ConversationMemory for this session_id."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationMemory(session_id)
                logger.debug("[MemoryStore] New session: %s", session_id)
            return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        """Clear all memory for this session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].clear()
                self._sessions[session_id].clear_working()
        logger.info("[MemoryStore] Session reset: %s", session_id)

    def drop(self, session_id: str) -> None:
        """Remove session entirely."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def all_sessions(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())

    def status(self) -> dict:
        with self._lock:
            return {
                "sessions": len(self._sessions),
                "detail":   {sid: m.status() for sid, m in self._sessions.items()},
            }


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """Return (and create if needed) the process-wide MemoryStore singleton."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def get_memory(session_id: str = "default") -> ConversationMemory:
    """Convenience function: get ConversationMemory for a session."""
    return get_memory_store().get(session_id)
