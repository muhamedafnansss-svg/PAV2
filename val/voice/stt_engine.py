"""
VAL STT Engine v15.0 — Faster-Whisper + VAD
=============================================
High-performance speech-to-text with:
  - Faster-Whisper (CTranslate2) for 4-6x speed over OpenAI Whisper
  - Silero VAD for voice activity detection
  - Energy-based noise gating
  - Hotword detection support

Fallback chain: faster-whisper → openai-whisper → stub
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import threading
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("val.voice.stt")

# ─── Result ───────────────────────────────────────────────────────────────────

@dataclass
class TranscriptionResult:
    text: str
    confidence: float = 0.0
    language: str = "en"
    duration_s: float = 0.0
    is_wake_word: bool = False
    latency_ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "language": self.language,
            "duration_s": round(self.duration_s, 2),
            "is_wake_word": self.is_wake_word,
            "latency_ms": round(self.latency_ms, 1),
        }


# ─── VAD (Voice Activity Detection) ──────────────────────────────────────────

class VADFilter:
    """Silero VAD-based voice activity detector with energy gating."""

    def __init__(self, energy_threshold: float = 0.01):
        self._model = None
        self._available = False
        self._energy_threshold = energy_threshold
        self._init_attempted = False

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True
        try:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True,
            )
            self._model = model
            self._get_speech_timestamps = utils[0]
            self._available = True
            logger.info("[VAD] Silero VAD loaded")
        except Exception as e:
            logger.info("[VAD] Silero VAD not available: %s", e)
            self._available = False
        return self._available

    @property
    def available(self) -> bool:
        return self._try_init()

    def has_speech(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """Check if audio contains speech using energy + VAD."""
        # Energy gate first (fast, no model needed)
        energy = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
        if energy < self._energy_threshold:
            return False

        if not self.available:
            # Fallback: just use energy threshold
            return energy > self._energy_threshold * 2

        try:
            import torch
            audio_tensor = torch.from_numpy(audio).float()
            if audio_tensor.dim() > 1:
                audio_tensor = audio_tensor.mean(dim=0)
            # Normalize
            if audio_tensor.abs().max() > 1.0:
                audio_tensor = audio_tensor / audio_tensor.abs().max()
            speech_timestamps = self._get_speech_timestamps(
                audio_tensor, self._model, sampling_rate=sample_rate
            )
            return len(speech_timestamps) > 0
        except Exception as e:
            logger.debug("[VAD] Detection error: %s", e)
            return energy > self._energy_threshold * 2

    def energy_variance(self, audio: np.ndarray, window_ms: int = 50, sample_rate: int = 16000) -> float:
        """
        Compute energy variance across windows.
        Low variance = likely a recording/replay attack.
        Real speech has high energy variance.
        """
        window_size = int(sample_rate * window_ms / 1000)
        if len(audio) < window_size * 2:
            return 0.0
        energies = []
        for i in range(0, len(audio) - window_size, window_size):
            chunk = audio[i:i + window_size].astype(np.float32)
            energies.append(np.sqrt(np.mean(chunk ** 2)))
        if not energies:
            return 0.0
        return float(np.var(energies))


# ─── STT Engine ───────────────────────────────────────────────────────────────

class STTEngine:
    """
    Speech-to-Text engine with fallback chain:
      1. faster-whisper (CTranslate2, 4-6x faster)
      2. openai-whisper (original, slower)
      3. stub (returns None)
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
    ):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._backend = "none"
        self._available = False
        self._init_attempted = False
        self._lock = threading.Lock()
        self._vad = VADFilter()

        # Stats
        self._transcriptions = 0
        self._total_latency_ms = 0.0

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True

        # Try faster-whisper first
        try:
            from faster_whisper import WhisperModel

            device = self._device
            compute_type = self._compute_type

            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            if compute_type == "auto":
                compute_type = "float16" if device == "cuda" else "int8"

            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute_type,
            )
            self._backend = "faster-whisper"
            self._available = True
            logger.info(
                "[STT] Faster-Whisper loaded: model=%s device=%s compute=%s",
                self._model_size, device, compute_type,
            )
            return True
        except ImportError:
            logger.info("[STT] faster-whisper not installed, trying openai-whisper")
        except Exception as e:
            logger.warning("[STT] faster-whisper init error: %s", e)

        # Fallback: openai-whisper
        try:
            import whisper
            self._model = whisper.load_model(self._model_size)
            self._backend = "openai-whisper"
            self._available = True
            logger.info("[STT] OpenAI Whisper loaded: %s", self._model_size)
            return True
        except ImportError:
            logger.info("[STT] openai-whisper not installed")
        except Exception as e:
            logger.warning("[STT] whisper init error: %s", e)

        logger.warning("[STT] No STT backend available. Install: pip install faster-whisper")
        return False

    @property
    def available(self) -> bool:
        return self._try_init()

    @property
    def backend(self) -> str:
        self._try_init()
        return self._backend

    def transcribe(
        self,
        audio_file: str,
        language: str = "en",
        check_vad: bool = True,
    ) -> Optional[TranscriptionResult]:
        """
        Transcribe audio file to text.

        Args:
            audio_file: Path to audio file (wav, webm, mp3, etc.)
            language: Language code
            check_vad: If True, skip transcription if no speech detected

        Returns:
            TranscriptionResult or None if no speech / error
        """
        if not self._try_init():
            return None

        t0 = time.monotonic()

        # Optional VAD check
        if check_vad:
            try:
                import soundfile as sf
                audio_data, sr = sf.read(audio_file)
                if isinstance(audio_data, np.ndarray) and not self._vad.has_speech(audio_data, sr):
                    logger.debug("[STT] No speech detected (VAD)")
                    return TranscriptionResult(
                        text="", confidence=0.0,
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )
            except Exception:
                pass  # Skip VAD if audio loading fails

        try:
            with self._lock:
                if self._backend == "faster-whisper":
                    return self._transcribe_faster(audio_file, language, t0)
                elif self._backend == "openai-whisper":
                    return self._transcribe_openai(audio_file, language, t0)
                else:
                    return None
        except Exception as e:
            logger.error("[STT] Transcription error: %s", e)
            return None

    def _transcribe_faster(self, audio_file: str, language: str, t0: float) -> TranscriptionResult:
        """Transcribe using faster-whisper."""
        segments, info = self._model.transcribe(
            audio_file,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        text_parts = []
        total_confidence = 0.0
        segment_count = 0

        for segment in segments:
            text_parts.append(segment.text.strip())
            total_confidence += (1.0 - segment.no_speech_prob)
            segment_count += 1

        text = " ".join(text_parts).strip()
        avg_confidence = total_confidence / max(segment_count, 1)
        latency_ms = (time.monotonic() - t0) * 1000

        self._transcriptions += 1
        self._total_latency_ms += latency_ms

        return TranscriptionResult(
            text=text,
            confidence=avg_confidence,
            language=info.language if hasattr(info, 'language') else language,
            duration_s=info.duration if hasattr(info, 'duration') else 0.0,
            latency_ms=latency_ms,
        )

    def _transcribe_openai(self, audio_file: str, language: str, t0: float) -> TranscriptionResult:
        """Transcribe using openai-whisper."""
        result = self._model.transcribe(audio_file, language=language)
        text = result.get("text", "").strip()
        latency_ms = (time.monotonic() - t0) * 1000

        self._transcriptions += 1
        self._total_latency_ms += latency_ms

        # Extract confidence from segments
        segments = result.get("segments", [])
        avg_conf = 0.0
        if segments:
            avg_conf = sum(1.0 - s.get("no_speech_prob", 0.5) for s in segments) / len(segments)

        return TranscriptionResult(
            text=text,
            confidence=avg_conf,
            language=result.get("language", language),
            duration_s=segments[-1]["end"] if segments else 0.0,
            latency_ms=latency_ms,
        )

    def transcribe_bytes(
        self,
        audio_data: bytes,
        filename: str = "recording.webm",
        language: str = "en",
    ) -> Optional[TranscriptionResult]:
        """Transcribe raw audio bytes. Saves to temp file, transcribes, cleans up."""
        tmp_path = None
        try:
            suffix = Path(filename).suffix or ".webm"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="val_stt_")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_data)
            return self.transcribe(tmp_path, language=language)
        except Exception as e:
            logger.error("[STT] Transcribe bytes error: %s", e)
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    @property
    def vad(self) -> VADFilter:
        return self._vad

    def status(self) -> dict:
        avg_latency = (
            self._total_latency_ms / self._transcriptions
            if self._transcriptions > 0 else 0.0
        )
        return {
            "engine": "stt",
            "backend": self._backend,
            "model_size": self._model_size,
            "available": self.available,
            "vad_available": self._vad.available,
            "transcriptions": self._transcriptions,
            "avg_latency_ms": round(avg_latency, 1),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_stt: Optional[STTEngine] = None
_stt_lock = threading.Lock()


def get_stt_engine(model_size: str = "base") -> STTEngine:
    global _stt
    if _stt is None:
        with _stt_lock:
            if _stt is None:
                _stt = STTEngine(model_size=model_size)
    return _stt
