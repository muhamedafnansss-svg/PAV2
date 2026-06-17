"""
Speaker Verification
Voice Authentication - Only YOUR voice activates Genos
Uses SpeechBrain for speaker recognition
"""

import numpy as np
import logging
from typing import Tuple, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class SpeakerVerifier:
    """
    Verifies speaker identity using voice biometrics
    
    Ensures only authorized users can activate Genos
    """
    
    def __init__(
        self,
        threshold: float = 0.85,
        model_name: str = "speechbrain/spkrec-ecapa-voxceleb",
        profile_path: Optional[Path] = None,
    ):
        self.threshold = threshold
        self.model_name = model_name
        self.profile_path = Path(profile_path) if profile_path else Path("models/speaker_profile.json")
        self.model = None
        self.speaker_embeddings = None
        self.is_loaded = False
        
        self._load_model()
        self._load_profile()
    
    def _load_model(self) -> None:
        """Load SpeechBrain speaker recognition model"""
        try:
            import torch
            from speechbrain.pretrained import SpeakerRecognition
            
            self.model = SpeakerRecognition.from_hparams(
                source=self.model_name,
                savedir=Path("models/speechbrain_cache"),
                run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"}
            )
            self.is_loaded = True
            logger.info(f"Loaded SpeechBrain model: {self.model_name}")
        except ImportError:
            logger.error("SpeechBrain not installed")
        except Exception as e:
            logger.error(f"Failed to load SpeechBrain model: {e}")
    
    def enroll_speaker(
        self,
        audio_samples: list,
        user_name: str = "default_user",
        metadata: dict = None,
    ) -> bool:
        """
        Enroll speaker voice
        
        Args:
            audio_samples: List of audio arrays (5-10 minutes total)
            user_name: Name for this speaker profile
            metadata: Optional metadata
            
        Returns:
            Success status
        """
        if not self.is_loaded:
            logger.error("Model not loaded")
            return False
        
        if len(audio_samples) < 3:
            logger.warning("Need at least 3 audio samples for enrollment")
            return False
        
        try:
            logger.info(f"Enrolling speaker: {user_name}")
            
            # Compute embeddings for all samples
            embeddings = []
            for i, audio in enumerate(audio_samples):
                try:
                    embedding = self.model.encode_batch(
                        audio.reshape(1, -1),
                        normalize=True
                    )
                    embeddings.append(embedding.cpu().numpy().flatten().tolist())
                    logger.debug(f"Processed sample {i+1}/{len(audio_samples)}")
                except Exception as e:
                    logger.warning(f"Error processing sample {i+1}: {e}")
                    continue
            
            if not embeddings:
                logger.error("No valid embeddings generated")
                return False
            
            # Average embeddings for speaker profile
            avg_embedding = np.mean(embeddings, axis=0)
            
            # Save profile
            profile = {
                "user_name": user_name,
                "embedding": avg_embedding.tolist(),
                "samples_used": len(embeddings),
                "threshold": self.threshold,
                "metadata": metadata or {},
            }
            
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.profile_path, "w") as f:
                json.dump(profile, f, indent=2)
            
            self.speaker_embeddings = avg_embedding
            logger.info(f"Speaker enrolled successfully: {self.profile_path}")
            return True
        except Exception as e:
            logger.error(f"Enrollment error: {e}")
            return False
    
    def _load_profile(self) -> None:
        """Load speaker profile from file"""
        if not self.profile_path.exists():
            logger.warning(f"No speaker profile found at {self.profile_path}")
            return
        
        try:
            with open(self.profile_path, "r") as f:
                profile = json.load(f)
            
            self.speaker_embeddings = np.array(profile.get("embedding", []))
            self.threshold = profile.get("threshold", self.threshold)
            logger.info(f"Loaded speaker profile: {profile.get('user_name')}")
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
    
    def verify(self, audio: np.ndarray) -> Tuple[bool, float]:
        """
        Verify if audio belongs to enrolled speaker
        
        Args:
            audio: Audio data to verify
            
        Returns:
            Tuple of (verified: bool, confidence: float)
        """
        if not self.is_loaded or self.speaker_embeddings is None:
            logger.warning("Model or profile not loaded")
            return False, 0.0
        
        try:
            # Compute embedding for test audio
            test_embedding = self.model.encode_batch(
                audio.reshape(1, -1),
                normalize=True
            ).cpu().numpy().flatten()
            
            # Compute cosine similarity
            similarity = self._cosine_similarity(
                self.speaker_embeddings,
                test_embedding
            )
            
            verified = similarity >= self.threshold
            logger.debug(f"Speaker verification: {similarity:.3f}, verified: {verified}")
            
            return verified, similarity
        except Exception as e:
            logger.error(f"Verification error: {e}")
            return False, 0.0
    
    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors"""
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot_product / (norm_a * norm_b))
    
    def set_threshold(self, threshold: float) -> None:
        """Adjust verification threshold"""
        if 0 <= threshold <= 1:
            self.threshold = threshold
            logger.info(f"Verification threshold set to {threshold}")
        else:
            logger.warning("Threshold must be between 0 and 1")
    
    def get_profile_info(self) -> dict:
        """Get information about current speaker profile"""
        if not self.profile_path.exists():
            return {}
        
        try:
            with open(self.profile_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read profile: {e}")
            return {}


class MultiSpeakerVerifier:
    """
    Support for multiple speaker profiles
    """
    
    def __init__(self, profiles_dir: Path = Path("models/speaker_profiles")):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.verifiers = {}
        self.primary_user = None
    
    def add_speaker(self, name: str, verifier: SpeakerVerifier) -> None:
        """Add speaker profile"""
        self.verifiers[name] = verifier
        if self.primary_user is None:
            self.primary_user = name
        logger.info(f"Added speaker profile: {name}")
    
    def verify_any(self, audio: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Check if audio matches any enrolled speaker
        
        Returns:
            Tuple of (speaker_name or None, confidence)
        """
        best_match = None
        best_score = 0.0
        
        for name, verifier in self.verifiers.items():
            verified, score = verifier.verify(audio)
            if score > best_score:
                best_score = score
                if verified:
                    best_match = name
        
        return best_match, best_score
    
    def verify_primary(self, audio: np.ndarray) -> Tuple[bool, float]:
        """Verify primary user only"""
        if self.primary_user and self.primary_user in self.verifiers:
            return self.verifiers[self.primary_user].verify(audio)
        return False, 0.0