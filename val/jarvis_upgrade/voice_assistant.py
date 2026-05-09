import pyttsx3
import queue
import sounddevice as sd
import numpy as np
import threading
from faster_whisper import WhisperModel

class JarvisVoiceModule:
    """
    Local voice module for interactive speech capabilities.
    Uses faster-whisper for completely local offline speech-to-text.
    Uses pyttsx3 for completely local offline text-to-speech.
    """
    
    def __init__(self, model_size="base.en"):
        # Text-to-Speech Engine
        self.tts_engine = pyttsx3.init()
        self.configure_tts()
        
        # Speech-to-Text Engine
        print(f"Loading local faster-whisper model ({model_size})...")
        # Run on CPU by default for broader compatibility, or GPU if specified
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.audio_queue = queue.Queue()
        self.is_listening = False
        
    def configure_tts(self):
        """Configures voice properties for TTS."""
        voices = self.tts_engine.getProperty('voices')
        # Try to select a suitable voice
        if len(voices) > 0:
            self.tts_engine.setProperty('voice', voices[0].id)
        self.tts_engine.setProperty('rate', 170) # speaking rate
        self.tts_engine.setProperty('volume', 1.0) # max volume
        
    def speak(self, text):
        """Speaks the given text out loud asynchronously."""
        def run_tts():
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        
        threading.Thread(target=run_tts, daemon=True).start()

    def _audio_callback(self, indata, frames, time, status):
        """Called for each audio block from the microphone."""
        if status:
            print(status, flush=True)
        if self.is_listening:
            self.audio_queue.put(indata.copy())

    def start_listening(self):
        """Starts listening to the microphone in the background."""
        self.is_listening = True
        self.audio_queue = queue.Queue()
        print("Jarvis is now listening...")

    def stop_listening_and_transcribe(self):
        """Stops listening and transcribes the recorded audio."""
        self.is_listening = False
        print("Processing audio...")
        
        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
            
        if not audio_data:
            return ""
            
        # Concatenate audio chunks
        audio_np = np.concatenate(audio_data, axis=0)
        # Convert to expected 1D float32 array
        audio_np = audio_np.flatten().astype(np.float32)
        
        # Transcribe
        segments, info = self.stt_model.transcribe(audio_np, beam_size=5)
        
        text = " ".join([segment.text for segment in segments])
        return text.strip()

# Example usage/testing
if __name__ == "__main__":
    voice = JarvisVoiceModule()
    voice.speak("Jarvis voice module initialized and ready.")
    print("Voice initialized. Use `start_listening()` and `stop_listening_and_transcribe()` to test STT.")
