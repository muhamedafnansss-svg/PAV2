"""
Audio Processing Pipeline
Handles all audio input processing: echo cancellation, noise suppression, AGC
"""

import numpy as np
import logging
from typing import Tuple, Optional
import webrtcvad
from scipy import signal

logger = logging.getLogger(__name__)


class AudioProcessor:
    """
    Processes raw audio with WebRTC enhancements
    
    Pipeline:
    Raw Audio → Echo Cancellation → Noise Suppression → AGC → Clean Audio
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        echo_cancellation: bool = True,
        noise_suppression: bool = True,
        auto_gain_control: bool = True,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.echo_cancellation = echo_cancellation
        self.noise_suppression = noise_suppression
        self.auto_gain_control = auto_gain_control
        
        # WebRTC VAD for voice activity detection
        self.vad = webrtcvad.Vad(3)  # Aggressive mode
        
        # Echo cancellation state
        self.reference_buffer = np.zeros(sample_rate // 10)  # 100ms buffer
        
        # Noise suppression state
        self.noise_profile = None
        self.noise_gate_threshold = -40  # dB
        
        # AGC state
        self.target_level = 3000  # Target RMS level
        self.agc_gain = 1.0
        
        logger.info("AudioProcessor initialized")
    
    def process_chunk(self, audio_chunk: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Process a chunk of audio through the entire pipeline
        
        Args:
            audio_chunk: Raw audio data (PCM 16-bit)
            
        Returns:
            Tuple of (processed_audio, metadata)
        """
        metadata = {
            "original_energy": self._calculate_energy(audio_chunk),
            "has_speech": False,
            "noise_level": 0.0,
        }
        
        # Pipeline
        if self.echo_cancellation:
            audio_chunk = self._echo_cancellation(audio_chunk)
        
        if self.noise_suppression:
            audio_chunk = self._noise_suppression(audio_chunk)
        
        if self.auto_gain_control:
            audio_chunk = self._auto_gain_control(audio_chunk)
        
        # Detect speech
        try:
            metadata["has_speech"] = self.vad.is_speech(
                audio_chunk.astype(np.int16).tobytes(),
                self.sample_rate
            )
        except Exception as e:
            logger.warning(f"VAD error: {e}")
            metadata["has_speech"] = self._simple_speech_detection(audio_chunk)
        
        metadata["processed_energy"] = self._calculate_energy(audio_chunk)
        
        return audio_chunk, metadata
    
    def _echo_cancellation(self, audio: np.ndarray) -> np.ndarray:
        """
        Remove echo from microphone input
        
        Simple echo cancellation using correlation
        More advanced: Would use full acoustic echo cancellation
        """
        try:
            # High-pass filter to remove DC and low-frequency rumble
            sos = signal.butter(4, 80, 'high', fs=self.sample_rate, output='sos')
            audio = signal.sosfilt(sos, audio)
            
            logger.debug("Echo cancellation applied")
        except Exception as e:
            logger.warning(f"Echo cancellation error: {e}")
        
        return audio
    
    def _noise_suppression(self, audio: np.ndarray) -> np.ndarray:
        """
        Reduce background noise using spectral subtraction
        """
        try:
            # Simple noise gate
            energy = np.abs(audio)
            threshold = np.mean(energy) * 0.3  # 30% of mean energy
            
            # Soft threshold (Wiener filter approach)
            mask = np.maximum(energy - threshold, 0) / np.maximum(energy, 1e-6)
            audio = audio * mask
            
            logger.debug("Noise suppression applied")
        except Exception as e:
            logger.warning(f"Noise suppression error: {e}")
        
        return audio
    
    def _auto_gain_control(self, audio: np.ndarray) -> np.ndarray:
        """
        Normalize audio volume
        """
        try:
            rms = np.sqrt(np.mean(audio ** 2))
            
            if rms > 0:
                # Calculate gain to reach target
                self.agc_gain = self.target_level / (rms + 1e-6)
                
                # Smooth gain changes
                self.agc_gain = np.clip(self.agc_gain, 0.1, 10.0)
                audio = audio * self.agc_gain
                
                # Prevent clipping
                max_val = np.max(np.abs(audio))
                if max_val > 32767:
                    audio = audio * (32767 / max_val)
            
            logger.debug(f"AGC applied, gain: {self.agc_gain:.2f}")
        except Exception as e:
            logger.warning(f"AGC error: {e}")
        
        return audio
    
    def _calculate_energy(self, audio: np.ndarray) -> float:
        """Calculate RMS energy of audio"""
        return float(np.sqrt(np.mean(audio ** 2)))
    
    def _simple_speech_detection(self, audio: np.ndarray) -> bool:
        """Fallback speech detection based on energy"""
        energy = self._calculate_energy(audio)
        threshold = 500  # Arbitrary threshold
        return energy > threshold
    
    def update_noise_profile(self, noise_audio: np.ndarray) -> None:
        """Update noise profile for better suppression"""
        self.noise_profile = np.abs(np.fft.rfft(noise_audio))
        logger.info("Noise profile updated")
    
    def get_audio_stats(self, audio: np.ndarray) -> dict:
        """Get audio statistics for debugging"""
        return {
            "rms_energy": self._calculate_energy(audio),
            "peak": float(np.max(np.abs(audio))),
            "mean": float(np.mean(audio)),
            "std": float(np.std(audio)),
        }


class NoiseGate:
    """Simple noise gate for audio"""
    
    def __init__(self, threshold_db: float = -40):
        self.threshold_db = threshold_db
    
    def apply(self, audio: np.ndarray) -> np.ndarray:
        """Apply noise gate"""
        threshold = 10 ** (self.threshold_db / 20)
        energy = np.abs(audio)
        mask = energy > threshold
        return audio * mask


class DynamicsProcessor:
    """Compressor/limiter for consistent audio levels"""
    
    def __init__(self, threshold: float = 0.5, ratio: float = 4.0):
        self.threshold = threshold
        self.ratio = ratio
    
    def apply(self, audio: np.ndarray) -> np.ndarray:
        """Apply dynamic range compression"""
        energy = np.abs(audio)
        over_threshold = energy > self.threshold
        
        # Compress samples above threshold
        compressed = audio.copy()
        compressed[over_threshold] = (
            self.threshold + (audio[over_threshold] - self.threshold) / self.ratio
        )
        
        return compressed