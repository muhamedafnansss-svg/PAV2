"""
VAL State Store
==============
Global AppStateStore — the single source of truth for VAL's runtime state.
Inspired by Claude Code's state management, but simplified for local-first use.

Stores:
  - Active agent sessions
  - Task registry
  - Plugin/tool registration status
  - Session metrics (tokens, cost, latency)
  - System status
"""

import json
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from enum import Enum
from pathlib import Path

from val.utils.logger import get_logger, LogCategory
from val.config.settings import STATE_DIR

logger = get_logger("state", LogCategory.SYSTEM)


class TaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    task_id: str
    name: str
    status: TaskStatus
    agent_id: str
    created_at: float
    updated_at: float
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class SessionMetrics:
    session_id: str
    start_time: float
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_requests: int = 0
    total_latency_s: float = 0.0
    model_usage: Dict[str, int] = field(default_factory=dict)

    def record_request(
        self, tokens_in: int, tokens_out: int, latency_s: float, model: str
    ) -> None:
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_requests += 1
        self.total_latency_s += latency_s
        self.model_usage[model] = self.model_usage.get(model, 0) + 1

    @property
    def avg_latency(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_s / self.total_requests

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "uptime_s": time.time() - self.start_time,
            "total_requests": self.total_requests,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "avg_latency_s": self.avg_latency,
            "model_usage": self.model_usage,
        }


class AppStateStore:
    """
    Thread-safe global state store.
    Acts as the central nervous system for VAL's runtime state.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._session_id = str(uuid.uuid4())[:8]
        self._tasks: Dict[str, TaskRecord] = {}
        self._agents: Dict[str, dict] = {}
        self._plugins: Dict[str, dict] = {}
        self._tools: Dict[str, dict] = {}
        self._metrics = SessionMetrics(
            session_id=self._session_id,
            start_time=time.time(),
        )
        self._system_flags: Dict[str, Any] = {
            "initialized": False,
            "models_ready": {},
            "val_version": "1.0.0",
        }
        logger.info(f"AppStateStore initialized (session={self._session_id})")

    # ── Session ──────────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._session_id

    def mark_initialized(self) -> None:
        with self._lock:
            self._system_flags["initialized"] = True
            logger.info("VAL system marked as initialized")

    def set_model_ready(self, model_name: str, ready: bool = True) -> None:
        with self._lock:
            self._system_flags["models_ready"][model_name] = ready

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_task(
        self,
        name: str,
        agent_id: str = "val-core",
        metadata: Optional[Dict] = None,
    ) -> str:
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        now = time.time()
        task = TaskRecord(
            task_id=task_id,
            name=name,
            status=TaskStatus.PENDING,
            agent_id=agent_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._lock:
            self._tasks[task_id] = task
        logger.info(f"Task created: {task_id} ({name})")
        return task_id

    def update_task(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"Cannot update unknown task: {task_id}")
                return
            task.status = status
            task.updated_at = time.time()
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, status_filter: Optional[TaskStatus] = None) -> List[TaskRecord]:
        with self._lock:
            tasks = list(self._tasks.values())
            if status_filter:
                tasks = [t for t in tasks if t.status == status_filter]
            return sorted(tasks, key=lambda t: t.created_at)

    # ── Agents ────────────────────────────────────────────────────────────────

    def register_agent(self, agent_id: str, info: dict) -> None:
        with self._lock:
            self._agents[agent_id] = {**info, "registered_at": time.time()}
            logger.info(f"Agent registered: {agent_id}")

    def deregister_agent(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)

    def list_agents(self) -> dict:
        with self._lock:
            return dict(self._agents)

    # ── Tools & Plugins ───────────────────────────────────────────────────────

    def register_tool(self, tool_name: str, schema: dict) -> None:
        with self._lock:
            self._tools[tool_name] = schema

    def register_plugin(self, plugin_name: str, info: dict) -> None:
        with self._lock:
            self._plugins[plugin_name] = info

    def list_tools(self) -> dict:
        with self._lock:
            return dict(self._tools)

    # ── Metrics ───────────────────────────────────────────────────────────────

    def record_inference(
        self, tokens_in: int, tokens_out: int, latency_s: float, model: str
    ) -> None:
        with self._lock:
            self._metrics.record_request(tokens_in, tokens_out, latency_s, model)

    def get_metrics(self) -> dict:
        with self._lock:
            return self._metrics.to_dict()

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a full serializable snapshot of the current state."""
        with self._lock:
            return {
                "session_id": self._session_id,
                "system": self._system_flags,
                "tasks": [t.to_dict() for t in self._tasks.values()],
                "agents": list(self._agents.keys()),
                "tools": list(self._tools.keys()),
                "metrics": self._metrics.to_dict(),
            }

    def save_snapshot(self) -> Path:
        """Persist state snapshot to disk."""
        snap = self.snapshot()
        path = STATE_DIR / f"state_{self._session_id}.json"
        path.write_text(json.dumps(snap, indent=2, default=str))
        return path


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[AppStateStore] = None
_store_lock = threading.Lock()


def get_state() -> AppStateStore:
    """Return the singleton AppStateStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AppStateStore()
    return _store
