"""
Voice Activity Detection (VAD)
Detects when the user is speaking vs. silence
Critical for session timeout and interruption detection
"""

import numpy as np
import logging
from typing import Tuple, Optional
from collections import deque
import time

logger = logging.getLogger(__name__)


class SileroVAD:
    """
    Silero Voice Activity Detection
    Fast, accurate speech detection on GPU
    """
    
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.model = None
        self.is_loaded = False
        
        self._load_model()
    
    def _load_model(self) -> None:
        """Load Silero VAD model"""
        try:
            import torch
            
            self.model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
            )
            
            if torch.cuda.is_available():
                self.model = self.model.cuda()
            
            self.is_loaded = True
            logger.info("Silero VAD model loaded")
        except Exception as e:
            logger.error(f"Failed to load Silero VAD: {e}")
    
    def detect(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """
        Detect voice activity
        
        Args:
            audio_chunk: Audio data (PCM 16-bit)
            
        Returns:
            Tuple of (has_speech: bool, confidence: float)
        """
        if not self.is_loaded:
            return False, 0.0
        
        try:
            import torch
            
            # Convert to tensor
            if audio_chunk.dtype != np.float32:
                audio_chunk = audio_chunk.astype(np.float32) / 32768.0
            
            if self.sample_rate == 16000:
                audio_tensor = torch.from_numpy(audio_chunk)
            else:
                # Resample if needed
                import torchaudio
                audio_tensor = torch.from_numpy(audio_chunk)
                resampler = torchaudio.transforms.Resample(self.sample_rate, 16000)
                audio_tensor = resampler(audio_tensor)
            
            if torch.cuda.is_available():
                audio_tensor = audio_tensor.cuda()
            
            # Get speech probability
            speech_prob = self.model(audio_tensor, 16000).item()
            has_speech = speech_prob >= self.threshold
            
            return has_speech, speech_prob
        except Exception as e:
            logger.error(f"VAD detection error: {e}")
            return False, 0.0


class WebRTCVAD:
    """
    WebRTC Voice Activity Detection
    Lightweight alternative to Silero VAD
    """
    
    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 3):
        """
        Args:
            sample_rate: 8000, 16000, 32000, or 48000
            aggressiveness: 0-3 (higher = more aggressive)
        """
        self.sample_rate = sample_rate
        self.aggressiveness = aggressiveness
        self.vad = None
        
        self._load_model()
    
    def _load_model(self) -> None:
        """Load WebRTC VAD"""
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(self.aggressiveness)
            logger.info("WebRTC VAD loaded")
        except ImportError:
            logger.error("webrtcvad not installed")
    
    def detect(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """
        Detect voice activity
        
        Returns:
            Tuple of (has_speech: bool, confidence: float)
            Note: WebRTC doesn't return confidence, only 0.0 or 1.0
        """
        if self.vad is None:
            return False, 0.0
        
        try:
            # Convert to required format
            if audio_chunk.dtype != np.int16:
                audio_chunk = (audio_chunk * 32767).astype(np.int16)
            
            # Ensure correct frame size
            frame_length = (self.sample_rate * 10) // 1000  # 10ms frames
            
            has_speech = self.vad.is_speech(
                audio_chunk[:frame_length].tobytes(),
                self.sample_rate
            )
            
            confidence = 1.0 if has_speech else 0.0
            return has_speech, confidence
        except Exception as e:
            logger.error(f"WebRTC VAD error: {e}")
            return False, 0.0


class VADHandler:
    """
    Handles voice activity detection state machine
    
    States:
    - IDLE: No speech detected, waiting
    - SPEECH_DETECTED: User started speaking
    - SPEAKING: User is actively speaking
    - SILENCE: User stopped speaking, counting down
    - SESSION_TIMEOUT: Silence exceeded timeout
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        silence_start_duration: float = 0.5,
        silence_end_duration: float = 2.0,
        session_timeout: float = 15.0,
        vad_type: str = "silero",
    ):
        self.sample_rate = sample_rate
        self.silence_start_duration = silence_start_duration
        self.silence_end_duration = silence_end_duration
        self.session_timeout = session_timeout
        
        # Initialize VAD
        if vad_type == "silero":
            self.vad = SileroVAD(sample_rate)
        else:
            self.vad = WebRTCVAD(sample_rate)
        
        # State tracking
        self.state = "IDLE"
        self.last_speech_time = time.time()
        self.speech_start_time = None
        self.silence_counter = 0
        self.frame_duration = 1024 / sample_rate  # seconds
        
        # History for smoothing
        self.speech_history = deque(maxlen=5)
        
        logger.info(f"VADHandler initialized with {vad_type} VAD")
    
    def process(self, audio_chunk: np.ndarray) -> dict:
        """
        Process audio chunk and update state
        
        Returns:
            State update dictionary
        """
        has_speech, confidence = self.vad.detect(audio_chunk)
        
        # Smooth detection with history
        self.speech_history.append(has_speech)
        smoothed_speech = sum(self.speech_history) > len(self.speech_history) / 2
        
        # State machine
        old_state = self.state
        
        if smoothed_speech:
            if self.state == "IDLE":
                self.state = "SPEECH_DETECTED"
                self.speech_start_time = time.time()
            elif self.state == "SILENCE":
                self.state = "SPEECH_DETECTED"  # User spoke again
            else:
                self.state = "SPEAKING"
            
            self.last_speech_time = time.time()
            self.silence_counter = 0
        
        else:  # No speech detected
            if self.state in ["SPEECH_DETECTED", "SPEAKING"]:
                self.state = "SILENCE"
                self.silence_counter = 0
            elif self.state == "SILENCE":
                self.silence_counter += 1
                
                # Check timeouts
                silence_duration = self.silence_counter * self.frame_duration
                if silence_duration > self.session_timeout:
                    self.state = "SESSION_TIMEOUT"
            elif self.state == "IDLE":
                pass  # Stay idle
        
        update = {
            "state": self.state,
            "state_changed": old_state != self.state,
            "has_speech": smoothed_speech,
            "confidence": confidence,
            "silence_duration": self.silence_counter * self.frame_duration,
            "session_duration": (time.time() - self.speech_start_time) if self.speech_start_time else 0,
        }
        
        logger.debug(f"VAD state: {self.state}, confidence: {confidence:.2f}")
        return update
    
    def reset(self) -> None:
        """Reset state"""
        self.state = "IDLE"
        self.silence_counter = 0
        self.speech_start_time = None
        logger.info("VAD handler reset")
    
    def get_session_stats(self) -> dict:
        """Get current session statistics"""
        return {
            "state": self.state,
            "speech_start_time": self.speech_start_time,
            "last_speech_time": self.last_speech_time,
            "silence_duration": self.silence_counter * self.frame_duration,
        }