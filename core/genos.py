"""
Genos - Main AI Assistant Class
Orchestrates all audio, LLM, and session management
"""

import logging
from typing import Optional, Dict
import time

from config import (
    ECHO_CANCELLATION,
    NOISE_SUPPRESSION,
    AUTO_GAIN_CONTROL,
    WAKE_WORD_THRESHOLD,
    SPEAKER_VERIFICATION_ENABLED,
    SPEAKER_VERIFICATION_THRESHOLD,
    SESSION_TIMEOUT,
    SYSTEM_PROMPT,
    LLM_MODEL,
    LLM_TEMPERATURE,
)

from audio.audio_processor import AudioProcessor
from audio.wake_word_detector import WakeWordDetector
from audio.speaker_verifier import SpeakerVerifier
from audio.voice_activity_detector import VADHandler
from audio.microphone_handler import MicrophoneHandler, SpeakerHandler
from audio.tts_engine import TTSEngine

from core.session_manager import SessionManager
from core.memory_manager import MemoryManager
from core.ollama_interface import OllamaInterface

logger = logging.getLogger(__name__)


class Genos:
    """
    Main Genos AI Assistant
    
    Pipeline:
    Microphone → Audio Processing → Wake Word → Speaker Verification →
    VAD → Speech-to-Text → Session Memory → LLM → TTS → Speaker
    """
    
    def __init__(self):
        logger.info("\n" + "="*60)
        logger.info("🤖 Initializing Genos AI Assistant")
        logger.info("="*60 + "\n")
        
        # Audio Pipeline
        self.audio_processor = AudioProcessor(
            echo_cancellation=ECHO_CANCELLATION,
            noise_suppression=NOISE_SUPPRESSION,
            auto_gain_control=AUTO_GAIN_CONTROL,
        )
        
        self.wake_word_detector = WakeWordDetector(
            threshold=WAKE_WORD_THRESHOLD,
        )
        
        self.speaker_verifier = SpeakerVerifier(
            threshold=SPEAKER_VERIFICATION_THRESHOLD,
        )
        
        self.vad_handler = VADHandler(
            session_timeout=SESSION_TIMEOUT,
        )
        
        self.microphone = MicrophoneHandler()
        self.speaker = SpeakerHandler()
        
        # Speech Processing
        self.tts_engine = TTSEngine()
        
        # LLM
        self.llm = OllamaInterface(model=LLM_MODEL)
        
        # Session Management
        self.session_manager = SessionManager()
        self.memory_manager = MemoryManager()
        
        # State
        self.is_running = False
        self.is_listening = False
        self.current_state = "IDLE"
        self.last_activity = time.time()
        
        # Debug indicators
        self.debug_info = {
            "wake_word_detected": False,
            "speaker_verified": False,
            "speech_detected": False,
            "listening_timeout": 0,
            "current_state": "IDLE",
            "transcription_confidence": 0.0,
            "speaker_confidence": 0.0,
        }
        
        logger.info("✅ Genos initialized successfully")
        logger.info(f"\n📊 Configuration:")
        logger.info(f"  - Speaker verification: {SPEAKER_VERIFICATION_ENABLED}")
        logger.info(f"  - Session timeout: {SESSION_TIMEOUT}s")
        logger.info(f"  - LLM Model: {LLM_MODEL}\n")
    
    def start(self) -> None:
        """Start Genos listening"""
        if self.is_running:
            logger.warning("Already running")
            return
        
        logger.info("🎙️  Starting Genos...")
        self.is_running = True
        self.microphone.start_recording()
        logger.info("✅ Genos is listening for wake word")
    
    def stop(self) -> None:
        """Stop Genos"""
        logger.info("🛑 Stopping Genos...")
        self.is_running = False
        self.is_listening = False
        self.microphone.stop_recording()
        self.speaker.cleanup()
        logger.info("✅ Genos stopped")
    
    def process_audio_chunk(self, audio_chunk) -> None:
        """Process incoming audio chunk"""
        if not self.is_running:
            return
        
        try:
            processed_audio, metadata = self.audio_processor.process_chunk(audio_chunk)
            
            if not self.is_listening:
                detected, confidence = self.wake_word_detector.detect(processed_audio)
                self.debug_info["wake_word_detected"] = detected
                
                if detected:
                    logger.info(f"🔔 Wake word detected! (confidence: {confidence:.2f})")
                    
                    if SPEAKER_VERIFICATION_ENABLED:
                        verified, sp_confidence = self.speaker_verifier.verify(processed_audio)
                        self.debug_info["speaker_verified"] = verified
                        self.debug_info["speaker_confidence"] = sp_confidence
                        
                        if not verified:
                            logger.warning(f"❌ Speaker verification failed: {sp_confidence:.2f}")
                            return
                        
                        logger.info(f"✅ Speaker verified (confidence: {sp_confidence:.2f})")
                    
                    self.is_listening = True
                    self.current_state = "LISTENING"
                    self.session_manager.create_session()
                    self.vad_handler.reset()
                    logger.info("👂 Listening...")
            
            else:
                if self.current_state == "SPEAKING":
                    verified, sp_conf = self.speaker_verifier.verify(processed_audio)
                    if verified:
                        logger.info("⏸️  Interrupted by user")
                        self.current_state = "LISTENING"
                
                vad_update = self.vad_handler.process(processed_audio)
                self.debug_info["speech_detected"] = vad_update["has_speech"]
                
                if vad_update["state"] == "SESSION_TIMEOUT":
                    logger.info("⏱️  Session timeout")
                    self._end_session()
            
            self.last_activity = time.time()
        
        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
    
    def handle_user_input(self, text: str) -> None:
        """Process user speech input"""
        if not self.is_listening:
            return
        
        logger.info(f"👤 User: {text}")
        
        self.session_manager.add_message("user", text)
        self.memory_manager.save_message(
            self.session_manager.current_session.session_id,
            "user",
            text
        )
        
        self._get_response(text)
    
    def _get_response(self, user_input: str) -> None:
        """Get and speak response from LLM"""
        try:
            self.current_state = "THINKING"
            logger.info("🧠 Thinking...")
            
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ]
            
            response = self.llm.get_response(
                messages,
                temperature=LLM_TEMPERATURE,
            )
            
            if not response:
                logger.error("No response from LLM")
                return
            
            logger.info(f"🤖 Genos: {response}")
            
            self.session_manager.add_message("assistant", response)
            self.memory_manager.save_message(
                self.session_manager.current_session.session_id,
                "assistant",
                response
            )
            
            self._speak_response(response)
        
        except Exception as e:
            logger.error(f"Error getting response: {e}")
    
    def _speak_response(self, text: str) -> None:
        """Synthesize and play response"""
        try:
            self.current_state = "SPEAKING"
            logger.info("🔊 Speaking...")
            
            audio_data = self.tts_engine.synthesize(text)
            
            if audio_data is None:
                logger.error("TTS failed")
                return
            
            self.speaker.play_audio(audio_data)
            logger.info("✅ Response delivered")
            
            self.current_state = "LISTENING"
        
        except Exception as e:
            logger.error(f"Error speaking: {e}")
    
    def _end_session(self) -> None:
        """End current session"""
        if self.session_manager.current_session:
            session = self.session_manager.current_session
            logger.info(f"📊 Session ended (duration: {session.get_duration():.1f}s, messages: {len(session.messages)})")
            self.session_manager.end_session()
        
        self.is_listening = False
        self.current_state = "IDLE"
        logger.info("👂 Waiting for wake word...")
    
    def get_status(self) -> Dict:
        """Get current Genos status"""
        return {
            "is_running": self.is_running,
            "is_listening": self.is_listening,
            "current_state": self.current_state,
            "session": self.session_manager.current_session.to_dict() if self.session_manager.current_session else None,
            "debug_info": self.debug_info,
            "memory": self.memory_manager.get_stats(),
            "available_models": self.llm.list_models(),
            "current_model": self.llm.model,
        }
    
    def switch_model(self, model_name: str) -> None:
        """Switch to different LLM model"""
        available = self.llm.list_models()
        if model_name in available:
            self.llm.set_model(model_name)
            logger.info(f"Switched to model: {model_name}")
        else:
            logger.warning(f"Model not available: {model_name}")
            logger.info(f"Available models: {available}")
    
    def cleanup(self) -> None:
        """Cleanup resources"""
        self.stop()
        logger.info("✅ Genos cleanup complete")
