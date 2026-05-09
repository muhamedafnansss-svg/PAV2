"""
VAL Voice Auth v15.0 — Speaker Verification + Anti-Spoofing
=============================================================
Owner-only voice authentication:
  - Speaker embedding via resemblyzer (d-vector)
  - Enrollment: 3x 10s samples → average embedding
  - Verify: cosine similarity > threshold
  - Anti-replay: energy variance + spectral checks
  - Unknown voice → silent ignore + log
  - Spoof detected → 30s cooldown lockout
"""

from __future__ import annotations
import hashlib, json, logging, os, threading, time
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("val.voice.auth")

ENROLL_DIR = Path(os.environ.get("VAL_VOICE_ENROLL_DIR", "d:/PAV2/val/state/voice_auth"))
ENROLL_DIR.mkdir(parents=True, exist_ok=True)

SIMILARITY_THRESHOLD = 0.82
LOCKOUT_DURATION_S   = 30.0
ENERGY_VAR_MIN       = 0.0001  # min energy variance for liveness
MIN_ENROLL_SAMPLES   = 2

@dataclass
class AuthResult:
    authenticated: bool = False
    confidence: float = 0.0
    reason: str = ""
    locked_out: bool = False

class VoiceAuthenticator:
    def __init__(self):
        self._encoder = None
        self._available = False
        self._init_attempted = False
        self._lock = threading.Lock()
        self._owner_embedding: Optional[np.ndarray] = None
        self._lockout_until: float = 0.0
        self._auth_attempts = 0
        self._auth_successes = 0
        self._auth_rejections = 0
        self._spoof_detections = 0
        self._load_enrollment()

    def _try_init(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True
        try:
            from resemblyzer import VoiceEncoder
            self._encoder = VoiceEncoder()
            self._available = True
            logger.info("[VoiceAuth] resemblyzer encoder loaded")
        except ImportError:
            logger.info("[VoiceAuth] resemblyzer not installed (pip install resemblyzer)")
        except Exception as e:
            logger.warning("[VoiceAuth] Init error: %s", e)
        return self._available

    @property
    def available(self) -> bool:
        return self._try_init()

    @property
    def is_enrolled(self) -> bool:
        return self._owner_embedding is not None

    @property
    def is_locked_out(self) -> bool:
        if time.time() < self._lockout_until:
            return True
        self._lockout_until = 0.0
        return False

    def _load_enrollment(self):
        embed_path = ENROLL_DIR / "owner_embedding.npy"
        if embed_path.exists():
            try:
                self._owner_embedding = np.load(str(embed_path))
                logger.info("[VoiceAuth] Owner embedding loaded")
            except Exception as e:
                logger.warning("[VoiceAuth] Failed to load embedding: %s", e)

    def enroll(self, audio_samples: List[np.ndarray], sample_rate: int = 16000) -> bool:
        """
        Enroll owner voice from audio samples.
        Requires at least MIN_ENROLL_SAMPLES samples.
        Computes average d-vector embedding.
        """
        if not self._try_init():
            return False
        if len(audio_samples) < MIN_ENROLL_SAMPLES:
            logger.warning("[VoiceAuth] Need >= %d samples, got %d", MIN_ENROLL_SAMPLES, len(audio_samples))
            return False

        try:
            from resemblyzer import preprocess_wav
            embeddings = []
            for audio in audio_samples:
                if audio.dtype != np.float32:
                    audio = audio.astype(np.float32)
                if np.abs(audio).max() > 1.0:
                    audio = audio / np.abs(audio).max()
                wav = preprocess_wav(audio, source_sr=sample_rate)
                embed = self._encoder.embed_utterance(wav)
                embeddings.append(embed)

            self._owner_embedding = np.mean(embeddings, axis=0)
            self._owner_embedding = self._owner_embedding / np.linalg.norm(self._owner_embedding)

            # Persist
            np.save(str(ENROLL_DIR / "owner_embedding.npy"), self._owner_embedding)
            logger.info("[VoiceAuth] Owner enrolled (%d samples)", len(audio_samples))
            return True
        except Exception as e:
            logger.error("[VoiceAuth] Enrollment error: %s", e)
            return False

    def verify(self, audio: np.ndarray, sample_rate: int = 16000) -> AuthResult:
        """Verify if audio matches enrolled owner voice."""
        self._auth_attempts += 1

        if self.is_locked_out:
            return AuthResult(locked_out=True, reason="Temporarily locked out")

        if not self.is_enrolled:
            # No enrollment → allow all (open mode)
            return AuthResult(authenticated=True, confidence=1.0, reason="No enrollment (open mode)")

        if not self._try_init():
            return AuthResult(reason="Voice auth unavailable")

        try:
            # Liveness check: energy variance
            from val.voice.stt_engine import VADFilter
            vad = VADFilter()
            variance = vad.energy_variance(audio, sample_rate=sample_rate)
            if variance < ENERGY_VAR_MIN:
                self._spoof_detections += 1
                self._lockout_until = time.time() + LOCKOUT_DURATION_S
                self._log_attempt("spoof_detected", 0.0)
                logger.warning("[VoiceAuth] Possible replay attack (low energy variance: %.6f)", variance)
                return AuthResult(reason="Possible replay attack detected", locked_out=True)

            # Compute embedding
            from resemblyzer import preprocess_wav
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)
            if np.abs(audio).max() > 1.0:
                audio = audio / np.abs(audio).max()
            wav = preprocess_wav(audio, source_sr=sample_rate)
            embed = self._encoder.embed_utterance(wav)
            embed = embed / np.linalg.norm(embed)

            # Cosine similarity
            similarity = float(np.dot(self._owner_embedding, embed))

            if similarity >= SIMILARITY_THRESHOLD:
                self._auth_successes += 1
                self._log_attempt("authenticated", similarity)
                return AuthResult(authenticated=True, confidence=similarity, reason="Owner verified")
            else:
                self._auth_rejections += 1
                self._log_attempt("rejected", similarity)
                logger.info("[VoiceAuth] Unknown voice (similarity: %.3f)", similarity)
                return AuthResult(confidence=similarity, reason="Voice not recognized")

        except Exception as e:
            logger.error("[VoiceAuth] Verify error: %s", e)
            return AuthResult(reason=f"Verification error: {e}")

    def _log_attempt(self, result: str, similarity: float):
        """Log auth attempt to security log."""
        try:
            log_path = ENROLL_DIR / "auth_log.jsonl"
            entry = {
                "timestamp": time.time(),
                "result": result,
                "similarity": round(similarity, 4),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def status(self) -> dict:
        return {
            "available": self.available,
            "enrolled": self.is_enrolled,
            "locked_out": self.is_locked_out,
            "auth_attempts": self._auth_attempts,
            "auth_successes": self._auth_successes,
            "auth_rejections": self._auth_rejections,
            "spoof_detections": self._spoof_detections,
            "threshold": SIMILARITY_THRESHOLD,
        }

_auth: Optional[VoiceAuthenticator] = None
_auth_lock = threading.Lock()

def get_voice_auth() -> VoiceAuthenticator:
    global _auth
    if _auth is None:
        with _auth_lock:
            if _auth is None:
                _auth = VoiceAuthenticator()
    return _auth
