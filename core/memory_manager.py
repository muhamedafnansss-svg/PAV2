import logging
from typing import Optional, List, Dict
import sqlite3
from pathlib import Path
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self, db_path: Path = Path("models/conversation_db.sqlite")):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.short_term_memory: List[Dict] = []
        self.max_short_term = 20
        self._initialize_db()
    
    def _initialize_db(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, created_at TIMESTAMP, metadata TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp TIMESTAMP, metadata TEXT)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")
            conn.commit()
            conn.close()
            logger.info(f"Database initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"DB error: {e}")
    
    def save_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        try:
            self.short_term_memory.append({"session_id": session_id, "role": role, "content": content, "timestamp": datetime.now()})
            if len(self.short_term_memory) > self.max_short_term:
                self.short_term_memory.pop(0)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO messages (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                         (session_id, role, content, datetime.now(), json.dumps(metadata or {})))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Save error: {e}")
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
            rows = cursor.fetchall()
            conn.close()
            return [{"role": row[0], "content": row[1]} for row in reversed(rows)]
        except Exception as e:
            logger.error(f"Query error: {e}")
            return []
    
    def get_stats(self) -> Dict:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM messages")
            total = cursor.fetchone()[0]
            conn.close()
            return {"total_messages": total, "short_term": len(self.short_term_memory)}
        except:
            return {}
