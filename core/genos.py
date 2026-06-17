import logging
from typing import Optional, Dict
import time

from config import (ECHO_CANCELLATION, NOISE_SUPPRESSION, AUTO_GAIN_CONTROL, WAKE_WORD_THRESHOLD,
                   SPEAKER_VERIFICATION_ENABLED, SPEAKER_VERIFICATION_THRESHOLD, SESSION_TIMEOUT, SYSTEM_PROMPT, LLM_MODEL, LLM_TEMPERATURE)

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
    def __init__(self):
        logger.info("\n" + "="*60 + "\n🤖 Initializing Genos AI Assistant\n" + "="*60 + "\n")
        
        self.audio_processor = AudioProcessor(echo_cancellation=ECHO_CANCELLATION, noise_suppression=NOISE_SUPPRESSION, auto_gain_control=AUTO_GAIN_CONTROL)
        self.wake_word_detector = WakeWordDetector(threshold=WAKE_WORD_THRESHOLD)
        self.speaker_verifier = SpeakerVerifier(threshold=SPEAKER_VERIFICATION_THRESHOLD)
        self.vad_handler = VADHandler(session_timeout=SESSION_TIMEOUT)
        self.microphone = MicrophoneHandler()
        self.speaker = SpeakerHandler()
        self.tts_engine = TTSEngine()
        self.llm = OllamaInterface(model=LLM_MODEL)
        self.session_manager = SessionManager()
        self.memory_manager = MemoryManager()
        
        self.is_running = False
        self.is_listening = False
        self.current_state = "IDLE"
        self.last_activity = time.time()
        
        logger.info("✅ Genos initialized successfully\n")
    
    def start(self) -> None:
        if self.is_running:
            return
        logger.info("🎙️ Starting Genos...")
        self.is_running = True
        self.microphone.start_recording()
        logger.info("✅ Genos is listening")
    
    def stop(self) -> None:
        logger.info("🛑 Stopping Genos...")
        self.is_running = False
        self.is_listening = False
        self.microphone.stop_recording()
        logger.info("✅ Genos stopped")
    
    def process_audio_chunk(self, audio_chunk) -> None:
        if not self.is_running:
            return
        try:
            processed_audio, metadata = self.audio_processor.process_chunk(audio_chunk)
            if not self.is_listening:
                detected, confidence = self.wake_word_detector.detect(processed_audio)
                if detected:
                    if SPEAKER_VERIFICATION_ENABLED:
                        verified, sp_confidence = self.speaker_verifier.verify(processed_audio)
                        if not verified:
                            return
                    self.is_listening = True
                    self.current_state = "LISTENING"
                    self.session_manager.create_session()
                    self.vad_handler.reset()
                    logger.info("👂 Listening...")
            else:
                vad_update = self.vad_handler.process(processed_audio)
                if vad_update["state"] == "SESSION_TIMEOUT":
                    self._end_session()
            self.last_activity = time.time()
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def handle_user_input(self, text: str) -> None:
        if not self.is_listening:
            return
        logger.info(f"👤 User: {text}")
        self.session_manager.add_message("user", text)
        self.memory_manager.save_message(self.session_manager.current_session.session_id, "user", text)
        self._get_response(text)
    
    def _get_response(self, user_input: str) -> None:
        try:
            self.current_state = "THINKING"
            logger.info("🧠 Thinking...")
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_input}]
            response = self.llm.get_response(messages, temperature=LLM_TEMPERATURE)
            if not response:
                return
            logger.info(f"🤖 Genos: {response}")
            self.session_manager.add_message("assistant", response)
            self.memory_manager.save_message(self.session_manager.current_session.session_id, "assistant", response)
            self._speak_response(response)
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _speak_response(self, text: str) -> None:
        try:
            self.current_state = "SPEAKING"
            logger.info("🔊 Speaking...")
            audio_data = self.tts_engine.synthesize(text)
            if audio_data is None:
                return
            self.speaker.play_audio(audio_data)
            logger.info("✅ Response delivered")
            self.current_state = "LISTENING"
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _end_session(self) -> None:
        if self.session_manager.current_session:
            logger.info(f"📊 Session ended")
            self.session_manager.end_session()
        self.is_listening = False
        self.current_state = "IDLE"
        logger.info("👂 Waiting...")
    
    def get_status(self) -> Dict:
        return {
            "is_running": self.is_running,
            "is_listening": self.is_listening,
            "current_state": self.current_state,
            "session": self.session_manager.current_session.to_dict() if self.session_manager.current_session else None,
            "available_models": self.llm.list_models(),
            "current_model": self.llm.model,
        }
    
    def switch_model(self, model_name: str) -> None:
        available = self.llm.list_models()
        if model_name in available:
            self.llm.set_model(model_name)
            logger.info(f"Switched to: {model_name}")
        else:
            logger.warning(f"Model not available: {model_name}")
    
    def cleanup(self) -> None:
        self.stop()
        logger.info("✅ Cleanup complete")
