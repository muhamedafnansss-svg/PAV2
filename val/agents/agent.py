"""
VAL Agent System
================
Multi-agent architecture with:
  - VALCoreAgent: primary interactive agent
  - BackgroundAgent: async task runner
  - TaskAgent: single-task executor
  - AgentOrchestrator: lifecycle manager

Inspired by Claude Code's tasks/* subsystem.
"""

import uuid
import time
import threading
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Iterator
from enum import Enum
from dataclasses import dataclass, field

from val.utils.logger import get_logger, LogCategory
from val.state.store import get_state, TaskStatus
from val.core.engine import ValEngine, get_engine
from val.tools.executor import get_tool_registry

logger = get_logger("agents", LogCategory.AGENT)


class AgentStatus(str, Enum):
    IDLE      = "idle"
    RUNNING   = "running"
    PAUSED    = "paused"
    STOPPED   = "stopped"
    ERROR     = "error"


# ─── Base Agent ───────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base class for all VAL agents."""

    def __init__(self, agent_id: Optional[str] = None, name: str = "unnamed-agent"):
        self._agent_id = agent_id or f"agent-{uuid.uuid4().hex[:6]}"
        self._name = name
        self._status = AgentStatus.IDLE
        self._state = get_state()
        self._state.register_agent(self._agent_id, {
            "name": self._name,
            "type": self.__class__.__name__,
        })

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> AgentStatus:
        return self._status

    def _set_status(self, status: AgentStatus) -> None:
        self._status = status
        logger.info(f"Agent '{self._name}' ({self._agent_id}) status → {status.value}")

    @abstractmethod
    def run(self, *args, **kwargs) -> Any:
        """Execute the agent's primary logic."""
        ...

    def stop(self) -> None:
        self._set_status(AgentStatus.STOPPED)

    def to_dict(self) -> dict:
        return {
            "agent_id": self._agent_id,
            "name": self._name,
            "type": self.__class__.__name__,
            "status": self._status.value,
        }


# ─── VAL Core Agent ───────────────────────────────────────────────────────────

class VALCoreAgent(BaseAgent):
    """
    The primary interactive VAL agent.
    Wraps ValEngine with session management and tool integration.
    """

    def __init__(self, session_id: Optional[str] = None):
        super().__init__(name="val-core")
        self._engine = ValEngine(session_id=session_id or "val-interactive")
        # Register all tools with the engine
        tool_registry = get_tool_registry()
        tool_registry.register_all_with_engine(self._engine)
        logger.info(f"VALCoreAgent initialized (session={session_id})")

    @property
    def engine(self) -> ValEngine:
        return self._engine

    def run(self, user_input: str, stream: bool = False, **kwargs) -> Any:
        """Process a single user turn."""
        self._set_status(AgentStatus.RUNNING)
        try:
            if stream:
                result = self._engine.stream(user_input, **kwargs)
                self._set_status(AgentStatus.IDLE)
                return result
            else:
                result = self._engine.query(user_input, **kwargs)
                self._set_status(AgentStatus.IDLE)
                return result
        except Exception as e:
            self._set_status(AgentStatus.ERROR)
            logger.error(f"VALCoreAgent error: {e}", exc_info=True)
            raise

    def query(self, user_input: str, **kwargs):
        """Non-streaming query."""
        return self.run(user_input, stream=False, **kwargs)

    def stream(self, user_input: str, **kwargs) -> Iterator[str]:
        """Streaming query."""
        return self.run(user_input, stream=True, **kwargs)

    def reset(self) -> None:
        """Reset conversation memory."""
        self._engine.reset_memory()
        logger.info(f"VALCoreAgent memory reset")

    def status_report(self) -> dict:
        return {
            **self.to_dict(),
            "context_stats": self._engine.get_context_stats(),
            "metrics": self._engine.get_metrics(),
        }


# ─── Task Agent ───────────────────────────────────────────────────────────────

class TaskAgent(BaseAgent):
    """
    Single-use agent for executing a specific task.
    Runs one job and terminates cleanly.
    """

    def __init__(self, task_description: str, model: Optional[str] = None):
        super().__init__(name="task-agent")
        self._task_description = task_description
        self._model = model
        self._result: Optional[str] = None
        self._task_id: Optional[str] = None

    def run(self, **kwargs) -> str:
        """Execute the task. Returns result string."""
        self._task_id = self._state.create_task(
            name=self._task_description[:50],
            agent_id=self._agent_id,
        )
        self._set_status(AgentStatus.RUNNING)
        self._state.update_task(self._task_id, TaskStatus.RUNNING)

        try:
            engine = get_engine()
            result = engine.query(
                self._task_description,
                force_model=self._model,
            )
            self._result = result.text
            self._state.update_task(
                self._task_id,
                TaskStatus.COMPLETED,
                result=self._result,
            )
            self._set_status(AgentStatus.STOPPED)
            return self._result
        except Exception as e:
            error_msg = str(e)
            self._state.update_task(
                self._task_id,
                TaskStatus.FAILED,
                error=error_msg,
            )
            self._set_status(AgentStatus.ERROR)
            logger.error(f"TaskAgent failed: {e}", exc_info=True)
            return f"[TASK ERROR] {e}"


# ─── Background Agent ────────────────────────────────────────────────────────

class BackgroundAgent(BaseAgent):
    """
    Runs a task asynchronously in a background thread.
    Supports cancellation.
    """

    def __init__(self, task_description: str, callback=None, model: Optional[str] = None):
        super().__init__(name="background-agent")
        self._task_description = task_description
        self._callback = callback
        self._model = model
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()

    def run(self, **kwargs) -> None:
        """Start background execution. Non-blocking."""
        if self._thread and self._thread.is_alive():
            logger.warning(f"BackgroundAgent already running")
            return

        self._cancel_event.clear()
        self._thread = threading.Thread(
            target=self._run_inner,
            daemon=True,
            name=f"val-bg-{self._agent_id}",
        )
        self._thread.start()
        self._set_status(AgentStatus.RUNNING)
        logger.info(f"BackgroundAgent started: {self._task_description[:50]}")

    def _run_inner(self) -> None:
        task_agent = TaskAgent(self._task_description, model=self._model)
        result = task_agent.run()

        if self._cancel_event.is_set():
            logger.info(f"BackgroundAgent {self._agent_id} was cancelled")
            self._set_status(AgentStatus.STOPPED)
            return

        self._set_status(AgentStatus.STOPPED)
        if self._callback:
            try:
                self._callback(result)
            except Exception as e:
                logger.error(f"BackgroundAgent callback error: {e}")

    def cancel(self) -> None:
        """Request cancellation of the background task."""
        self._cancel_event.set()
        self._set_status(AgentStatus.STOPPED)
        logger.info(f"BackgroundAgent {self._agent_id} cancel requested")

    def is_done(self) -> bool:
        return self._thread is None or not self._thread.is_alive()


# ─── ReAct Agent (from PA/backend/agents/agent_brain.py) ──────────────────────

REACT_PROMPT = """You are Jarvis, an elite, autonomous AI executive assistant. Your tone is calm, highly intelligent, concise, and premium. 
You solve complex problems by reasoning step-by-step and using the tools at your disposal natively on the host machine. 

Available tools: {tool_list}

Respond in this EXACT format when you want to use a tool:
THOUGHT: <your reasoning>
ACTION: <tool_name>
ACTION_INPUT: <input for the tool>

When you have a final answer:
THOUGHT: <final reasoning>
FINAL_ANSWER: <your complete answer>

Rules:
- Always include THOUGHT before any action
- Be concise but thorough
- If a tool fails, try an alternative approach
"""


@dataclass
class AgentStep:
    step_num:     int
    thought:      str
    action:       Optional[str] = None
    action_input: Optional[str] = None
    observation:  Optional[str] = None
    is_final:     bool = False
    final_answer: Optional[str] = None
    error:        Optional[str] = None
    duration_ms:  float = 0.0


@dataclass
class AgentResult:
    query:       str
    answer:      str
    steps:       list = field(default_factory=list)
    total_steps: int = 0
    total_ms:    float = 0.0
    success:     bool = True
    error:       Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query": self.query, "answer": self.answer,
            "total_steps": self.total_steps, "total_ms": round(self.total_ms, 1),
            "success": self.success, "error": self.error,
            "steps": [
                {"step": s.step_num, "thought": s.thought, "action": s.action,
                 "observation": (s.observation or "")[:200], "is_final": s.is_final}
                for s in self.steps
            ],
        }


class ReActAgent(BaseAgent):
    """
    Autonomous ReAct agent: Think → Act → Observe → Evaluate → Repeat.
    Ported from PA/backend/agents/agent_brain.py.
    """

    def __init__(self, max_steps: int = 8):
        super().__init__(name="react-agent")
        self._max_steps = max_steps

    def run(self, query: str, context: str = "", **kwargs) -> AgentResult:
        """Execute the ReAct loop synchronously."""
        import re as _re
        t_start = time.time()
        steps: List[AgentStep] = []
        registry = get_tool_registry()

        # Build tool descriptions
        tool_descs = "\n".join(
            f"- {t['name']}: {t['description']}"
            for t in registry.list_tools()
        )
        system = REACT_PROMPT.format(tool_list=tool_descs)
        if context:
            system += f"\n\nContext:\n{context}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ]

        self._set_status(AgentStatus.RUNNING)

        for step_num in range(1, self._max_steps + 1):
            step_t0 = time.time()
            logger.info(f"[ReAct] Step {step_num}/{self._max_steps}")

            # Get LLM response
            try:
                engine = get_engine()
                resp = engine.query(
                    messages[-1]["content"] if messages else query,
                    max_tokens=512,
                )
                llm_output = resp.text if hasattr(resp, 'text') else str(resp)
            except Exception as e:
                steps.append(AgentStep(step_num=step_num, thought="", error=str(e)))
                break

            # Parse ReAct output
            parsed = {}
            for key, pat in [
                ("thought", r"THOUGHT:\s*(.+?)(?=ACTION:|FINAL_ANSWER:|$)"),
                ("action", r"ACTION:\s*(.+?)(?=ACTION_INPUT:|THOUGHT:|FINAL_ANSWER:|$)"),
                ("action_input", r"ACTION_INPUT:\s*(.+?)(?=THOUGHT:|ACTION:|FINAL_ANSWER:|$)"),
                ("final_answer", r"FINAL_ANSWER:\s*(.+?)$"),
            ]:
                m = _re.search(pat, llm_output, _re.DOTALL | _re.IGNORECASE)
                if m:
                    parsed[key] = m.group(1).strip()

            step = AgentStep(
                step_num=step_num,
                thought=parsed.get("thought", ""),
                action=parsed.get("action"),
                action_input=parsed.get("action_input"),
                is_final="final_answer" in parsed,
                final_answer=parsed.get("final_answer"),
                duration_ms=(time.time() - step_t0) * 1000,
            )

            if step.is_final:
                steps.append(step)
                self._set_status(AgentStatus.IDLE)
                return AgentResult(
                    query=query, answer=step.final_answer or "",
                    steps=steps, total_steps=step_num,
                    total_ms=(time.time() - t_start) * 1000,
                )

            # Execute tool
            if step.action:
                try:
                    observation = registry.execute(
                        step.action.strip(),
                        {"input": step.action_input or ""}
                    )
                except Exception as e:
                    observation = f"Tool error: {e}"
                step.observation = str(observation)
                steps.append(step)
                messages.append({"role": "assistant", "content": llm_output})
                messages.append({"role": "user", "content": f"OBSERVATION: {step.observation}"})
            else:
                steps.append(step)
                messages.append({"role": "assistant", "content": llm_output})
                messages.append({"role": "user", "content": "Continue. Use a tool or provide FINAL_ANSWER."})

        self._set_status(AgentStatus.IDLE)
        best = ""
        for s in reversed(steps):
            if s.final_answer: best = s.final_answer; break
            if s.observation: best = f"Based on analysis: {s.observation}"; break
        return AgentResult(
            query=query, answer=best or "Max steps reached.",
            steps=steps, total_steps=len(steps),
            total_ms=(time.time() - t_start) * 1000,
            error="Max steps reached" if not best else None,
        )


# ─── Agent Orchestrator ───────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    Manages the lifecycle of all agents.
    Provides creation, retrieval, and cleanup of agent instances.
    """

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._lock = threading.Lock()
        # Always start with a core agent
        self._core_agent: Optional[VALCoreAgent] = None

    def get_core(self) -> VALCoreAgent:
        """Get or create the primary VAL core agent."""
        if self._core_agent is None:
            self._core_agent = VALCoreAgent()
            with self._lock:
                self._agents[self._core_agent.agent_id] = self._core_agent
        return self._core_agent

    def spawn_task_agent(
        self,
        description: str,
        model: Optional[str] = None,
        background: bool = False,
        callback=None,
    ) -> BaseAgent:
        """
        Create and optionally run a task agent.

        Args:
            description: What the agent should do
            model: Force a specific model
            background: Whether to run asynchronously
            callback: Function to call with result (background only)
        """
        if background:
            agent = BackgroundAgent(
                task_description=description,
                callback=callback,
                model=model,
            )
            agent.run()
        else:
            agent = TaskAgent(description, model=model)

        with self._lock:
            self._agents[agent.agent_id] = agent

        return agent

    def list_agents(self) -> List[dict]:
        with self._lock:
            return [a.to_dict() for a in self._agents.values()]

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        with self._lock:
            return self._agents.get(agent_id)

    def cleanup(self) -> None:
        """Stop all agents and clean up resources."""
        with self._lock:
            for agent in self._agents.values():
                if hasattr(agent, "cancel"):
                    agent.cancel()
            logger.info(f"Orchestrator: cleaned up {len(self._agents)} agents")


# ─── Singleton ────────────────────────────────────────────────────────────────

_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Return the singleton AgentOrchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
