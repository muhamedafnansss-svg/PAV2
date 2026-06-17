"""
Text-to-Speech Engine
Converts text responses to natural speech using Piper TTS
Customizable pronunciation for "Genos" -> "Jeh-noss"
"""

import numpy as np
import logging
from typing import Optional, List, Tuple
import subprocess
import json
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Text-to-Speech using Piper TTS
    """
    
    def __init__(
        self,
        voice: str = "en_US-amy-medium",
        speed: float = 1.0,
        noise: float = 0.667,
        noise_w: float = 0.8,
    ):
        self.voice = voice
        self.speed = speed
        self.noise = noise
        self.noise_w = noise_w
        self.sample_rate = 22050
        
        self.replacements = {
            "Genos": "Jeh-noss",
            "genos": "Jeh-noss",
            "JEH-noss": "Jeh-noss",
            "AI": "A-I",
        }
        
        self.is_available = self._check_piper_available()
        logger.info(f"TTS Engine initialized: {voice}")
    
    def _check_piper_available(self) -> bool:
        """Check if Piper TTS is installed"""
        try:
            result = subprocess.run(["piper", "--version"], capture_output=True)
            if result.returncode == 0:
                logger.info("Piper TTS is available")
                return True
        except FileNotFoundError:
            logger.warning("Piper TTS not found in PATH")
        return False
    
    def _apply_replacements(self, text: str) -> str:
        """Apply pronunciation replacements"""
        for original, replacement in self.replacements.items():
            text = text.replace(original, replacement)
        return text
    
    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """Synthesize text to speech"""
        if not self.is_available:
            logger.error("TTS not available")
            return None
        
        try:
            text = self._apply_replacements(text)
            logger.debug(f"Synthesizing: {text}")
            return self._synthesize_cli(text)
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return None
    
    def _synthesize_cli(self, text: str) -> Optional[np.ndarray]:
        """Synthesize using Piper CLI"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                output_file = tmp.name
            
            cmd = [
                "piper",
                "--model", self.voice,
                "--output-file", output_file,
                "--speed", str(self.speed),
            ]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            stdout, stderr = process.communicate(input=text.encode())
            
            if process.returncode != 0:
                logger.error(f"Piper error: {stderr.decode()}")
                return None
            
            import soundfile as sf
            audio_data, sr = sf.read(output_file)
            
            Path(output_file).unlink()
            
            audio_data = (audio_data * 32767).astype(np.int16)
            logger.debug(f"Synthesized {len(audio_data)} samples")
            return audio_data
        except Exception as e:
            logger.error(f"CLI synthesis error: {e}")
            return None
    
    def set_voice(self, voice: str) -> None:
        """Change voice"""
        self.voice = voice
        logger.info(f"Voice changed to {voice}")
    
    def set_speed(self, speed: float) -> None:
        """Change speech speed"""
        if 0.1 <= speed <= 5.0:
            self.speed = speed
            logger.info(f"Speed set to {speed}")
        else:
            logger.warning("Speed must be between 0.1 and 5.0")
    
    def add_replacement(self, original: str, replacement: str) -> None:
        """Add custom pronunciation replacement"""
        self.replacements[original] = replacement
        logger.info(f"Added replacement: {original} -> {replacement}")
