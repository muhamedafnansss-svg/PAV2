"""
Memory Manager
Handles short-term and long-term conversation memory
"""

import logging
from typing import Optional, List, Dict
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Manages conversation memory using SQLite
    """
    
    def __init__(self, db_path: Path = Path("models/conversation_db.sqlite")):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.short_term_memory: List[Dict] = []
        self.max_short_term = 20
        
        self._initialize_db()
    
    def _initialize_db(self) -> None:
        """Create database if it doesn't exist"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (session_id) REFERENCES conversations(session_id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON messages(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)")
            
            conn.commit()
            conn.close()
            logger.info(f"Database initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    
    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Save message to database and cache"""
        try:
            message = {
                "session_id": session_id,
                "role": role,
                "content": content,
                "timestamp": datetime.now(),
                "metadata": metadata or {},
            }
            
            self.short_term_memory.append(message)
            
            if len(self.short_term_memory) > self.max_short_term:
                self.short_term_memory.pop(0)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.now()
            meta_json = json.dumps(metadata or {})
            
            cursor.execute("""
                INSERT INTO messages (session_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, role, content, now, meta_json))
            
            conn.commit()
            conn.close()
            logger.debug(f"Message saved: {role}")
        except Exception as e:
            logger.error(f"Error saving message: {e}")
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages from session"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT role, content, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            messages = [
                {"role": row[0], "content": row[1], "timestamp": row[2]}
                for row in reversed(rows)
            ]
            
            return messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []
    
    def get_short_term_memory(self) -> List[Dict]:
        """Get cached short-term memory"""
        return self.short_term_memory.copy()
    
    def clear_short_term_memory(self) -> None:
        """Clear short-term memory cache"""
        self.short_term_memory.clear()
        logger.info("Short-term memory cleared")
    
    def get_stats(self) -> Dict:
        """Get memory statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM conversations")
            total_conversations = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            total_messages = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "conversations": total_conversations,
                "messages": total_messages,
                "short_term": len(self.short_term_memory),
            }
        except Exception as e:
            logger.error(f"Stats error: {e}")
            return {}
