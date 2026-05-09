import logging
from .agent import BaseAgent, AgentStatus

logger = logging.getLogger("val.agents")

class JarvisCoreAgent(BaseAgent):
    """The central executive voice and brain of the JARVIS platform."""
    def __init__(self):
        super().__init__(name="jarvis-core", agent_type="executive")
        self._set_status(AgentStatus.IDLE)

    def route_request(self, query: str):
        """Routes high-level tasks to specialist agents."""
        logger.info(f"[JarvisCore] Routing request: {query[:50]}")
        # In a full implementation, this uses LLM to classify intent
        if "scan" in query.lower() or "firewall" in query.lower():
            return "cyber-agent"
        if "code" in query.lower() or "build" in query.lower():
            return "dev-agent"
        return "self"


class CyberAgent(BaseAgent):
    """Specialist for defensive cyber tasks, SOC, and scanning."""
    def __init__(self):
        super().__init__(name="cyber-specialist", agent_type="security")
        self._set_status(AgentStatus.IDLE)
        
    def execute_audit(self, target: str):
        logger.info(f"[CyberAgent] Executing security audit on {target}")
        self._set_status(AgentStatus.RUNNING)
        from val.soc.soc_engine import is_target_safe
        
        if not is_target_safe(target):
            logger.warning(f"[CyberAgent] Target {target} is blocked by current SafetyMode.")
            self._set_status(AgentStatus.IDLE)
            return {"status": "blocked", "reason": "Target outside authorized scope."}
            
        # In full execution, it orchestrates nmap/ffuf/gobuster based on the authorized target
        # Here we mock the result to ensure it adheres to the scope
        self._set_status(AgentStatus.IDLE)
        return {"status": "audit_complete", "target": target, "results": "Safe pentest executed successfully."}


class DevAgent(BaseAgent):
    """Specialist for codebase indexing, compilation, and AST logic."""
    def __init__(self):
        super().__init__(name="dev-specialist", agent_type="engineering")
        self._set_status(AgentStatus.IDLE)
        
    def review_code(self, filepath: str):
        logger.info(f"[DevAgent] Reviewing code at {filepath}")
        self._set_status(AgentStatus.RUNNING)
        # Mock execution logic to be wired to tools
        self._set_status(AgentStatus.IDLE)
        return {"status": "review_complete", "file": filepath}
