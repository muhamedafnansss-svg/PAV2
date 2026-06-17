"""
Session Manager
Handles conversation sessions and state
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime
import time
import uuid

logger = logging.getLogger(__name__)


class Session:
    """
    Represents a conversation session
    """
    
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.messages: List[Dict] = []
        self.metadata: Dict = {
            "user": "default",
            "device": "local",
        }
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """Add message to session"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self.messages.append(message)
        self.updated_at = datetime.now()
    
    def get_messages(self, limit: Optional[int] = None) -> List[Dict]:
        """Get messages, optionally limited to last N"""
        if limit:
            return self.messages[-limit:]
        return self.messages
    
    def clear(self) -> None:
        """Clear all messages in session"""
        self.messages.clear()
        logger.info(f"Session {self.session_id} cleared")
    
    def get_duration(self) -> float:
        """Get session duration in seconds"""
        return (self.updated_at - self.created_at).total_seconds()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "duration": self.get_duration(),
            "message_count": len(self.messages),
            "messages": self.messages,
            "metadata": self.metadata,
        }


class SessionManager:
    """
    Manages conversation sessions
    """
    
    def __init__(self, max_sessions: int = 100):
        self.sessions: Dict[str, Session] = {}
        self.current_session: Optional[Session] = None
        self.max_sessions = max_sessions
        self.session_timeout = 300
    
    def create_session(self, metadata: Optional[Dict] = None) -> Session:
        """Create new session"""
        if len(self.sessions) >= self.max_sessions:
            oldest_id = min(
                self.sessions.keys(),
                key=lambda k: self.sessions[k].created_at
            )
            del self.sessions[oldest_id]
            logger.warning(f"Removed oldest session: {oldest_id}")
        
        session = Session()
        if metadata:
            session.metadata.update(metadata)
        
        self.sessions[session.session_id] = session
        self.current_session = session
        
        logger.info(f"Session created: {session.session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def get_current_session(self) -> Optional[Session]:
        """Get current active session"""
        return self.current_session
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """Add message to current session"""
        if self.current_session:
            self.current_session.add_message(role, content, metadata)
        else:
            logger.warning("No active session")
    
    def get_conversation_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get conversation history"""
        if self.current_session:
            return self.current_session.get_messages(limit)
        return []
    
    def end_session(self, session_id: Optional[str] = None) -> None:
        """End session"""
        target_id = session_id or (self.current_session.session_id if self.current_session else None)
        
        if target_id and target_id in self.sessions:
            session = self.sessions[target_id]
            logger.info(f"Session ended: {session.session_id} (duration: {session.get_duration():.1f}s)")
            del self.sessions[target_id]
            
            if self.current_session and self.current_session.session_id == target_id:
                self.current_session = None
    
    def list_sessions(self) -> List[Dict]:
        """List all sessions"""
        return [session.to_dict() for session in self.sessions.values()]
    
    def get_stats(self) -> Dict:
        """Get session statistics"""
        total_messages = sum(len(s.messages) for s in self.sessions.values())
        total_duration = sum(s.get_duration() for s in self.sessions.values())
        
        return {
            "total_sessions": len(self.sessions),
            "active_session": self.current_session.session_id if self.current_session else None,
            "total_messages": total_messages,
            "total_duration": total_duration,
        }
