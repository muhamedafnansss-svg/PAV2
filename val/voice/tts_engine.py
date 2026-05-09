"""
VAL TTS Engine v15.0 — Piper + Voice Modes
============================================
Piper TTS (CPU) primary, pyttsx3 fallback.
Voice modes: Formal, Tactical, Friendly, Silent.
Interruption support, async playback.
"""

from __future__ import annotations
import io, logging, os, threading, time, wave
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("val.voice.tts")

class VoiceMode(str, Enum):
    FORMAL   = "formal"
    TACTICAL = "tactical"
    FRIENDLY = "friendly"
    SILENT   = "silent"

@dataclass
class TTSResult:
    audio_data: Optional[bytes] = None
    sample_rate: int = 22050
    duration_s: float = 0.0
    latency_ms: float = 0.0
    backend: str = "none"
    success: bool = False

_MODE_CFG = {
    VoiceMode.FORMAL:   {"rate": 0.9},
    VoiceMode.TACTICAL: {"rate": 1.15},
    VoiceMode.FRIENDLY: {"rate": 1.0},
    VoiceMode.SILENT:   {"rate": 1.0},
}

class TTSEngine:
    def __init__(self, voice_mode: VoiceMode = VoiceMode.FORMAL):
        self._voice_mode = voice_mode
        self._backend = "none"
        self._available = False
        self._init_attempted = False
        self._lock = threading.Lock()
        self._interrupted = threading.Event()
        self._piper_voice = None
        self._piper_model_path = None
        self._pyttsx3_engine = None
        self._playing = False
        self._utterances = 0
        self._total_latency_ms = 0.0

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True
        # Try Piper
        try:
            from piper import PiperVoice
            vp = self._find_piper_voice()
            if vp:
                self._piper_voice = PiperVoice.load(str(vp))
                self._piper_model_path = vp
                self._backend = "piper"
                self._available = True
                logger.info("[TTS] Piper loaded: %s", vp.name)
                return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning("[TTS] Piper init: %s", e)
        # Fallback pyttsx3
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate", 170)
            eng.setProperty("volume", 0.85)
            voices = eng.getProperty("voices")
            for v in voices:
                if any(k in v.name.lower() for k in ("david","mark","male","daniel")):
                    eng.setProperty("voice", v.id)
                    break
            self._pyttsx3_engine = eng
            self._backend = "pyttsx3"
            self._available = True
            logger.info("[TTS] pyttsx3 initialized")
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning("[TTS] pyttsx3 init: %s", e)
        return False

    def _find_piper_voice(self) -> Optional[Path]:
        dirs = [
            Path.home() / ".local" / "share" / "piper-voices",
            Path(__file__).parent / "voices",
            Path("d:/PAV2/models/piper"),
        ]
        for d in dirs:
            if not d.exists(): continue
            for f in d.rglob("*.onnx"):
                if "en" in f.stem.lower(): return f
            for f in d.rglob("*.onnx"): return f
        return None

    @property
    def available(self) -> bool:
        return self._try_init()

    @property
    def voice_mode(self) -> VoiceMode:
        return self._voice_mode

    @voice_mode.setter
    def voice_mode(self, mode: VoiceMode):
        self._voice_mode = mode

    def synthesize(self, text: str) -> TTSResult:
        if self._voice_mode == VoiceMode.SILENT:
            return TTSResult(success=True, backend="silent")
        if not self._try_init():
            return TTSResult(success=False)
        t0 = time.monotonic()
        try:
            with self._lock:
                if self._backend == "piper":
                    return self._synth_piper(text, t0)
                elif self._backend == "pyttsx3":
                    return self._synth_pyttsx3(text, t0)
        except Exception as e:
            logger.error("[TTS] Synthesis error: %s", e)
        return TTSResult(success=False)

    def _synth_piper(self, text: str, t0: float) -> TTSResult:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            self._piper_voice.synthesize(text, wav)
        audio = buf.getvalue()
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            dur = frames / rate if rate else 0.0
        lat = (time.monotonic() - t0) * 1000
        self._utterances += 1; self._total_latency_ms += lat
        return TTSResult(audio_data=audio, sample_rate=rate, duration_s=dur,
                         latency_ms=lat, backend="piper", success=True)

    def _synth_pyttsx3(self, text: str, t0: float) -> TTSResult:
        cfg = _MODE_CFG[self._voice_mode]
        self._pyttsx3_engine.setProperty("rate", int(170 * cfg["rate"]))
        self._pyttsx3_engine.say(text)
        self._pyttsx3_engine.runAndWait()
        lat = (time.monotonic() - t0) * 1000
        self._utterances += 1; self._total_latency_ms += lat
        return TTSResult(latency_ms=lat, backend="pyttsx3", success=True)

    def speak(self, text: str, async_mode: bool = True):
        if self._voice_mode == VoiceMode.SILENT or not self._try_init():
            return
        self._interrupted.clear()
        if async_mode:
            threading.Thread(target=self._speak_sync, args=(text,), daemon=True).start()
        else:
            self._speak_sync(text)

    def _speak_sync(self, text: str):
        self._playing = True
        try:
            if self._backend == "pyttsx3":
                self._synth_pyttsx3(text, time.monotonic()); return
            result = self.synthesize(text)
            if not result.success or not result.audio_data: return
            try:
                import sounddevice as sd, soundfile as sf
                data, sr = sf.read(io.BytesIO(result.audio_data))
                sd.play(data, sr)
                while sd.get_stream().active:
                    if self._interrupted.is_set(): sd.stop(); break
                    time.sleep(0.05)
            except ImportError:
                pass
        finally:
            self._playing = False

    def interrupt(self):
        self._interrupted.set()
        if self._pyttsx3_engine:
            try: self._pyttsx3_engine.stop()
            except: pass

    @property
    def is_speaking(self) -> bool:
        return self._playing

    def status(self) -> dict:
        avg = self._total_latency_ms / self._utterances if self._utterances else 0.0
        return {"engine": "tts", "backend": self._backend, "available": self.available,
                "voice_mode": self._voice_mode.value, "is_speaking": self._playing,
                "utterances": self._utterances, "avg_latency_ms": round(avg, 1)}

_tts: Optional[TTSEngine] = None
_tts_lock = threading.Lock()

def get_tts_engine() -> TTSEngine:
    global _tts
    if _tts is None:
        with _tts_lock:
            if _tts is None:
                _tts = TTSEngine()
    return _tts
