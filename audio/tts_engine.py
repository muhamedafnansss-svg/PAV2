"""
Text-to-Speech Engine
Converts text responses to natural speech using Piper TTS
"""

import numpy as np
import logging
from typing import Optional
import subprocess
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self, voice: str = "en_US-amy-medium", speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self.replacements = {"Genos": "Jeh-noss", "genos": "Jeh-noss", "AI": "A-I"}
        self.is_available = self._check_piper_available()
        logger.info(f"TTS Engine initialized: {voice}")
    
    def _check_piper_available(self) -> bool:
        try:
            subprocess.run(["piper", "--version"], capture_output=True, timeout=2)
            logger.info("Piper TTS available")
            return True
        except:
            logger.warning("Piper TTS not available")
            return False
    
    def _apply_replacements(self, text: str) -> str:
        for original, replacement in self.replacements.items():
            text = text.replace(original, replacement)
        return text
    
    def synthesize(self, text: str) -> Optional[np.ndarray]:
        if not self.is_available:
            return None
        
        try:
            text = self._apply_replacements(text)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                output_file = tmp.name
            
            cmd = ["piper", "--model", self.voice, "--output-file", output_file]
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.communicate(input=text.encode())
            
            if process.returncode == 0:
                import soundfile as sf
                audio_data, sr = sf.read(output_file)
                Path(output_file).unlink()
                return (audio_data * 32767).astype(np.int16)
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
        return None
    
    def set_speed(self, speed: float) -> None:
        if 0.1 <= speed <= 5.0:
            self.speed = speed
