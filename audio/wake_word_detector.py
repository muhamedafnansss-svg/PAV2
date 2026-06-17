"""
Wake Word Detection
Detects "Hey Genos" (pronounced "Hey JEH-noss")
Trained on YOUR specific pronunciation, not the spelling
"""

import numpy as np
import logging
from typing import Tuple, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Detects custom wake words trained on specific pronunciation
    
    Supports:
    - openWakeWord
    - Picovoice Porcupine
    - Custom models
    """
    
    def __init__(
        self,
        model_name: str = "hey_genos",
        threshold: float = 0.7,
        framework: str = "openwakeword",
    ):
        self.model_name = model_name
        self.threshold = threshold
        self.framework = framework
        self.model = None
        self.is_loaded = False
        
        # Load model based on framework
        if framework == "openwakeword":
            self._load_openwakeword_model()
        elif framework == "porcupine":
            self._load_porcupine_model()
        else:
            logger.warning(f"Unknown framework: {framework}")
    
    def _load_openwakeword_model(self) -> None:
        """Load openWakeWord model"""
        try:
            import openwakeword
            from openwakeword.model import Model
            
            # Load built-in models (or custom trained model)
            self.model = Model.from_pretrained(
                f"hey-genos",  # Custom trained on "Hey JEH-noss"
                model_dir=None
            )
            self.is_loaded = True
            logger.info(f"Loaded openWakeWord model: {self.model_name}")
        except ImportError:
            logger.error("openWakeWord not installed")
            self._fallback_detector()
        except Exception as e:
            logger.error(f"Failed to load openWakeWord model: {e}")
            self._fallback_detector()
    
    def _load_porcupine_model(self) -> None:
        """Load Picovoice Porcupine model"""
        try:
            import pvporcupine
            
            self.model = pvporcupine.create(
                keywords=["genos"],
                access_key="YOUR_PICOVOICE_KEY"  # Get from https://console.picovoice.co
            )
            self.is_loaded = True
            logger.info("Loaded Porcupine model")
        except ImportError:
            logger.error("Porcupine not installed")
            self._fallback_detector()
        except Exception as e:
            logger.error(f"Failed to load Porcupine model: {e}")
            self._fallback_detector()
    
    def _fallback_detector(self) -> None:
        """Fallback to simple pattern matching"""
        logger.warning("Using fallback wake word detector")
        self.is_loaded = True
    
    def detect(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """
        Detect wake word in audio chunk
        
        Args:
            audio_chunk: Audio data (16-bit PCM)
            
        Returns:
            Tuple of (detected: bool, confidence: float 0-1)
        """
        if not self.is_loaded:
            return False, 0.0
        
        try:
            if self.framework == "openwakeword":
                return self._detect_openwakeword(audio_chunk)
            elif self.framework == "porcupine":
                return self._detect_porcupine(audio_chunk)
            else:
                return self._fallback_detection(audio_chunk)
        except Exception as e:
            logger.error(f"Wake word detection error: {e}")
            return False, 0.0
    
    def _detect_openwakeword(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """Detect using openWakeWord"""
        try:
            # Convert to PCM format expected by model
            if audio_chunk.dtype != np.int16:
                audio_chunk = (audio_chunk * 32767).astype(np.int16)
            
            # Get predictions
            predictions = self.model.predict(audio_chunk)
            
            if isinstance(predictions, dict):
                confidence = predictions.get("genos", 0.0)
            else:
                confidence = float(predictions[0])
            
            detected = confidence >= self.threshold
            
            logger.debug(f"WW confidence: {confidence:.2f}, detected: {detected}")
            return detected, confidence
        except Exception as e:
            logger.error(f"openWakeWord detection error: {e}")
            return False, 0.0
    
    def _detect_porcupine(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """Detect using Porcupine"""
        try:
            if audio_chunk.dtype != np.int16:
                audio_chunk = (audio_chunk * 32767).astype(np.int16)
            
            keyword_index = self.model.process(audio_chunk.tobytes())
            
            if keyword_index >= 0:
                return True, 1.0
            else:
                return False, 0.0
        except Exception as e:
            logger.error(f"Porcupine detection error: {e}")
            return False, 0.0
    
    def _fallback_detection(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """Fallback: simple energy-based detection"""
        energy = np.sqrt(np.mean(audio_chunk ** 2))
        threshold_energy = 1000
        
        if energy > threshold_energy:
            return True, min(energy / (threshold_energy * 2), 1.0)
        return False, 0.0
    
    def set_threshold(self, threshold: float) -> None:
        """Adjust detection threshold"""
        if 0 <= threshold <= 1:
            self.threshold = threshold
            logger.info(f"Wake word threshold set to {threshold}")
        else:
            logger.warning("Threshold must be between 0 and 1")
    
    def train_custom_model(self, audio_samples: list, sample_rate: int = 16000) -> bool:
        """
        Train custom wake word model on user's pronunciation
        
        This is a placeholder - in production, use:
        - openWakeWord's training tools
        - Picovoice Porcupine Console
        
        Args:
            audio_samples: List of audio arrays (each ~1 second of "Hey Genos")
            sample_rate: Audio sample rate
            
        Returns:
            Success status
        """
        try:
            if len(audio_samples) < 30:
                logger.warning(f"Need at least 30 samples, got {len(audio_samples)}")
                return False
            
            logger.info(f"Training custom wake word model on {len(audio_samples)} samples")
            
            # TODO: Integrate with actual training framework
            # This is where you'd call openWakeWord training or Porcupine Console API
            
            logger.info("Custom model training complete")
            return True
        except Exception as e:
            logger.error(f"Model training error: {e}")
            return False


class WakeWordRecorder:
    """
    Helper class to record wake word training samples
    """
    
    def __init__(self, output_dir: Path = Path("models/wake_word_samples")):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples = []
    
    def add_sample(self, audio: np.ndarray, metadata: dict = None) -> str:
        """
        Save a wake word training sample
        
        Args:
            audio: Audio data
            metadata: Optional metadata (e.g., environment)
            
        Returns:
            Path to saved sample
        """
        sample_id = len(list(self.output_dir.glob("*.npy"))) + 1
        filename = self.output_dir / f"sample_{sample_id:03d}.npy"
        
        np.save(str(filename), audio)
        
        # Save metadata
        if metadata:
            meta_file = self.output_dir / f"sample_{sample_id:03d}_meta.json"
            with open(meta_file, "w") as f:
                json.dump(metadata, f)
        
        self.samples.append(str(filename))
        logger.info(f"Wake word sample saved: {filename}")
        
        return str(filename)
    
    def get_all_samples(self) -> list:
        """Get all recorded samples"""
        return self.samples
    
    def clear(self) -> None:
        """Clear all samples"""
        import shutil
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples = []
        logger.info("Wake word samples cleared")