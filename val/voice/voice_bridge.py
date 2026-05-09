"""
VAL Voice Bridge -- Foundation Architecture
=============================================
Provides STT (Speech-to-Text) and TTS (Text-to-Speech) scaffolding.

Current state:
  - STT: Uses Whisper if installed, otherwise stub
  - TTS: Uses pyttsx3 (system TTS) if available, otherwise stub
  
To fully activate:
  pip install openai-whisper pyttsx3
  # Or for better TTS: pip install TTS (Coqui)
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import queue
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("val.voice")


class STTEngine:
    """Speech-to-Text engine using Whisper."""

    def __init__(self, model_size: str = "base"):
        self._model_size = model_size
        self._model = None
        self._available = False
        self._init_attempted = False

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True
        try:
            import whisper
            self._model = whisper.load_model(self._model_size)
            self._available = True
            logger.info("[STT] Whisper loaded: %s", self._model_size)
        except ImportError:
            logger.info("[STT] Whisper not installed (pip install openai-whisper)")
            self._available = False
        except Exception as e:
            logger.warning("[STT] Whisper init error: %s", e)
            self._available = False
        return self._available

    def transcribe(self, audio_file: str) -> Optional[str]:
        if not self._try_init():
            return None
        try:
            result = self._model.transcribe(audio_file, language="en")
            return result.get("text", "").strip()
        except Exception as e:
            logger.error("[STT] Transcription error: %s", e)
            return None

    @property
    def available(self) -> bool:
        return self._try_init()

    def status(self) -> dict:
        return {
            "engine": "whisper",
            "model_size": self._model_size,
            "available": self.available,
        }


class TTSEngine:
    """Text-to-Speech engine using pyttsx3 or system fallback."""

    def __init__(self):
        self._engine = None
        self._available = False
        self._lock = threading.Lock()
        self._init_attempted = False

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 180)  # words per minute
            self._engine.setProperty("volume", 0.85)
            self._available = True
            logger.info("[TTS] pyttsx3 initialized")
        except ImportError:
            logger.info("[TTS] pyttsx3 not installed (pip install pyttsx3)")
            self._available = False
        except Exception as e:
            logger.warning("[TTS] TTS init error: %s", e)
            self._available = False
        return self._available

    def speak(self, text: str) -> bool:
        if not self._try_init():
            return False
        if not text or not text.strip():
            return False
        with self._lock:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
                return True
            except Exception as e:
                logger.error("[TTS] Speech error: %s", e)
                return False

    def speak_async(self, text: str) -> None:
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()

    @property
    def available(self) -> bool:
        return self._try_init()

    def status(self) -> dict:
        return {
            "engine": "pyttsx3",
            "available": self.available,
        }


class VoiceBridge:
    """Orchestrates STT + TTS for the VAL voice interface."""

    def __init__(self):
        self._stt = STTEngine()
        self._tts = TTSEngine()
        self._active = False
        self._on_transcript: Optional[Callable[[str], None]] = None

    @property
    def stt(self) -> STTEngine:
        return self._stt

    @property
    def tts(self) -> TTSEngine:
        return self._tts

    @property
    def is_active(self) -> bool:
        return self._active

    def set_transcript_handler(self, handler: Callable[[str], None]) -> None:
        self._on_transcript = handler

    def speak(self, text: str, async_mode: bool = True) -> None:
        if async_mode:
            self._tts.speak_async(text)
        else:
            self._tts.speak(text)

    def detect_wake_word(self, transcript: str) -> bool:
        """Checks if the wake word is present in the transcript."""
        wake_words = ["hey jarvis", "jarvis", "commander"]
        text_lower = transcript.lower()
        return any(ww in text_lower for ww in wake_words)

    def transcribe_bytes(self, audio_data: bytes, filename: str = "recording.webm", require_wake_word: bool = False) -> Optional[str]:
        """Transcribe audio bytes via Whisper. Saves to temp file, transcribes, cleans up."""
        if not self._stt.available:
            logger.warning("[Voice] STT not available for transcription")
            return None
        tmp_path = None
        try:
            suffix = Path(filename).suffix or ".webm"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="val_voice_")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_data)
            result = self._stt.transcribe(tmp_path)
            
            if not result:
                return None
                
            if require_wake_word and not self.detect_wake_word(result):
                logger.debug("[Voice] Wake word not detected. Ignoring audio.")
                return None
                
            from val.security.voice_auth import voice_auth
            if not voice_auth.verify_speaker(audio_data):
                logger.warning("[Voice] Speaker verification failed. Audio rejected.")
                return None
                
            return result
        except Exception as e:
            logger.error("[Voice] Transcription error: %s", e)
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def status(self) -> dict:
        return {
            "active": self._active,
            "stt": self._stt.status(),
            "tts": self._tts.status(),
            "whisper_available": self._stt.available,
            "tts_available":     self._tts.available,
        }


# ─── Process-wide singleton ───────────────────────────────────────────────────

_bridge: Optional[VoiceBridge] = None
_bridge_lock = threading.Lock()

def get_voice_bridge() -> VoiceBridge:
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = VoiceBridge()
    return _bridge