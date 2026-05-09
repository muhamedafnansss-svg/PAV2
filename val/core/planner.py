"""
VAL Task Planner — Deterministic Execution Planning Layer v2
=============================================================
Converts raw user input into a structured ExecutionPlan.

v2 Changes:
  - Added RECON intent (nmap, whois, dig, traceroute, ping, shodan, subfinder, amass)
  - Added SECURITY intent (hashcat, sqlmap, nikto, ffuf, gobuster)
  - Added FILE_OP intent (read/write/list files)
  - Updated model assignments for Qwen 2.5 Coder
  - Priority: GREETING → SWITCH → RECON → SECURITY → SYSTEM_CMD → FILE_OP → TOOL_CALL → CODING → REASONING → CHAT

Design rules:
  - ZERO randomness. Same input → same plan. Always.
  - ZERO LLM calls. Pure keyword/heuristic analysis.
  - ZERO blocking. All operations are synchronous and CPU-only.
  - Complexity scored 1–5 (drives model selection + step decomposition)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("val.planner")


# ─── Intent Classes ───────────────────────────────────────────────────────────

class Intent:
    GREETING    = "GREETING"     # hi, hello, hey — fast-path, no model
    TRIVIAL     = "TRIVIAL"      # short, simple — qwen
    CHAT        = "CHAT"         # conversational — qwen
    REASONING   = "REASONING"    # explain, summarize, analyze — qwen
    CODING      = "CODING"       # code, debug, function, script — qwen
    SYSTEM_CMD  = "SYSTEM_CMD"   # run, exec, terminal — tool layer only
    RECON       = "RECON"        # nmap, whois, dig, traceroute, ping, shodan, subfinder, amass
    SECURITY    = "SECURITY"     # hashcat, sqlmap, nikto, ffuf, gobuster
    TOOL_CALL   = "TOOL_CALL"    # file, search, calc — tool layer
    FILE_OP     = "FILE_OP"      # read/write/list files
    SWITCH      = "SWITCH"       # "switch to gemma" — control plane


# ─── Model Assignment (deterministic) ────────────────────────────────────────

_INTENT_MODEL: dict[str, str] = {
    Intent.GREETING:   "fast-path",     # no model needed
    Intent.TRIVIAL:    "qwen",
    Intent.CHAT:       "qwen",
    Intent.REASONING:  "qwen",
    Intent.CODING:     "qwen",
    Intent.SYSTEM_CMD: "none",          # tool layer; no model
    Intent.RECON:      "none",          # tool layer; LLM summarizes after
    Intent.SECURITY:   "none",          # tool layer; LLM summarizes after
    Intent.TOOL_CALL:  "none",          # tool layer; no model
    Intent.FILE_OP:    "none",          # tool layer; no model
    Intent.SWITCH:     "none",          # control plane
}


# ─── Execution Step ───────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    index:       int
    action:      str            # 'llm_infer' | 'tool_call' | 'fast_reply' | 'switch_model' | 'recon' | 'security'
    payload:     str            # prompt fragment or command or model name
    tool_name:   Optional[str] = None
    tool_args:   dict          = field(default_factory=dict)
    depends_on:  Optional[int] = None   # step index this step waits for


# ─── Execution Plan ───────────────────────────────────────────────────────────

@dataclass
class ExecutionPlan:
    intent:       str
    model:        str
    steps:        List[PlanStep]
    tools:        List[str]         # tool names required
    complexity:   int               # 1 = trivial, 5 = complex multi-step
    memory_ctx:   List[dict]        = field(default_factory=list)
    fast_reply:   Optional[str]    = None    # pre-baked reply (no LLM needed)
    switch_target: Optional[str]  = None    # model to switch to


# ─── Keyword classifiers (compiled once at import) ────────────────────────────

# Greeting detection
_GREETING_RE = re.compile(
    r"^(hi|hello|hey|yo|sup|what'?s up|how are you|good (morning|evening|night)|"
    r"thanks?|thank you|ty|thx|bye|goodbye|ok|okay|k)[\s!?.]*$",
    re.IGNORECASE,
)

# Switch command: "switch to gemma"
_SWITCH_RE = re.compile(
    r"\b(switch|use|load|change)\s+(to\s+)?(qwen|gemma|mistral|phi.?mini|tinyllama|phi|tiny)\b",
    re.IGNORECASE,
)

# Recon / network intelligence tools
_RECON_RE = re.compile(
    r"(?:^|\b)(nmap|whois|dig|nslookup|traceroute|tracert|ping|shodan|subfinder|amass)\b|"
    r"^scan\s+\S|^list\s+ports\b|^dns\s+lookup\b|^trace\s+\S|^lookup\s+\S",
    re.IGNORECASE,
)

# Security / offensive tools
_SECURITY_RE = re.compile(
    r"(?:^|\b)(hashcat|crack\s+hash|sqlmap|nikto|ffuf|gobuster|"
    r"brute\s*force|exploit|fuzz|directory\s+scan)\b",
    re.IGNORECASE,
)

# Terminal / system commands: "run ls", "exec date", "$ ps aux"
_TERMINAL_RE = re.compile(
    r"^(\$\s*|run\s+|exec(?:ute)?\s+|cmd\s+|shell\s+|terminal\s+)",
    re.IGNORECASE,
)

# File operations
_FILE_RE = re.compile(
    r"\b(read\s+file|write\s+file|list\s+files|show\s+file|cat\s+\S|"
    r"create\s+file|save\s+to|open\s+file)\b",
    re.IGNORECASE,
)

# Code/debugging intent keywords
_CODE_RE = re.compile(
    r"\b(code|debug|function|class|script|algorithm|implement|refactor|bug|error|"
    r"syntax|import|module|package|compile|unittest|pytest|async|await|sql|query|"
    r"regex|api\s+endpoint|dockerfile|kubernetes|git\s+merge|pull\s+request|"
    r"write\s+a?\s*python|write\s+a?\s*script|write\s+a?\s*program)\b",
    re.IGNORECASE,
)

# Reasoning / analysis intent keywords
_REASON_RE = re.compile(
    r"\b(explain|analyze|analyse|summarize|summarise|compare|evaluate|difference|"
    r"pros\s+and\s+cons|why\s+is|how\s+does|what\s+is\s+the\s+reason|describe|"
    r"outline|review|assess|critique|interpret|meaning\s+of|significance)\b",
    re.IGNORECASE,
)

# Tool-call hints (file ops, search, math)
_TOOL_RE = re.compile(
    r"\b(calculate|compute|what\s+is\s+\d|find\s+file|read\s+file|list\s+files|"
    r"search|lookup|weather|time\s+in|convert|translate|base64|hash|checksum)\b",
    re.IGNORECASE,
)

# Greeting fast-path replies (pre-baked, no LLM)
_GREETING_REPLIES: dict[str, str] = {
    "hi":           "Hey! How can I help you?",
    "hello":        "Hello! What can I do for you?",
    "hey":          "Hey! What do you need?",
    "yo":           "What is up?",
    "sup":          "What is up?",
    "thanks":       "You are welcome!",
    "thank you":    "You are welcome!",
    "ty":           "Happy to help!",
    "thx":          "Happy to help!",
    "bye":          "Goodbye! Come back anytime.",
    "goodbye":      "Goodbye! Take care.",
    "ok":           "Got it.",
    "okay":         "Got it.",
    "k":            "Got it.",
}


# ─── Planner ─────────────────────────────────────────────────────────────────

class Planner:
    """
    Deterministic task planner. Stateless — all methods are pure functions.

    Usage:
        planner = get_planner()
        plan = planner.plan(user_input, memory_ctx=[...])
    """

    def plan(self, user_input: str, memory_ctx: Optional[List[dict]] = None) -> ExecutionPlan:
        """
        Entry point. Returns a fully populated ExecutionPlan.
        No side effects. No I/O. Deterministic.
        """
        text = user_input.strip()
        intent = self._classify(text)
        model  = _INTENT_MODEL[intent]
        steps  = self._decompose(text, intent)
        tools  = [s.tool_name for s in steps if s.tool_name]
        cmplx  = self._complexity(text, intent)
        fast   = self._fast_reply(text, intent)
        switch = self._switch_target(text, intent)

        plan = ExecutionPlan(
            intent=intent,
            model=model,
            steps=steps,
            tools=list(set(tools)),
            complexity=cmplx,
            memory_ctx=memory_ctx or [],
            fast_reply=fast,
            switch_target=switch,
        )

        logger.debug(
            "[Planner] intent=%s model=%s complexity=%d steps=%d",
            intent, model, cmplx, len(steps),
        )
        return plan

    # ── Classification ────────────────────────────────────────────────────────

    def _classify(self, text: str) -> str:
        lower = text.lower().strip()

        # Greeting (highest priority — no model needed)
        if _GREETING_RE.match(lower):
            return Intent.GREETING

        # Model switch command
        if _SWITCH_RE.search(lower):
            return Intent.SWITCH

        # Recon / network tools (before SYSTEM_CMD to catch "run nmap" correctly)
        if _RECON_RE.search(lower):
            return Intent.RECON

        # Security / offensive tools
        if _SECURITY_RE.search(lower):
            return Intent.SECURITY

        # Terminal / shell commands: "run ls", "exec date", "$ ps aux"
        if _TERMINAL_RE.match(lower):
            return Intent.SYSTEM_CMD

        # File operations
        if _FILE_RE.search(lower):
            return Intent.FILE_OP

        # Tool calls (calculator, file ops, etc.)
        if _TOOL_RE.search(lower):
            return Intent.TOOL_CALL

        # Coding intent (high specificity keywords → qwen)
        if _CODE_RE.search(lower):
            return Intent.CODING

        # Reasoning intent (explain / analyze → qwen)
        if _REASON_RE.search(lower):
            return Intent.REASONING

        # Length-based fallback
        word_count = len(text.split())
        if word_count <= 8:
            return Intent.TRIVIAL   # short queries → qwen

        return Intent.CHAT           # everything else → qwen

    # ── Decomposition ─────────────────────────────────────────────────────────

    def _decompose(self, text: str, intent: str) -> List[PlanStep]:
        """
        Build the ordered step list for this plan.
        """
        steps: List[PlanStep] = []

        if intent == Intent.GREETING:
            steps.append(PlanStep(
                index=0, action="fast_reply",
                payload=self._fast_reply(text, intent) or "Hello!",
            ))

        elif intent == Intent.SWITCH:
            target = self._switch_target(text, intent) or "qwen"
            steps.append(PlanStep(
                index=0, action="switch_model", payload=target,
            ))

        elif intent == Intent.SYSTEM_CMD:
            cmd = self._extract_command(text)
            steps.append(PlanStep(
                index=0, action="tool_call", payload=cmd,
                tool_name="terminal", tool_args={"command": cmd},
            ))

        elif intent == Intent.RECON:
            # Step 1: execute the recon tool
            steps.append(PlanStep(
                index=0, action="recon", payload=text,
                tool_name="power_tool",
            ))
            # Step 2: LLM summarizes the output
            steps.append(PlanStep(
                index=1, action="llm_infer",
                payload="Summarize the scan results above. Highlight key findings.",
                depends_on=0,
            ))

        elif intent == Intent.SECURITY:
            steps.append(PlanStep(
                index=0, action="security", payload=text,
                tool_name="power_tool",
            ))

        elif intent == Intent.FILE_OP:
            steps.append(PlanStep(
                index=0, action="tool_call", payload=text,
                tool_name="file_ops",
            ))

        elif intent == Intent.TOOL_CALL:
            steps.append(PlanStep(
                index=0, action="tool_call", payload=text,
                tool_name="calculator",
            ))

        elif intent == Intent.CODING and len(text.split()) > 50:
            # Complex coding: clarify intent → then generate
            steps.append(PlanStep(
                index=0, action="llm_infer",
                payload=f"[PLAN: analyze request]\n{text}",
            ))
            steps.append(PlanStep(
                index=1, action="llm_infer",
                payload=f"[PLAN: generate code]\n{text}",
                depends_on=0,
            ))
        else:
            # Default: single LLM inference step
            steps.append(PlanStep(
                index=0, action="llm_infer", payload=text,
            ))

        return steps

    # ── Complexity scorer ─────────────────────────────────────────────────────

    def _complexity(self, text: str, intent: str) -> int:
        if intent in (Intent.GREETING, Intent.SWITCH, Intent.SYSTEM_CMD, Intent.FILE_OP):
            return 1

        if intent in (Intent.RECON, Intent.SECURITY):
            return 2  # tool execution, not LLM-heavy

        words = len(text.split())

        if intent == Intent.TRIVIAL:
            return 1 if words <= 5 else 2

        if intent == Intent.CHAT:
            return 2

        if intent == Intent.REASONING:
            return 3 if words < 40 else 4

        if intent == Intent.CODING:
            return 4 if words < 80 else 5

        return 2

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fast_reply(self, text: str, intent: str) -> Optional[str]:
        if intent != Intent.GREETING:
            return None
        key = text.lower().strip().rstrip("!?.")
        return _GREETING_REPLIES.get(key)

    def _switch_target(self, text: str, intent: str) -> Optional[str]:
        if intent != Intent.SWITCH:
            return None
        m = _SWITCH_RE.search(text)
        if not m:
            return None
        raw = m.group(3).lower()
        if "qwen" in raw:     return "qwen"
        if "gemma" in raw:    return "gemma"
        if "mistral" in raw:  return "mistral"
        if "phi" in raw:      return "phi-mini"
        if "tiny" in raw:     return "tinyllama"
        return raw

    def _extract_command(self, text: str) -> str:
        """Strip the leading trigger prefix and return the actual command."""
        m = _TERMINAL_RE.match(text)
        if m:
            return text[m.end():].strip()
        return text.strip()


# ─── Singleton ────────────────────────────────────────────────────────────────

_planner: Optional[Planner] = None


def get_planner() -> Planner:
    """Return (and create if needed) the process-wide Planner singleton."""
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner
