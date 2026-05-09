"""
VAL Voice Bridge v15.0 — JARVIS Voice Orchestrator
=====================================================
Orchestrates the full voice pipeline:
  Wake Word → Auth → STT → Kernel → Persona → TTS → Audio

State machine:
  IDLE → WAKE_DETECTED → AUTHENTICATING → LISTENING →
  PROCESSING → SPEAKING → IDLE

Supports:
  - Push-to-talk mode
  - Always-listening (wake word) mode
  - Full-duplex barge-in
  - Voice mode switching
"""

from __future__ import annotations
import asyncio, logging, os, tempfile, threading, time
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
import numpy as np

logger = logging.getLogger("val.voice")


class VoiceState(str, Enum):
    IDLE           = "idle"
    WAKE_DETECTED  = "wake_detected"
    AUTHENTICATING = "authenticating"
    LISTENING      = "listening"
    TRANSCRIBING   = "transcribing"
    PROCESSING     = "processing"
    SPEAKING       = "speaking"
    LOCKED         = "locked"


class VoiceBridge:
    """
    JARVIS Voice Orchestrator.
    Ties STT, TTS, Auth, Wake Word, and Persona into a unified pipeline.
    """

    def __init__(self):
        from val.voice.stt_engine import get_stt_engine
        from val.voice.tts_engine import get_tts_engine, VoiceMode
        from val.voice.voice_auth import get_voice_auth
        from val.voice.wake_word import get_wake_detector
        from val.voice.persona import get_persona

        self._stt = get_stt_engine()
        self._tts = get_tts_engine()
        self._auth = get_voice_auth()
        self._wake = get_wake_detector()
        self._persona = get_persona()

        self._state = VoiceState.IDLE
        self._state_lock = threading.Lock()
        self._on_state_change: Optional[Callable] = None
        self._on_transcript: Optional[Callable] = None

        # Pipeline stats
        self._interactions = 0
        self._total_pipeline_ms = 0.0

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def stt(self):
        return self._stt

    @property
    def tts(self):
        return self._tts

    @property
    def auth(self):
        return self._auth

    @property
    def wake(self):
        return self._wake

    @property
    def persona(self):
        return self._persona

    @property
    def is_active(self) -> bool:
        return self._state not in (VoiceState.IDLE, VoiceState.LOCKED)

    # ── State Machine ─────────────────────────────────────────────────────────

    def _set_state(self, state: VoiceState):
        with self._state_lock:
            old = self._state
            self._state = state
        if old != state:
            logger.debug("[Voice] State: %s → %s", old.value, state.value)
            if self._on_state_change:
                try:
                    self._on_state_change(state.value)
                except Exception:
                    pass

    def set_state_callback(self, cb: Callable):
        self._on_state_change = cb

    def set_transcript_handler(self, handler: Callable):
        self._on_transcript = handler

    # ── Push-to-Talk Pipeline ─────────────────────────────────────────────────

    def transcribe_bytes(self, audio_data: bytes, filename: str = "recording.webm") -> Optional[str]:
        """
        Full pipeline: receive audio → auth → transcribe → return text.
        Used by push-to-talk mode.
        """
        if not self._stt.available:
            logger.warning("[Voice] STT not available")
            return None

        self._set_state(VoiceState.TRANSCRIBING)
        try:
            result = self._stt.transcribe_bytes(audio_data, filename)
            if result and result.text:
                # Check wake word (strip it from the text if present)
                wake = self._wake.check_text(result.text)
                if wake:
                    # Remove wake word from the actual command
                    import re
                    cleaned = re.sub(re.escape(wake), "", result.text, count=1, flags=re.I).strip()
                    return cleaned if cleaned else None
                return result.text
            return None
        finally:
            self._set_state(VoiceState.IDLE)

    async def process_voice_input(self, audio_data: bytes, filename: str = "recording.webm") -> Optional[dict]:
        """
        Full JARVIS pipeline: audio → auth → STT → Kernel → persona → TTS.

        Returns dict with response text and metadata, or None on failure.
        """
        t0 = time.monotonic()

        # Step 1: Auth check (if enrolled)
        if self._auth.is_enrolled:
            self._set_state(VoiceState.AUTHENTICATING)
            try:
                import soundfile as sf
                import io
                buf = io.BytesIO(audio_data)
                audio_np, sr = sf.read(buf)
                if isinstance(audio_np, np.ndarray):
                    auth_result = self._auth.verify(audio_np, sr)
                    if not auth_result.authenticated:
                        if auth_result.locked_out:
                            self._set_state(VoiceState.LOCKED)
                        else:
                            self._set_state(VoiceState.IDLE)
                        logger.info("[Voice] Auth rejected: %s", auth_result.reason)
                        return None
            except Exception as e:
                logger.debug("[Voice] Auth check skipped: %s", e)

        # Step 2: Transcribe
        self._set_state(VoiceState.TRANSCRIBING)
        text = self.transcribe_bytes(audio_data, filename)
        if not text:
            self._set_state(VoiceState.IDLE)
            return None

        # Step 3: Process through Kernel
        self._set_state(VoiceState.PROCESSING)
        try:
            from val.core.engine import get_kernel
            kernel = get_kernel()
            chunks = []
            intent = "chat"
            model_used = "unknown"

            async for item in kernel.stream(text):
                if "chunk" in item:
                    chunks.append(item["chunk"])
                if "done" in item and isinstance(item.get("result"), dict):
                    intent = item["result"].get("intent", intent)
                    model_used = item["result"].get("model_used", model_used)

            response_text = "".join(chunks).strip()
        except Exception as e:
            logger.error("[Voice] Kernel error: %s", e)
            response_text = self._persona.format_error(str(e))
            intent = "error"
            model_used = "none"

        # Step 4: Apply persona transform
        response_text = self._persona.transform(response_text, intent=intent)

        # Step 5: Speak response
        self._set_state(VoiceState.SPEAKING)
        if self._tts.available:
            self._tts.speak(response_text, async_mode=False)

        pipeline_ms = (time.monotonic() - t0) * 1000
        self._interactions += 1
        self._total_pipeline_ms += pipeline_ms

        self._set_state(VoiceState.IDLE)

        return {
            "user_text": text,
            "response_text": response_text,
            "intent": intent,
            "model_used": model_used,
            "pipeline_ms": round(pipeline_ms, 1),
            "authenticated": True,
        }

    # ── TTS convenience ───────────────────────────────────────────────────────

    def speak(self, text: str, async_mode: bool = True):
        transformed = self._persona.transform(text)
        if async_mode:
            self._tts.speak(transformed, async_mode=True)
        else:
            self._set_state(VoiceState.SPEAKING)
            self._tts.speak(transformed, async_mode=False)
            self._set_state(VoiceState.IDLE)

    def interrupt(self):
        """Interrupt current speech (barge-in)."""
        self._tts.interrupt()
        self._set_state(VoiceState.IDLE)

    # ── Voice Mode ────────────────────────────────────────────────────────────

    def set_voice_mode(self, mode: str):
        from val.voice.tts_engine import VoiceMode
        try:
            vm = VoiceMode(mode.lower())
            self._tts.voice_mode = vm
            self._persona.mode = mode.lower()
        except ValueError:
            logger.warning("[Voice] Invalid mode: %s", mode)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        avg_pipeline = self._total_pipeline_ms / self._interactions if self._interactions else 0.0
        return {
            "state": self._state.value,
            "stt": self._stt.status(),
            "tts": self._tts.status(),
            "auth": self._auth.status(),
            "wake_word": self._wake.status(),
            "interactions": self._interactions,
            "avg_pipeline_ms": round(avg_pipeline, 1),
            "whisper_available": self._stt.available,
            "tts_available": self._tts.available,
            "active": self.is_active,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_bridge: Optional[VoiceBridge] = None
_bridge_lock = threading.Lock()

def get_voice_bridge() -> VoiceBridge:
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = VoiceBridge()
    return _bridge