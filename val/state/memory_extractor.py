"""
VAL Memory Extractor v15.0 — Auto Fact Extraction
====================================================
Extracts facts from conversations in the background.
Pattern-based: "I prefer X", "my device is Y", "remember that Z"
Stores in persistent_memory.py.
"""

from __future__ import annotations
import logging, re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("val.memory.extractor")

# ─── Extraction Patterns ──────────────────────────────────────────────────────

_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Personal preferences
    (re.compile(r"(?:i\s+prefer|i\s+like|i\s+use|my\s+favorite\s+is)\s+(.+?)(?:\.|$)", re.I),
     "personal", "preference"),

    # Device info
    (re.compile(r"(?:my\s+(?:device|laptop|pc|computer|phone)\s+is|i\s+(?:have|use)\s+(?:a|an))\s+(.+?)(?:\.|$)", re.I),
     "personal", "device"),

    # Name
    (re.compile(r"(?:my\s+name\s+is|i\s+am|call\s+me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", re.I),
     "personal", "name"),

    # Remember commands
    (re.compile(r"(?:remember\s+that|note\s+that|keep\s+in\s+mind)\s+(.+?)(?:\.|$)", re.I),
     "context", "remembered"),

    # Project info
    (re.compile(r"(?:i(?:'m|\s+am)\s+working\s+on|my\s+project\s+is)\s+(.+?)(?:\.|$)", re.I),
     "project", "current_project"),

    # Location
    (re.compile(r"(?:i\s+live\s+in|i(?:'m|\s+am)\s+from|i(?:'m|\s+am)\s+in)\s+(.+?)(?:\.|$)", re.I),
     "personal", "location"),

    # Schedule
    (re.compile(r"(?:i\s+(?:usually|always)\s+(?:work|start|wake)\s+(?:at|around))\s+(.+?)(?:\.|$)", re.I),
     "personal", "schedule"),
]


def extract_facts(text: str) -> List[Dict]:
    """
    Extract factual information from user text.
    Returns list of {domain, key, value} dicts.
    """
    facts = []
    for pattern, domain, key_prefix in _PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if len(value) < 3 or len(value) > 200:
                continue
            # Deduplicate key
            key = f"{key_prefix}_{_slug(value[:30])}"
            facts.append({
                "domain": domain,
                "key": key,
                "value": value,
                "source": "auto_extract",
            })
    return facts


def _slug(text: str) -> str:
    """Convert text to a slug for use as a key."""
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:40]


def process_message(text: str) -> int:
    """
    Extract facts from a message and store them.
    Returns number of facts stored.
    """
    facts = extract_facts(text)
    if not facts:
        return 0

    from val.state.persistent_memory import get_persistent_memory
    mem = get_persistent_memory()

    stored = 0
    for fact in facts:
        if mem.store_fact(
            key=fact["key"],
            value=fact["value"],
            domain=fact["domain"],
            source=fact["source"],
        ):
            stored += 1
            logger.info(
                "[Extractor] Stored: [%s] %s = %s",
                fact["domain"], fact["key"], fact["value"][:50],
            )
    return stored
