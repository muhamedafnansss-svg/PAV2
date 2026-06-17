import logging
from typing import Optional, Dict, List
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.messages: List[Dict] = []
        self.metadata: Dict = {"user": "default", "device": "local"}
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        self.updated_at = datetime.now()
    
    def get_duration(self) -> float:
        return (self.updated_at - self.created_at).total_seconds()
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "duration": self.get_duration(),
            "message_count": len(self.messages),
            "messages": self.messages,
        }

class SessionManager:
    def __init__(self, max_sessions: int = 100):
        self.sessions: Dict[str, Session] = {}
        self.current_session: Optional[Session] = None
        self.max_sessions = max_sessions
    
    def create_session(self, metadata: Optional[Dict] = None) -> Session:
        if len(self.sessions) >= self.max_sessions:
            oldest_id = min(self.sessions.keys(), key=lambda k: self.sessions[k].created_at)
            del self.sessions[oldest_id]
        
        session = Session()
        if metadata:
            session.metadata.update(metadata)
        self.sessions[session.session_id] = session
        self.current_session = session
        logger.info(f"Session created: {session.session_id}")
        return session
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        if self.current_session:
            self.current_session.add_message(role, content, metadata)
    
    def get_conversation_history(self, limit: Optional[int] = None) -> List[Dict]:
        if self.current_session:
            msgs = self.current_session.messages
            return msgs[-limit:] if limit else msgs
        return []
    
    def end_session(self, session_id: Optional[str] = None) -> None:
        target_id = session_id or (self.current_session.session_id if self.current_session else None)
        if target_id and target_id in self.sessions:
            logger.info(f"Session ended: {target_id}")
            del self.sessions[target_id]
            if self.current_session and self.current_session.session_id == target_id:
                self.current_session = None
    
    def get_stats(self) -> Dict:
        total_messages = sum(len(s.messages) for s in self.sessions.values())
        return {
            "total_sessions": len(self.sessions),
            "total_messages": total_messages,
        }
