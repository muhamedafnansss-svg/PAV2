"""
VAL AI Kernel — Production Async Execution Engine v14.1
========================================================
The central runtime loop. Behaves like an OS scheduler for AI tasks.

Pipeline for every request:
    user_input
        │
        ▼
    router.route()          ← zero-cost, sync, ~0ms (now with tier assignment)
        │
        ▼
    planner.plan()          ← zero-cost, sync, ~0ms
        │
        ▼
    orchestrator?           ← v14.1: multi-step decomposition (complex tasks only)
        │
        ▼
    memory.get_context()    ← inject short-term history
        │
        ▼
    [dispatch by intent]
        ├── GREETING    → fast_reply()    (no model, instant)
        ├── SWITCH      → governor.load() (control plane)
        ├── SYSTEM_CMD  → terminal tool   (no model)
        ├── TOOL_CALL   → executor tool   (no model)
        ├── SOC_TRIAGE  → orchestrator    (Tier 0→Tier 1)
        ├── EXPLOIT_GEN → orchestrator    (Tier 1→Tier 2)
        └── LLM intents → governor.stream() (async inference)
        │
        ▼
    memory.add_turn()       ← store result in short-term
        │
        ▼
    yield InferenceResult   ← structured result returned to API layer

Hard constraints:
  - Bounded async queue: max 1 active + 2 waiting
  - No blocking operations: all HF inference via run_in_executor
  - Rejection when watchdog.is_rejecting() == True
  - System NEVER crashes from this layer down
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, List, Optional, Dict, Any

from val.models.router   import get_router, RoutingDecision, Intent
from val.core.planner    import get_planner, ExecutionPlan
from val.core.planner    import Intent as PlannerIntent
from val.models.governor import get_governor
from val.core.orchestrator import get_orchestrator, needs_orchestration
from val.state.memory    import get_memory, WorkingState
from val.utils.watchdog  import get_watchdog

logger = logging.getLogger("val.kernel")

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_ACTIVE_REQUESTS = 1     # concurrent inference slots
MAX_QUEUE_DEPTH     = 2     # waiting queue depth
MAX_RESPONSE_WORDS  = 300   # word cap on LLM output
REQUEST_TIMEOUT_S   = 60.0  # per-request timeout

# ─── Result ───────────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    text:          str
    model_used:    str
    intent:        str
    latency_s:     float
    complexity:    int
    tool_output:   Optional[str] = None
    switch_event:  Optional[str] = None
    error:         Optional[str] = None
    session_id:    str = "default"
    request_id:    str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def as_dict(self) -> dict:
        return {
            "text":         self.text,
            "model_used":   self.model_used,
            "intent":       self.intent,
            "latency_s":    round(self.latency_s, 3),
            "complexity":   self.complexity,
            "tool_output":  self.tool_output,
            "switch_event": self.switch_event,
            "error":        self.error,
            "session_id":   self.session_id,
            "request_id":   self.request_id,
        }


# ─── Queue gate ───────────────────────────────────────────────────────────────

class RequestGate:
    """
    Bounded async semaphore implementing the queue policy:
      max 1 active inference + max 2 queued.
    Returns False immediately (no wait) when queue is full.
    """

    def __init__(self, active: int = 1, queue_depth: int = 2) -> None:
        self._sem     = asyncio.Semaphore(active)
        self._waiting = 0
        self._max_q   = queue_depth
        self._lock    = asyncio.Lock()

    async def __aenter__(self):
        async with self._lock:
            if self._waiting >= self._max_q:
                raise _QueueFullError(f"Queue full ({self._waiting}/{self._max_q})")
            self._waiting += 1
        await self._sem.acquire()
        return self

    async def __aexit__(self, *_):
        self._sem.release()
        async with self._lock:
            self._waiting = max(0, self._waiting - 1)

    @property
    def waiting(self) -> int:
        return self._waiting


class _QueueFullError(Exception):
    pass


# ─── Kernel ───────────────────────────────────────────────────────────────────

class Kernel:
    """
    The AI Kernel. Single process-wide instance.

    Usage (from API server):
        kernel = get_kernel()
        async for chunk in kernel.stream(message, session_id):
            yield chunk

        result = await kernel.process(message, session_id)
    """

    def __init__(self) -> None:
        self._gate     = RequestGate(MAX_ACTIVE_REQUESTS, MAX_QUEUE_DEPTH)
        self._router   = get_router()
        self._planner  = get_planner()
        self._governor = get_governor()
        self._watchdog = get_watchdog()
        self._requests_processed = 0
        self._requests_rejected  = 0

    # ── Primary streaming entry point ─────────────────────────────────────────

    async def stream(
        self,
        message: str,
        session_id: str = "default",
    ) -> AsyncIterator[dict]:
        """
        Async generator: yields SSE-ready dicts.
        Handles the full pipeline from classification to streaming response.

        Yields:
            {'status': ...}                  — status notification
            {'chunk': '...'}                 — text fragment
            {'done': True, 'result': {...}}  — completion signal
            {'error': '...'}                 — on failure
        """
        t0 = time.monotonic()

        # ── Safety gate ───────────────────────────────────────────────────────
        if self._watchdog.is_rejecting():
            yield {"error": "System under critical load — please retry in a moment."}
            self._requests_rejected += 1
            return

        # ── Queue admission ───────────────────────────────────────────────────
        try:
            async with self._gate:
                async for item in self._run_pipeline(message, session_id, t0):
                    yield item
        except _QueueFullError:
            self._requests_rejected += 1
            yield {"error": "Server busy — max 2 requests queued. Please retry."}

    # ── Blocking entry point (for non-streaming paths) ────────────────────────

    async def process(
        self,
        message: str,
        session_id: str = "default",
    ) -> InferenceResult:
        """
        Single-shot blocking process. Returns a complete InferenceResult.
        Internally collects all stream chunks.
        """
        t0        = time.monotonic()
        full_text = []
        result    = None

        async for item in self.stream(message, session_id):
            if "chunk" in item:
                full_text.append(item["chunk"])
            if "done" in item and item.get("result"):
                result = item["result"]
            if "error" in item:
                return InferenceResult(
                    text=item["error"],
                    model_used="none",
                    intent="error",
                    latency_s=time.monotonic() - t0,
                    complexity=0,
                    error=item["error"],
                    session_id=session_id,
                )

        if result:
            return InferenceResult(**result) if isinstance(result, dict) else result

        return InferenceResult(
            text="".join(full_text),
            model_used=self._governor.active_model or "none",
            intent="unknown",
            latency_s=time.monotonic() - t0,
            complexity=0,
            session_id=session_id,
        )

    # ── Core pipeline ─────────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        message: str,
        session_id: str,
        t0: float,
    ) -> AsyncIterator[dict]:

        memory   = get_memory(session_id)
        governor = self._governor

        # ── Step 1: Route ─────────────────────────────────────────────────────
        force = governor._force_model
        decision: RoutingDecision = self._router.route(message, force_model=force)

        # ── Step 2: Plan ──────────────────────────────────────────────────────
        ctx = memory.get_context()
        plan: ExecutionPlan = self._planner.plan(message, memory_ctx=ctx)

        # ── Step 3: Set working state ─────────────────────────────────────────
        working = WorkingState(
            task_id=uuid.uuid4().hex[:8],
            intent=decision.intent,
            model=decision.model,
            step_count=len(plan.steps),
        )
        memory.set_working(working)

        yield {
            "status": f"Processing [{decision.intent}]",
            "meta": {
                "model":      decision.model,
                "intent":     decision.intent,
                "complexity": decision.complexity,
                "queue":      self._gate.waiting,
            },
        }

        # ── Step 4: Dispatch ──────────────────────────────────────────────────

        try:
            # v14.1: Multi-step orchestration for complex tasks
            if needs_orchestration(decision):
                orchestrator = get_orchestrator()
                final_text = []
                async for item in orchestrator.orchestrate(
                    message, decision, session_id
                ):
                    if "chunk" in item:
                        final_text.append(item["chunk"])
                    yield item
                # Store result in memory
                full_text = "\n".join(final_text)
                if full_text:
                    memory.add_turn("user", message, model=None)
                    memory.add_turn("assistant", full_text, model=decision.model)

            elif decision.intent == Intent.GREETING:
                async for chunk in self._handle_greeting(plan, memory, session_id, t0):
                    yield chunk

            elif decision.intent == Intent.SWITCH:
                async for chunk in self._handle_switch(decision, memory, session_id, t0):
                    yield chunk

            elif decision.intent in (Intent.RECON, Intent.SECURITY, Intent.POWER_TOOL):
                async for chunk in self._handle_power_tool(
                    message, decision, memory, session_id, t0
                ):
                    yield chunk

            elif decision.intent == Intent.SYSTEM_CMD:
                async for chunk in self._handle_terminal(decision, memory, session_id, t0):
                    yield chunk

            elif decision.intent == Intent.TOOL_CALL:
                async for chunk in self._handle_tool(decision, memory, session_id, t0):
                    yield chunk

            else:
                # LLM inference (CHAT, CODING, REASONING, TRIVIAL, FILE_OP)
                async for chunk in self._handle_llm(
                    message, decision, plan, memory, session_id, t0
                ):
                    yield chunk

        except Exception as exc:
            logger.error("[Kernel] Pipeline error: %s", exc, exc_info=True)
            error_msg = f"Internal error: {exc}"
            yield {"error": error_msg}
            memory.clear_working()
            return

        # ── Step 5: Cleanup ───────────────────────────────────────────────────
        memory.clear_working()
        self._requests_processed += 1

    # ── Intent handlers ───────────────────────────────────────────────────────

    async def _handle_greeting(self, plan, memory, session_id, t0) -> AsyncIterator[dict]:
        text = plan.fast_reply or "Hello! How can I help you?"
        memory.add_turn("user",      "...", model=None)
        memory.add_turn("assistant", text,  model="fast-path")
        yield {"chunk": text}
        yield _done(text, "fast-path", Intent.GREETING, t0, session_id, plan.complexity)

    async def _handle_switch(self, decision, memory, session_id, t0) -> AsyncIterator[dict]:
        target = decision.command or "qwen"
        yield {"status": f"Switching model to {target}..."}

        ok = await self._governor.load(target)
        actual = self._governor.active_model or target

        if ok:
            msg = f"[OK] Switched to {actual.upper()}"
        else:
            msg = f"[WARN] Could not load {target} — using {actual}"

        memory.add_turn("user",      f"switch to {target}", model=None)
        memory.add_turn("assistant", msg, model="system")
        yield {"chunk": msg}
        result = _done_dict(msg, "system", Intent.SWITCH, t0, session_id, 1)
        result["switch_event"] = actual
        yield {"done": True, "result": result}

    async def _handle_terminal(self, decision, memory, session_id, t0) -> AsyncIterator[dict]:
        from val.tools.terminal import execute_terminal
        cmd = decision.command or ""

        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(None, lambda: execute_terminal(cmd))

        memory.add_turn("user",      decision.command or "terminal", model=None)
        memory.add_turn("assistant", output, model="terminal")
        yield {"chunk": output, "terminal": True, "command": cmd}
        yield _done(output, "terminal", Intent.SYSTEM_CMD, t0, session_id, 1)

    async def _handle_power_tool(
        self, message: str, decision, memory, session_id: str, t0: float,
    ) -> AsyncIterator[dict]:
        """
        Handle RECON and SECURITY intents via power_tools adapters.
        Streams tool output line-by-line for real-time feedback.
        """
        from val.tools.power_tools import parse_tool_command, get_adapter

        parsed = parse_tool_command(message)
        if not parsed:
            # Fallback to terminal execution
            async for chunk in self._handle_terminal(decision, memory, session_id, t0):
                yield chunk
            return

        tool_name, tool_args = parsed
        adapter = get_adapter(tool_name)

        if adapter is None:
            msg = f"[PowerTool] No adapter for '{tool_name}'."
            yield {"chunk": msg}
            yield _done(msg, "none", decision.intent, t0, session_id, 1)
            return

        if not adapter.is_installed():
            msg = f"[PowerTool] '{tool_name}' is not installed. Install it and add to PATH."
            yield {"chunk": msg, "terminal": True}
            yield _done(msg, "none", decision.intent, t0, session_id, 1)
            return

        yield {"status": f"Executing {tool_name}..."}

        # Stream output line-by-line for real-time feedback
        collected_output = []
        async for line in adapter.stream_execute(tool_args):
            collected_output.append(line)
            yield {"chunk": line, "terminal": True, "command": f"{tool_name} {tool_args}"}

        full_output = "".join(collected_output)
        memory.add_turn("user", message, model=None)
        memory.add_turn("assistant", full_output, model=tool_name)

        yield _done(full_output, tool_name, decision.intent, t0, session_id, 2)

    async def _handle_tool(self, decision, memory, session_id, t0) -> AsyncIterator[dict]:
        from val.tools.executor import get_tool_registry
        registry = get_tool_registry()
        tool_name = decision.tool or "calculator"
        tool = registry.get(tool_name)

        if tool is None:
            msg = f"[Tool] '{tool_name}' not available."
            yield {"chunk": msg}
            yield _done(msg, "none", Intent.TOOL_CALL, t0, session_id, 1)
            return

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: tool.run({"query": decision.command or ""})
            )
        except Exception as e:
            result = f"[Tool error: {e}]"

        memory.add_turn("user",      decision.command or "tool", model=None)
        memory.add_turn("assistant", str(result), model=tool_name)
        yield {"chunk": str(result)}
        yield _done(str(result), tool_name, Intent.TOOL_CALL, t0, session_id, 1)

    async def _handle_llm(
        self,
        message: str,
        decision: RoutingDecision,
        plan: ExecutionPlan,
        memory,
        session_id: str,
        t0: float,
    ) -> AsyncIterator[dict]:
        """
        Stream LLM inference via governor.stream().
        Loads model if not already loaded.
        """
        model_hint = decision.model if decision.model not in ("none", "fast-path") else None

        # Ensure model is loaded
        if model_hint and self._governor.active_model != model_hint:
            yield {"status": f"Loading {model_hint}..."}
            ok = await self._governor.load(model_hint)
            if not ok:
                msg = "[Kernel] No model available — check available RAM."
                yield {"error": msg}
                return

        # Build prompt from memory context
        ctx   = memory.get_context()
        prompt = _build_prompt(message, ctx)

        # Stream tokens
        collected: List[str] = []
        word_count = 0

        async for chunk in self._governor.stream(
            prompt, history=ctx, model_hint=model_hint
        ):
            if not chunk:
                continue
            words_in_chunk = len(chunk.split())
            if word_count + words_in_chunk > MAX_RESPONSE_WORDS:
                # Trim to cap
                remaining = MAX_RESPONSE_WORDS - word_count
                trimmed_words = chunk.split()[:remaining]
                chunk = " ".join(trimmed_words)
                collected.append(chunk)
                yield {"chunk": chunk}
                break
            collected.append(chunk)
            word_count += words_in_chunk
            yield {"chunk": chunk}

        full_text = "".join(collected).strip()
        model_used = self._governor.active_model or "unknown"

        # Store in memory
        memory.add_turn("user",      message,    model=None)
        memory.add_turn("assistant", full_text,  model=model_used)

        yield _done(full_text, model_used, decision.intent, t0, session_id, decision.complexity)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "requests_processed": self._requests_processed,
            "requests_rejected":  self._requests_rejected,
            "queue_waiting":      self._gate.waiting,
            "queue_capacity":     MAX_QUEUE_DEPTH,
            "governor":           self._governor.status(),
            "watchdog":           (
                self._watchdog.snapshot().as_dict()
                if self._watchdog.snapshot() else {"healthy": True}
            ),
        }


# ─── Prompt builder ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are VAL, a concise AI operator. "
    "Answer directly. No filler."
)

def _build_prompt(message: str, ctx: List[dict]) -> str:
    """Build a simple text prompt from system + history + user message."""
    parts = [_SYSTEM_PROMPT, ""]
    # Inject max 2 turns (1 pair) in LOW_RAM_MODE, 4 turns otherwise
    import os
    low_ram = os.environ.get('LOW_RAM_MODE', 'true').lower() in ('true', '1', 'yes')
    max_ctx = 2 if low_ram else 4
    for turn in ctx[-max_ctx:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        label = "User" if role == "user" else "VAL"
        parts.append(f"{label}: {content}")
    parts.append(f"User: {message}")
    parts.append("VAL:")
    return "\n".join(parts)


# ─── SSE helpers ──────────────────────────────────────────────────────────────

def _done(text, model, intent, t0, session_id, complexity) -> dict:
    return {"done": True, "result": _done_dict(text, model, intent, t0, session_id, complexity)}

def _done_dict(text, model, intent, t0, session_id, complexity) -> dict:
    return {
        "text":       text,
        "model_used": model,
        "intent":     intent,
        "latency_s":  round(time.monotonic() - t0, 3),
        "complexity": complexity,
        "session_id": session_id,
    }


# ─── Singleton ────────────────────────────────────────────────────────────────

_kernel: Optional[Kernel] = None


def get_kernel() -> Kernel:
    """Return (and create if needed) the process-wide Kernel singleton."""
    global _kernel
    if _kernel is None:
        _kernel = Kernel()
    return _kernel


# ─── Backward-compat shim ─────────────────────────────────────────────────────
# ValEngine and get_engine() are kept so that val.agents.agent and any other
# pre-refactor code that imports them continues to work without changes.

import asyncio as _asyncio
import threading as _threading

# One global event loop for the compat shim (runs in a background thread so
# it never blocks the main thread, and never conflicts with uvicorn's loop).
_compat_loop: Optional[_asyncio.AbstractEventLoop] = None
_compat_lock  = _threading.Lock()


def _get_compat_loop() -> _asyncio.AbstractEventLoop:
    global _compat_loop
    with _compat_lock:
        if _compat_loop is None or _compat_loop.is_closed():
            loop = _asyncio.new_event_loop()
            t = _threading.Thread(target=loop.run_forever, daemon=True,
                                  name="val-compat-loop")
            t.start()
            _compat_loop = loop
        return _compat_loop


def _run_sync(coro):
    """Run an async coroutine synchronously from any thread."""
    loop = _get_compat_loop()
    fut  = _asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=120)


class ValEngine:
    """
    Synchronous engine shim — wraps the async Kernel.
    Drop-in replacement for the pre-refactor ValEngine class.
    Used by val.agents.agent and legacy code.
    """

    def __init__(self, session_id: str = "default"):
        self._session_id = session_id
        self._kernel     = get_kernel()
        self._requests   = 0
        self._tokens_in  = 0
        self._tokens_out = 0
        self._latencies: List[float] = []

    def query(self, prompt: str, force_model: Optional[str] = None, **_) -> "InferenceResult":
        """Blocking single-turn query."""
        if force_model:
            get_governor().configure(force_model=force_model)
        result = _run_sync(self._kernel.process(prompt, session_id=self._session_id))
        self._track(result)
        return result

    def stream(self, prompt: str, **_) -> Iterator[str]:
        """Synchronous streaming — yields text chunks."""
        # We can't do true async streaming from sync context without a complex
        # bridge, so collect via process() and yield the full text.
        result = self.query(prompt)
        yield result.text

    def reset_memory(self) -> None:
        """Clear this session's conversation memory."""
        from val.state.memory import get_memory_store
        get_memory_store().reset(self._session_id)

    def get_context_stats(self) -> dict:
        from val.state.memory import get_memory
        mem = get_memory(self._session_id)
        return mem.status()

    def get_metrics(self) -> dict:
        avg = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.0
        return {
            "total_requests": self._requests,
            "total_tokens_in":  self._tokens_in,
            "total_tokens_out": self._tokens_out,
            "avg_latency_s": round(avg, 3),
        }

    def _track(self, result: "InferenceResult") -> None:
        self._requests   += 1
        self._tokens_in  += len(result.text.split()) // 2   # rough estimate
        self._tokens_out += len(result.text.split())
        self._latencies.append(result.latency_s)
        if len(self._latencies) > 200:
            self._latencies = self._latencies[-100:]


def get_engine(session_id: str = "default") -> ValEngine:
    """
    Backward-compat factory. Returns a ValEngine shim wrapping the Kernel.
    New code should use get_kernel() directly.
    """
    return ValEngine(session_id=session_id)


# Let VAL_SYSTEM_PROMPT also be importable from here (some old code needs it)
VAL_SYSTEM_PROMPT = _SYSTEM_PROMPT
