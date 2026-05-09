"""
VAL Wake Word v15.0 — Lightweight Keyword Spotting
====================================================
Low-latency wake word detection for JARVIS-style activation.
Supports: "Hey VAL", "Jarvis", "Commander"
Uses VAD + short-window STT for wake detection.
"""

from __future__ import annotations
import logging, re, threading, time
from typing import Callable, List, Optional

logger = logging.getLogger("val.voice.wake")

DEFAULT_WAKE_PHRASES = ["hey val", "jarvis", "commander"]

# Fuzzy match patterns for wake phrases (handles STT quirks)
_WAKE_PATTERNS = [
    re.compile(r"\bhey\s*val\b", re.I),
    re.compile(r"\bjarvis\b", re.I),
    re.compile(r"\bcommander\b", re.I),
    # Common STT misheard variants
    re.compile(r"\bhey\s*vow\b", re.I),
    re.compile(r"\bhey\s*vowel\b", re.I),
    re.compile(r"\bjervis\b", re.I),
]

class WakeWordDetector:
    """Detect wake words from transcribed text or audio stream."""

    def __init__(self, wake_phrases: Optional[List[str]] = None):
        self._phrases = wake_phrases or DEFAULT_WAKE_PHRASES
        self._custom_patterns: List[re.Pattern] = []
        self._on_wake: Optional[Callable[[str], None]] = None
        self._active = False
        self._detections = 0

        # Build custom patterns from phrases
        for phrase in self._phrases:
            words = phrase.strip().split()
            pattern = r"\b" + r"\s*".join(re.escape(w) for w in words) + r"\b"
            self._custom_patterns.append(re.compile(pattern, re.I))

    def check_text(self, text: str) -> Optional[str]:
        """Check if text contains a wake phrase. Returns matched phrase or None."""
        text = text.strip().lower()
        if not text:
            return None

        # Check built-in patterns
        for pattern in _WAKE_PATTERNS:
            if pattern.search(text):
                self._detections += 1
                matched = pattern.pattern.replace(r"\b", "").replace(r"\s*", " ")
                logger.info("[Wake] Detected: '%s' in '%s'", matched, text)
                return matched

        # Check custom patterns
        for pattern in self._custom_patterns:
            if pattern.search(text):
                self._detections += 1
                return pattern.pattern
        return None

    def set_wake_callback(self, callback: Callable[[str], None]):
        self._on_wake = callback

    def add_phrase(self, phrase: str):
        words = phrase.strip().split()
        pattern = r"\b" + r"\s*".join(re.escape(w) for w in words) + r"\b"
        self._custom_patterns.append(re.compile(pattern, re.I))
        self._phrases.append(phrase.lower())
        logger.info("[Wake] Added phrase: %s", phrase)

    @property
    def phrases(self) -> List[str]:
        return list(self._phrases)

    def status(self) -> dict:
        return {
            "phrases": self._phrases,
            "detections": self._detections,
            "active": self._active,
        }

_detector: Optional[WakeWordDetector] = None

def get_wake_detector() -> WakeWordDetector:
    global _detector
    if _detector is None:
        _detector = WakeWordDetector()
    return _detector
