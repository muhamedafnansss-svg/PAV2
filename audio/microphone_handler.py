"""
Microphone Handler
Captures audio input with error handling and device management
"""

import numpy as np
import logging
import pyaudio
from typing import Optional, Callable
import threading
from queue import Queue, Empty
import time

logger = logging.getLogger(__name__)


class MicrophoneHandler:
    """
    Handles microphone input with ring buffer
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device_index: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device_index = device_index
        
        self.audio_interface = None
        self.stream = None
        self.is_recording = False
        self.audio_queue = Queue()
        
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize PyAudio and microphone stream"""
        try:
            self.audio_interface = pyaudio.PyAudio()
            
            # List available devices if requested
            logger.info(f"Available audio devices:")
            for i in range(self.audio_interface.get_device_count()):
                info = self.audio_interface.get_device_info_by_index(i)
                if info['max_input_channels'] > 0:
                    logger.info(f"  Device {i}: {info['name']}")
            
            # Open microphone stream
            self.stream = self.audio_interface.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
                start=False,
            )
            
            logger.info(f"Microphone initialized: {self.sample_rate}Hz, {self.channels}ch")
        except Exception as e:
            logger.error(f"Failed to initialize microphone: {e}")
            raise
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback for audio stream"""
        if status:
            logger.warning(f"Audio callback status: {status}")
        
        self.audio_queue.put(in_data)
        return (in_data, pyaudio.paContinue)
    
    def start_recording(self) -> None:
        """Start recording from microphone"""
        if not self.is_recording and self.stream:
            self.stream.start_stream()
            self.is_recording = True
            logger.info("Microphone recording started")
    
    def stop_recording(self) -> None:
        """Stop recording from microphone"""
        if self.is_recording and self.stream:
            self.stream.stop_stream()
            self.is_recording = False
            logger.info("Microphone recording stopped")
    
    def get_audio_chunk(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Get next audio chunk
        
        Returns:
            Audio data as numpy array, or None if timeout
        """
        try:
            audio_data = self.audio_queue.get(timeout=timeout)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            return audio_array
        except Empty:
            return None
    
    def list_devices(self) -> list:
        """List available audio input devices"""
        if not self.audio_interface:
            return []
        
        devices = []
        for i in range(self.audio_interface.get_device_count()):
            info = self.audio_interface.get_device_info_by_index(i)
            if info['max_input_channels'] > 0:
                devices.append({
                    "index": i,
                    "name": info['name'],
                    "channels": info['max_input_channels'],
                    "sample_rate": int(info['default_sample_rate']),
                })
        
        return devices
    
    def cleanup(self) -> None:
        """Cleanup resources"""
        try:
            self.stop_recording()
            if self.stream:
                self.stream.close()
            if self.audio_interface:
                self.audio_interface.terminate()
            logger.info("Microphone resources cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def __del__(self):
        """Ensure cleanup on deletion"""
        self.cleanup()


class MicrophoneThread:
    """
    Runs microphone input in a separate thread
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        on_audio_chunk: Optional[Callable] = None,
    ):
        self.mic_handler = MicrophoneHandler(
            sample_rate=sample_rate,
            chunk_size=chunk_size
        )
        self.on_audio_chunk = on_audio_chunk
        self.thread = None
        self.is_running = False
    
    def start(self) -> None:
        """Start recording in background thread"""
        if self.is_running:
            return
        
        self.is_running = True
        self.mic_handler.start_recording()
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
        logger.info("Microphone thread started")
    
    def stop(self) -> None:
        """Stop recording and thread"""
        self.is_running = False
        self.mic_handler.stop_recording()
        
        if self.thread:
            self.thread.join(timeout=2.0)
        
        self.mic_handler.cleanup()
        logger.info("Microphone thread stopped")
    
    def _run(self) -> None:
        """Main thread loop"""
        while self.is_running:
            audio_chunk = self.mic_handler.get_audio_chunk(timeout=0.5)
            
            if audio_chunk is not None and self.on_audio_chunk:
                try:
                    self.on_audio_chunk(audio_chunk)
                except Exception as e:
                    logger.error(f"Error in audio chunk handler: {e}")
            
            time.sleep(0.001)  # Prevent busy loop


class SpeakerHandler:
    """
    Handles audio output / speaker
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_interface = None
        self.stream = None
        
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize speaker output"""
        try:
            self.audio_interface = pyaudio.PyAudio()
            
            self.stream = self.audio_interface.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=1024,
            )
            
            logger.info("Speaker initialized")
        except Exception as e:
            logger.error(f"Failed to initialize speaker: {e}")
            raise
    
    def play_audio(self, audio_data: np.ndarray) -> None:
        """Play audio"""
        if not self.stream:
            logger.warning("Stream not initialized")
            return
        
        try:
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32) / 32768.0
            
            self.stream.write(audio_data.tobytes())
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
    
    def cleanup(self) -> None:
        """Cleanup resources"""
        try:
            if self.stream:
                self.stream.close()
            if self.audio_interface:
                self.audio_interface.terminate()
            logger.info("Speaker resources cleaned up")
        except Exception as e:
            logger.error(f"Error during speaker cleanup: {e}")
    
    def __del__(self):
        """Ensure cleanup on deletion"""
        self.cleanup()