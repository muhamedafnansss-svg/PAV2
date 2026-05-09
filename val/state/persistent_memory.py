"""
VAL Persistent Memory v15.0 — SQLite-backed Multi-Domain Memory
================================================================
4 memory domains:
  1. Personal — preferences, habits, devices
  2. Project  — coding tasks, repo states, build status
  3. Security — scan results, alerts, IOCs
  4. Context  — general key-value facts

Features:
  - SQLite (fast, zero-config, single-file)
  - Auto-creates tables on first use
  - Thread-safe via connection-per-thread
  - Optional encryption (future: sqlcipher)
"""

from __future__ import annotations
import json, logging, os, sqlite3, threading, time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("val.memory.persist")

DEFAULT_DB = Path(os.environ.get("VAL_MEMORY_DB", "d:/PAV2/val/state/store/memory.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL DEFAULT 'context',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'user',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(domain, key)
);

CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT DEFAULT 'INFO',
    data_json TEXT,
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_domain ON facts(domain);
CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
CREATE INDEX IF NOT EXISTS idx_security_ts ON security_events(timestamp);
"""


class PersistentMemory:
    """SQLite-backed persistent memory store."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DEFAULT_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()
        logger.info("[PersistMem] Initialized: %s", self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ── Facts CRUD ────────────────────────────────────────────────────────────

    def store_fact(self, key: str, value: str, domain: str = "context",
                   confidence: float = 1.0, source: str = "user") -> bool:
        """Store or update a fact."""
        now = time.time()
        try:
            conn = self._get_conn()
            conn.execute("""
                INSERT INTO facts (domain, key, value, confidence, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """, (domain, key, value, confidence, source, now, now))
            conn.commit()
            return True
        except Exception as e:
            logger.error("[PersistMem] store_fact error: %s", e)
            return False

    def get_fact(self, key: str, domain: str = "context") -> Optional[str]:
        """Get a single fact by key."""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT value FROM facts WHERE domain = ? AND key = ?",
                (domain, key)
            ).fetchone()
            return row["value"] if row else None
        except Exception:
            return None

    def get_facts(self, domain: str = "context", limit: int = 100) -> List[Dict]:
        """Get all facts for a domain."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT key, value, confidence, source, updated_at FROM facts WHERE domain = ? ORDER BY updated_at DESC LIMIT ?",
                (domain, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def search_facts(self, query: str, limit: int = 20) -> List[Dict]:
        """Search facts across all domains (LIKE match on key and value)."""
        try:
            conn = self._get_conn()
            q = f"%{query}%"
            rows = conn.execute(
                "SELECT domain, key, value, confidence FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (q, q, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def delete_fact(self, key: str, domain: str = "context") -> bool:
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM facts WHERE domain = ? AND key = ?", (domain, key))
            conn.commit()
            return True
        except Exception:
            return False

    # ── Security Events ───────────────────────────────────────────────────────

    def log_security_event(self, event_type: str, severity: str = "INFO",
                           data: Optional[Dict] = None) -> bool:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO security_events (event_type, severity, data_json, timestamp) VALUES (?, ?, ?, ?)",
                (event_type, severity, json.dumps(data or {}), time.time())
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("[PersistMem] security event error: %s", e)
            return False

    def get_security_events(self, limit: int = 50, severity: Optional[str] = None) -> List[Dict]:
        try:
            conn = self._get_conn()
            if severity:
                rows = conn.execute(
                    "SELECT * FROM security_events WHERE severity = ? ORDER BY timestamp DESC LIMIT ?",
                    (severity, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM security_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("data_json"):
                    try: d["data"] = json.loads(d["data_json"])
                    except: d["data"] = {}
                    del d["data_json"]
                result.append(d)
            return result
        except Exception:
            return []

    # ── Context injection (for LLM prompt) ────────────────────────────────────

    def get_relevant_context(self, query: str, max_chars: int = 500) -> str:
        """
        Get relevant facts for injection into LLM prompt context.
        Searches across all domains with keyword matching.
        """
        facts = self.search_facts(query, limit=10)
        if not facts:
            return ""

        lines = []
        chars = 0
        for f in facts:
            line = f"[{f['domain']}] {f['key']}: {f['value']}"
            if chars + len(line) > max_chars:
                break
            lines.append(line)
            chars += len(line)
        return "\n".join(lines)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        try:
            conn = self._get_conn()
            total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            total_events = conn.execute("SELECT COUNT(*) FROM security_events").fetchone()[0]
            domains = conn.execute(
                "SELECT domain, COUNT(*) as cnt FROM facts GROUP BY domain"
            ).fetchall()
            return {
                "total_facts": total_facts,
                "total_security_events": total_events,
                "domains": {r["domain"]: r["cnt"] for r in domains},
                "db_path": str(self._db_path),
                "db_size_mb": round(self._db_path.stat().st_size / 1e6, 2) if self._db_path.exists() else 0,
            }
        except Exception as e:
            return {"error": str(e)}


# ─── Singleton ────────────────────────────────────────────────────────────────

_mem: Optional[PersistentMemory] = None
_mem_lock = threading.Lock()

def get_persistent_memory() -> PersistentMemory:
    global _mem
    if _mem is None:
        with _mem_lock:
            if _mem is None:
                _mem = PersistentMemory()
    return _mem
