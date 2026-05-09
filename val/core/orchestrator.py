"""
VAL Task Orchestrator v14.1 — Multi-Step Task Decomposition
=============================================================
Sits between Router and execution in the Kernel pipeline.

Responsibilities:
  - Multi-step task decomposition for complex prompts
  - Cross-tier chaining (Tier 0 → Tier 1 → Tier 2)
  - State tracking (target, scope, intermediate results)
  - Dependency resolution between steps

Flow: User Input → Router → Orchestrator → Tool/Model → Aggregated Output

Constraints:
  - Max 5 sub-tasks per orchestration
  - Scope validation at every step
  - Timeout: 30s per tool, 60s per LLM step
  - State is ephemeral (request-scoped only)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from val.models.router import RoutingDecision, Intent, TIER_0, TIER_1, TIER_2

logger = logging.getLogger("val.orchestrator")

MAX_STEPS = 5
TOOL_TIMEOUT_S = 30
LLM_TIMEOUT_S = 60


class StepStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"
    SKIPPED  = "skipped"


@dataclass
class OrchestratorStep:
    step_id: str
    index: int
    tier: int
    action: str           # "tool_exec", "llm_infer", "enrich", "fast_reply"
    description: str
    tool_name: Optional[str] = None
    model: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class TaskState:
    task_id: str
    original_prompt: str
    target: Optional[str] = None
    steps: List[OrchestratorStep] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)
    current_step: int = 0
    started_at: float = 0.0


# ─── Multi-step detection ─────────────────────────────────────────────────────

# Intents that may benefit from orchestration (cross-tier chaining)
_ORCHESTRATABLE_INTENTS = {
    Intent.RECON, Intent.SECURITY, Intent.AGENT,
    Intent.SOC_TRIAGE, Intent.EXPLOIT_GEN, Intent.PAYLOAD_CRAFT,
    Intent.ANALYZE,
}


def needs_orchestration(decision: RoutingDecision) -> bool:
    """
    Determine if a routing decision warrants multi-step orchestration.
    Simple queries bypass the orchestrator entirely for speed.
    """
    if decision.intent not in _ORCHESTRATABLE_INTENTS:
        return False
    if decision.complexity < 3:
        return False
    return True


# ─── Task Decomposer ─────────────────────────────────────────────────────────

def decompose(prompt: str, decision: RoutingDecision) -> List[OrchestratorStep]:
    """
    Break a complex prompt into ordered sub-tasks.
    Deterministic — same input always produces same decomposition.
    """
    steps: List[OrchestratorStep] = []

    if decision.intent == Intent.RECON:
        # Tier 0: execute tool → Tier 1: Mistral summarizes
        steps.append(OrchestratorStep(
            step_id="recon_exec", index=0, tier=TIER_0,
            action="tool_exec", description="Execute recon tool",
            tool_name=decision.tool or "nmap",
        ))
        steps.append(OrchestratorStep(
            step_id="recon_analyze", index=1, tier=TIER_1,
            action="llm_infer", description="Analyze recon results",
            model="mistral", depends_on=["recon_exec"],
        ))

    elif decision.intent == Intent.SOC_TRIAGE:
        # Tier 0: parse logs → Tier 1: Mistral classifies + scores
        steps.append(OrchestratorStep(
            step_id="soc_parse", index=0, tier=TIER_0,
            action="tool_exec", description="Parse and scan logs",
            tool_name="soc_scanner",
        ))
        steps.append(OrchestratorStep(
            step_id="soc_classify", index=1, tier=TIER_1,
            action="llm_infer", description="Classify threats and score risk",
            model="mistral", depends_on=["soc_parse"],
        ))

    elif decision.intent == Intent.EXPLOIT_GEN:
        # Tier 1: Mistral analyzes target → Tier 2: Qwen generates exploit
        steps.append(OrchestratorStep(
            step_id="vuln_assess", index=0, tier=TIER_1,
            action="llm_infer", description="Assess vulnerability context",
            model="mistral",
        ))
        steps.append(OrchestratorStep(
            step_id="exploit_gen", index=1, tier=TIER_2,
            action="llm_infer", description="Generate exploit code",
            model="qwen", depends_on=["vuln_assess"],
        ))

    elif decision.intent == Intent.PAYLOAD_CRAFT:
        # Tier 2: Qwen generates payload
        steps.append(OrchestratorStep(
            step_id="payload_craft", index=0, tier=TIER_2,
            action="llm_infer", description="Craft payload/shellcode",
            model="qwen",
        ))

    elif decision.intent == Intent.SECURITY:
        # Tier 0: extract IOCs → Tier 1: Mistral analyzes
        steps.append(OrchestratorStep(
            step_id="ioc_extract", index=0, tier=TIER_0,
            action="tool_exec", description="Extract IOCs from input",
            tool_name="ioc_extractor",
        ))
        steps.append(OrchestratorStep(
            step_id="threat_analyze", index=1, tier=TIER_1,
            action="llm_infer", description="Analyze threat indicators",
            model="mistral", depends_on=["ioc_extract"],
        ))

    elif decision.intent == Intent.ANALYZE:
        # Tier 0: scan code → Tier 2: Qwen reviews
        steps.append(OrchestratorStep(
            step_id="code_scan", index=0, tier=TIER_0,
            action="tool_exec", description="Static code analysis",
            tool_name="analyze_code",
        ))
        steps.append(OrchestratorStep(
            step_id="code_review", index=1, tier=TIER_2,
            action="llm_infer", description="Review findings and suggest fixes",
            model="qwen", depends_on=["code_scan"],
        ))

    else:
        # Single-step fallback
        steps.append(OrchestratorStep(
            step_id="default", index=0,
            tier=decision.tier,
            action="llm_infer", description="Process request",
            model=decision.model,
        ))

    return steps[:MAX_STEPS]


# ─── Task Orchestrator ────────────────────────────────────────────────────────

class TaskOrchestrator:
    """
    Executes multi-step task plans with cross-tier chaining.
    Yields progress events for real-time UI updates.
    """

    def __init__(self):
        self._active_tasks: Dict[str, TaskState] = {}

    async def orchestrate(
        self,
        prompt: str,
        decision: RoutingDecision,
        session_id: str = "default",
    ) -> AsyncIterator[dict]:
        """
        Execute orchestrated multi-step task.
        Yields SSE-compatible dicts with progress and results.
        """
        task_id = uuid.uuid4().hex[:8]
        steps = decompose(prompt, decision)

        state = TaskState(
            task_id=task_id,
            original_prompt=prompt,
            steps=steps,
            started_at=time.time(),
        )
        self._active_tasks[task_id] = state

        yield {
            "status": f"Orchestrating [{decision.intent}] — {len(steps)} step(s)",
            "orchestrator": {
                "task_id": task_id,
                "steps": len(steps),
                "tiers": list(set(s.tier for s in steps)),
            },
        }

        try:
            for step in steps:
                # Check dependencies
                for dep_id in step.depends_on:
                    if dep_id not in state.results:
                        step.status = StepStatus.SKIPPED
                        step.error = f"Dependency '{dep_id}' not satisfied"
                        continue

                step.status = StepStatus.RUNNING
                state.current_step = step.index
                t0 = time.time()

                yield {
                    "status": f"Step {step.index + 1}/{len(steps)}: {step.description}",
                    "orchestrator_step": {
                        "step_id": step.step_id,
                        "tier": step.tier,
                        "action": step.action,
                    },
                }

                try:
                    if step.action == "tool_exec":
                        result = await self._exec_tool(step, state, prompt)
                    elif step.action == "llm_infer":
                        result = await self._exec_llm(step, state, prompt)
                    elif step.action == "fast_reply":
                        result = step.description
                    else:
                        result = f"[Unknown action: {step.action}]"

                    step.status = StepStatus.DONE
                    step.result = result
                    step.duration_ms = (time.time() - t0) * 1000
                    state.results[step.step_id] = result

                    yield {"chunk": result}

                except asyncio.TimeoutError:
                    step.status = StepStatus.FAILED
                    step.error = "Step timed out"
                    step.duration_ms = (time.time() - t0) * 1000
                    yield {"error": f"Step '{step.step_id}' timed out"}

                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    step.duration_ms = (time.time() - t0) * 1000
                    logger.error("[Orchestrator] Step %s failed: %s", step.step_id, e)
                    yield {"error": f"Step '{step.step_id}' failed: {e}"}

        finally:
            self._active_tasks.pop(task_id, None)

        total_ms = (time.time() - state.started_at) * 1000
        yield {
            "done": True,
            "result": {
                "task_id": task_id,
                "steps_completed": sum(1 for s in steps if s.status == StepStatus.DONE),
                "total_steps": len(steps),
                "total_ms": round(total_ms, 1),
                "text": state.results.get(steps[-1].step_id, ""),
                "model_used": steps[-1].model or "fast-path",
                "intent": decision.intent,
                "latency_s": round(total_ms / 1000, 3),
                "complexity": decision.complexity,
                "session_id": session_id,
            },
        }

    async def _exec_tool(self, step: OrchestratorStep, state: TaskState, prompt: str) -> str:
        """Execute a tool step."""
        loop = asyncio.get_running_loop()

        if step.tool_name == "soc_scanner":
            from val.soc.soc_engine import analyze_text, generate_report
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: generate_report(analyze_text(prompt))),
                timeout=TOOL_TIMEOUT_S,
            )
            return result

        if step.tool_name == "ioc_extractor":
            from val.soc.soc_engine import extract_iocs
            import json
            iocs = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: extract_iocs(prompt)),
                timeout=TOOL_TIMEOUT_S,
            )
            return json.dumps(iocs, indent=2) if iocs else "No IOCs found."

        if step.tool_name == "analyze_code":
            from val.tools.executor import get_tool_registry
            registry = get_tool_registry()
            tool = registry.get("analyze_code")
            if tool:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: tool(path="")),
                    timeout=TOOL_TIMEOUT_S,
                )
                return result
            return "[Code analyzer not available]"

        # Generic tool execution via registry
        from val.tools.executor import get_tool_registry
        registry = get_tool_registry()
        tool = registry.get(step.tool_name or "")
        if tool:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: tool(query=prompt)),
                timeout=TOOL_TIMEOUT_S,
            )
            return str(result)

        return f"[Tool '{step.tool_name}' not found]"

    async def _exec_llm(self, step: OrchestratorStep, state: TaskState, prompt: str) -> str:
        """Execute an LLM inference step."""
        from val.models.governor import get_governor

        governor = get_governor()

        # Build context from previous step results
        context_parts = []
        for dep_id in step.depends_on:
            if dep_id in state.results:
                context_parts.append(f"[Previous result]\n{state.results[dep_id]}")

        full_prompt = prompt
        if context_parts:
            full_prompt = "\n\n".join(context_parts) + f"\n\n[Task] {step.description}\n\n{prompt}"

        # Ensure correct model is loaded
        if step.model and governor.active_model != step.model:
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: governor.load(step.model)),
                timeout=LLM_TIMEOUT_S,
            )

        # Determine token cap based on tier
        from val.models.router import TIER_TOKEN_CAPS
        max_tokens = TIER_TOKEN_CAPS.get(step.tier, 128)

        messages = [
            {
                "role": "system", 
                "content": (
                    "You are Jarvis, a highly capable, premium AI executive assistant and cyber operator. "
                    "Your tone is calm, professional, and slightly cinematic. You are concise and elite. "
                    "You operate the machine natively. Do not ramble. Do not sound robotic. "
                    "For example, instead of 'Task completed', say 'Completed. The firewall rules are now active.'"
                )
            },
            {"role": "user", "content": full_prompt},
        ]

        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: governor.generate(messages, max_new_tokens=max_tokens, temperature=0.3),
            ),
            timeout=LLM_TIMEOUT_S,
        )
        return result

    def status(self) -> dict:
        return {
            "active_tasks": len(self._active_tasks),
            "tasks": {
                tid: {
                    "prompt": t.original_prompt[:80],
                    "steps": len(t.steps),
                    "current": t.current_step,
                    "completed": sum(1 for s in t.steps if s.status == StepStatus.DONE),
                }
                for tid, t in self._active_tasks.items()
            },
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_orchestrator: Optional[TaskOrchestrator] = None


def get_orchestrator() -> TaskOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TaskOrchestrator()
    return _orchestrator
