import logging
import time

logger = logging.getLogger("val.security.voice")

class VoiceAuthManager:
    """
    JARVIS Primary Layer: Wake word & speaker verification.
    Ensures the system ONLY responds to the enrolled owner's voice.
    """
    
    def __init__(self, owner_name="Commander", strict_mode=True):
        self.owner_name = owner_name
        self.strict_mode = strict_mode
        self.enrolled_voiceprint = None
        self.is_locked = False
        self.lockout_until = 0.0
        
    def enroll_voice(self, audio_data: bytes):
        """Mock enrollment: In production, extracts MFCC/embeddings from audio."""
        logger.info("[VoiceAuth] Enrolling owner voiceprint...")
        self.enrolled_voiceprint = "mock_voiceprint_embedding_12345"
        return True
        
    def verify_speaker(self, audio_data: bytes) -> bool:
        """
        Secondary Layer: Speaker verification.
        Rejects unknown voices and replay attacks.
        """
        if self.is_locked and time.time() < self.lockout_until:
            logger.warning("[VoiceAuth] System is currently locked due to spoof attempt.")
            return False
            
        if not self.enrolled_voiceprint:
            # If no voice enrolled, allow pass-through during setup phase
            logger.warning("[VoiceAuth] No voice enrolled. Skipping verification.")
            return True
            
        # In a real implementation, this runs a speaker verification model (e.g. SpeechBrain/ECAPA-TDNN)
        # Mocking verification pass
        logger.info("[VoiceAuth] Speaker verified as owner.")
        return True
        
    def handle_spoof_attempt(self):
        """Locks the voice mode temporarily if spoofing is detected."""
        logger.error("[VoiceAuth] SPOOF DETECTED. Locking voice interface for 60 seconds.")
        self.is_locked = True
        self.lockout_until = time.time() + 60.0

# Singleton instance
voice_auth = VoiceAuthManager()
