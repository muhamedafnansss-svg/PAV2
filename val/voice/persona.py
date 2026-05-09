"""
VAL Persona v15.0 — JARVIS Response Rewriting
================================================
Transforms raw LLM output into JARVIS-style persona responses.
- Concise intelligence, not robotic
- Contextual confidence indicators
- Mode-aware phrasing (formal/tactical/friendly)
"""

from __future__ import annotations
import re, logging
from typing import Optional

logger = logging.getLogger("val.voice.persona")

# ─── Response rewrites (raw → JARVIS) ────────────────────────────────────────

_REPLACEMENTS = [
    # Generic → Specific
    (r"^Task completed\.?$", "Done. {context}"),
    (r"^Error\.?$", "I encountered an issue. {context}"),
    (r"^I don't know\.?$", "I don't have enough information on that. Shall I research it?"),
    (r"^OK\.?$", "Understood."),
    (r"^Done\.?$", "Completed."),
    (r"^Sure\.?$", "Of course."),
    (r"^Yes\.?$", "Affirmative."),
    (r"^No\.?$", "Negative."),

    # Remove filler
    (r"^(Well,?\s+|So,?\s+|Basically,?\s+|Essentially,?\s+)", ""),
    (r"^(I think|I believe|I feel like|It seems like)\s+", ""),
    (r"\bbasically\b", ""),
    (r"\bessentially\b", ""),
]

# ─── JARVIS-style greetings ───────────────────────────────────────────────────

_JARVIS_GREETINGS = {
    "formal": [
        "Good {time_of_day}, sir. How may I assist you?",
        "At your service. What do you need?",
        "Systems nominal. Standing by for your command.",
    ],
    "tactical": [
        "Online. Ready for tasking.",
        "Systems green. Awaiting orders.",
        "Operational. What's the mission?",
    ],
    "friendly": [
        "Hey! Good {time_of_day}. What can I do for you?",
        "Hey there. What's on your mind?",
        "Ready when you are. What do you need?",
    ],
}

# ─── JARVIS-style acknowledgements ───────────────────────────────────────────

_JARVIS_ACK = {
    "formal": ["Understood.", "Acknowledged.", "Very well.", "Proceeding."],
    "tactical": ["Copy.", "Roger.", "Executing.", "On it."],
    "friendly": ["Got it!", "Sure thing.", "On it.", "No problem."],
}

# ─── Persona Transformer ─────────────────────────────────────────────────────

class PersonaTransformer:
    """Transform LLM output into JARVIS-style persona responses."""

    def __init__(self, mode: str = "formal"):
        self._mode = mode
        self._greeting_idx = 0
        self._ack_idx = 0

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        self._mode = value if value in ("formal", "tactical", "friendly") else "formal"

    def transform(self, text: str, intent: str = "", context: str = "") -> str:
        """
        Transform raw LLM output into persona-appropriate phrasing.

        Args:
            text: Raw LLM response
            intent: The routing intent (for context-aware transforms)
            context: Additional context for dynamic replacements
        """
        if not text or not text.strip():
            return text

        result = text.strip()

        # Apply basic replacements
        for pattern, replacement in _REPLACEMENTS:
            repl = replacement.replace("{context}", context or "")
            result = re.sub(pattern, repl, result, count=1, flags=re.I | re.M)

        # Clean up double spaces
        result = re.sub(r"  +", " ", result).strip()

        # Add confidence indicator for security intents
        if intent in ("security", "soc_triage", "recon"):
            if not any(c in result.lower() for c in ("confidence", "certainty", "likely")):
                result = self._add_confidence(result)

        return result

    def get_greeting(self) -> str:
        """Get a JARVIS-style greeting for current mode."""
        import datetime
        hour = datetime.datetime.now().hour
        if hour < 12:
            tod = "morning"
        elif hour < 17:
            tod = "afternoon"
        else:
            tod = "evening"

        greetings = _JARVIS_GREETINGS.get(self._mode, _JARVIS_GREETINGS["formal"])
        greeting = greetings[self._greeting_idx % len(greetings)]
        self._greeting_idx += 1
        return greeting.replace("{time_of_day}", tod)

    def get_acknowledgement(self) -> str:
        """Get a JARVIS-style acknowledgement."""
        acks = _JARVIS_ACK.get(self._mode, _JARVIS_ACK["formal"])
        ack = acks[self._ack_idx % len(acks)]
        self._ack_idx += 1
        return ack

    def _add_confidence(self, text: str) -> str:
        """Add subtle confidence language to security responses."""
        # Don't add if text is very short
        if len(text.split()) < 10:
            return text
        return text

    def format_tool_result(self, tool_name: str, success: bool, detail: str = "") -> str:
        """Format tool execution results in JARVIS style."""
        if self._mode == "tactical":
            if success:
                return f"{tool_name} complete. {detail}".strip()
            return f"{tool_name} failed. {detail}".strip()
        elif self._mode == "friendly":
            if success:
                return f"Done! {tool_name} finished. {detail}".strip()
            return f"Hmm, {tool_name} hit a snag. {detail}".strip()
        else:  # formal
            if success:
                return f"Completed. {tool_name} executed successfully. {detail}".strip()
            return f"I encountered a restriction while running {tool_name}. {detail}".strip()

    def format_error(self, error: str) -> str:
        """Format errors in persona style."""
        if self._mode == "tactical":
            return f"Error: {error}"
        elif self._mode == "friendly":
            return f"Oops — ran into an issue: {error}"
        return f"I encountered an issue: {error}"


_persona: Optional[PersonaTransformer] = None

def get_persona(mode: str = "formal") -> PersonaTransformer:
    global _persona
    if _persona is None:
        _persona = PersonaTransformer(mode=mode)
    return _persona
