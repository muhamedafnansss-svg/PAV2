"""
VAL Intent Router
=================
Fast intent routing based on natural language input.
"""

from enum import Enum
import re
from dataclasses import dataclass
from typing import Optional

class Intent(str, Enum):
    GREETING = "greeting"
    SWITCH = "switch"
    MODE_SET = "mode_set"
    SYSTEM_CMD = "system_cmd"
    POWER_TOOL = "power_tool"
    CODING = "coding"
    RECON = "recon"
    SECURITY = "security"
    RESEARCH = "research"
    REASONING = "reasoning"
    CHAT = "chat"
    FILE_OP = "file_op"
    AGENT = "agent"
    ANALYZE = "analyze"
    CLEANUP = "cleanup"
    KNOWLEDGE = "knowledge"
    REPO_INTEL = "repo_intel"
    FIREWALL = "firewall"
    SOC_TRIAGE = "soc_triage"
    EXPLOIT_GEN = "exploit_gen"
    PAYLOAD_CRAFT = "payload_craft"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    VOLUME = "volume"
    CLIPBOARD = "clipboard"
    FILE_SEARCH = "file_search"
    VOICE_MODE = "voice_mode"
    VOICE_AUTH = "voice_auth"
    SYS_CONTROL = "sys_control"
    TOOL_CALL = "tool_call"

@dataclass
class RoutingDecision:
    intent: Intent
    model: str
    complexity: int
    tool: Optional[str] = None
    command: Optional[str] = None

class Router:
    def __init__(self):
        pass

    def route(self, message: str) -> RoutingDecision:
        msg_lower = message.lower()

        # Tool Calls (System Control)
        if re.match(r"^(open|launch|start|run|close|quit|kill|stop|set volume|mute|volume up|volume down|copy .* to clipboard|read clipboard|find file).*?", msg_lower):
            return RoutingDecision(intent=Intent.SYS_CONTROL, model="none", complexity=0, tool="system_control", command=message)

        if msg_lower.startswith(("terminal", "cmd", "sh", "bash")):
            cmd = message.split(" ", 1)[1] if " " in message else ""
            return RoutingDecision(intent=Intent.SYSTEM_CMD, model="none", complexity=0, tool="terminal", command=cmd)

        if "analyze code" in msg_lower or "code analysis" in msg_lower:
            return RoutingDecision(intent=Intent.ANALYZE, model="qwen", complexity=2, tool="analyzer", command=message)

        # Complex reasoning & coding
        if any(w in msg_lower for w in ["write code", "refactor", "debug", "create a script"]):
            return RoutingDecision(intent=Intent.CODING, model="qwen", complexity=2)

        # Security & SOC
        if any(w in msg_lower for w in ["scan", "exploit", "payload", "firewall", "nmap", "hashcat"]):
            return RoutingDecision(intent=Intent.SECURITY, model="mistral", complexity=1)

        # Greetings
        if msg_lower in ["hi", "hello", "hey", "wake up", "jarvis"]:
            return RoutingDecision(intent=Intent.GREETING, model="tinyllama", complexity=0)

        # Default fallback to Chat with default model (usually tinyllama or qwen depending on .env)
        return RoutingDecision(intent=Intent.CHAT, model="tinyllama", complexity=1)

_router = None
def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router

class ModelTier(Enum):
    TIER_0 = "none"
    TIER_1 = "tinyllama"
    TIER_2 = "mistral"
    TIER_3 = "qwen"

ModelTier.UTILITY = ModelTier.TIER_1
ModelTier.GENERAL = ModelTier.TIER_2
ModelTier.COMPLEX = ModelTier.TIER_3
TIER_0 = ModelTier.TIER_0
TIER_1 = ModelTier.TIER_1
TIER_2 = ModelTier.TIER_2
TIER_3 = ModelTier.TIER_3

def route_prompt(prompt, **kwargs):
    d = get_router().route(prompt)
    tier = ModelTier.TIER_1
    if d.model == "none": tier = ModelTier.TIER_0
    elif d.model == "mistral": tier = ModelTier.TIER_2
    elif d.model == "qwen": tier = ModelTier.TIER_3
    return type("Routing", (), {"tier": tier, "model": d.model, "intent": d.intent})

class RequestGate:
    MAX_QUEUE = 10
    def __init__(self, *args, **kwargs):
        pass
    def wait_for_capacity(self, *args, **kwargs):
        pass
    def acquire(self):
        pass
    def release(self):
        pass

def _get_pressure_cap(*args, **kwargs):
    pass
