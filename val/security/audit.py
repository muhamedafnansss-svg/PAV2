"""
VAL Audit Logger — Immutable Command Audit Trail
==================================================
Append-only logging of all tool executions, scope violations,
and security events for forensic review.

Writes to: val/logs/audit.jsonl
Format: One JSON object per line (append-only, no edits)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("val.security.audit")

# ─── Audit directory ──────────────────────────────────────────────────────────

_AUDIT_DIR = Path(os.environ.get(
    "VAL_AUDIT_DIR",
    str(Path(__file__).resolve().parent.parent / "logs")
))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_FILE = _AUDIT_DIR / "audit.jsonl"


# ─── Audit Entry ─────────────────────────────────────────────────────────────

@dataclass
class AuditEntry:
    """A single audit log entry."""
    timestamp:    float
    event_type:   str        # "tool_exec", "scope_violation", "rate_limit", "security"
    tool:         str
    command:      str
    targets:      List[str]
    result:       str        # "success", "blocked", "error", "rate_limited"
    session_id:   str = "default"
    duration_ms:  float = 0.0
    output_size:  int = 0
    error:        Optional[str] = None
    metadata:     Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)
        )
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ─── Audit Logger ─────────────────────────────────────────────────────────────

class AuditLogger:
    """
    Thread-safe, append-only audit logger.
    All tool executions pass through here.
    """

    def __init__(self, audit_file: Optional[Path] = None):
        self._file = audit_file or _AUDIT_FILE
        self._lock = threading.Lock()
        self._entry_count = 0
        # Ensure the file exists
        self._file.touch(exist_ok=True)
        logger.info("[Audit] Logging to %s", self._file)

    def log_tool_execution(
        self,
        tool: str,
        command: str,
        targets: List[str],
        success: bool,
        session_id: str = "default",
        duration_ms: float = 0.0,
        output_size: int = 0,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a tool execution event."""
        entry = AuditEntry(
            timestamp=time.time(),
            event_type="tool_exec",
            tool=tool,
            command=command[:500],  # Cap command length
            targets=targets[:10],  # Cap target count
            result="success" if success else "error",
            session_id=session_id,
            duration_ms=round(duration_ms, 2),
            output_size=output_size,
            error=error[:200] if error else None,
            metadata=metadata,
        )
        self._write(entry)

    def log_scope_violation(
        self,
        tool: str,
        command: str,
        target: str,
        reason: str,
        session_id: str = "default",
    ) -> None:
        """Log a scope violation (blocked out-of-scope attempt)."""
        entry = AuditEntry(
            timestamp=time.time(),
            event_type="scope_violation",
            tool=tool,
            command=command[:500],
            targets=[target],
            result="blocked",
            session_id=session_id,
            error=reason[:200],
            metadata={"violation_type": "scope"},
        )
        self._write(entry)
        logger.warning(
            "[Audit] SCOPE VIOLATION: tool=%s target=%s reason=%s",
            tool, target, reason,
        )

    def log_rate_limit(
        self,
        tool: str,
        target: str,
        session_id: str = "default",
    ) -> None:
        """Log a rate limit enforcement."""
        entry = AuditEntry(
            timestamp=time.time(),
            event_type="rate_limit",
            tool=tool,
            command="",
            targets=[target],
            result="rate_limited",
            session_id=session_id,
            metadata={"violation_type": "rate_limit"},
        )
        self._write(entry)

    def log_security_event(
        self,
        event_description: str,
        tool: str = "system",
        severity: str = "medium",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a general security event."""
        entry = AuditEntry(
            timestamp=time.time(),
            event_type="security",
            tool=tool,
            command="",
            targets=[],
            result=severity,
            metadata={**(metadata or {}), "description": event_description},
        )
        self._write(entry)

    def _write(self, entry: AuditEntry) -> None:
        """Thread-safe append to audit log."""
        with self._lock:
            try:
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(entry.to_json() + "\n")
                self._entry_count += 1
            except Exception as e:
                logger.error("[Audit] Write failed: %s", e)

    def get_recent(self, count: int = 50) -> List[dict]:
        """Read the most recent N audit entries."""
        try:
            lines = self._file.read_text(encoding="utf-8").splitlines()
            recent = lines[-count:]
            return [json.loads(line) for line in recent if line.strip()]
        except Exception as e:
            logger.error("[Audit] Read failed: %s", e)
            return []

    def get_violations(self, count: int = 50) -> List[dict]:
        """Read recent scope violations and rate limit events."""
        all_entries = self.get_recent(count * 3)  # Read more, then filter
        violations = [
            e for e in all_entries
            if e.get("event_type") in ("scope_violation", "rate_limit")
        ]
        return violations[-count:]

    def stats(self) -> dict:
        """Return audit statistics."""
        try:
            lines = self._file.read_text(encoding="utf-8").splitlines()
            total = len(lines)
            by_type: Dict[str, int] = {}
            by_result: Dict[str, int] = {}
            for line in lines[-500:]:  # Only analyze recent
                try:
                    entry = json.loads(line)
                    et = entry.get("event_type", "unknown")
                    by_type[et] = by_type.get(et, 0) + 1
                    res = entry.get("result", "unknown")
                    by_result[res] = by_result.get(res, 0) + 1
                except Exception:
                    pass
            return {
                "total_entries": total,
                "by_type": by_type,
                "by_result": by_result,
                "audit_file": str(self._file),
            }
        except Exception:
            return {"total_entries": 0, "audit_file": str(self._file)}


# ─── Singleton ────────────────────────────────────────────────────────────────

_audit: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit() -> AuditLogger:
    """Return the singleton AuditLogger."""
    global _audit
    if _audit is None:
        with _audit_lock:
            if _audit is None:
                _audit = AuditLogger()
    return _audit
