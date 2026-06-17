"""
Genos Configuration File
Complete settings for audio pipeline, LLM, and UI
"""

import os
from pathlib import Path

# ============================================================================
# PROJECT PATHS
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"
STATIC_DIR = BASE_DIR / "web" / "static"
TEMPLATES_DIR = BASE_DIR / "web" / "templates"

# Create directories if they don't exist
LOGS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

# ============================================================================
# AUDIO HARDWARE SETTINGS
# ============================================================================
SAMPLE_RATE = 16000  # Hz - Optimal for speech recognition
CHUNK_SIZE = 1024  # Samples per chunk
CHANNELS = 1  # Mono
FORMAT = "int16"  # 16-bit audio
DEVICE_INDEX = None  # Auto-detect or specify manually

# ============================================================================
# AUDIO PROCESSING PIPELINE
# ============================================================================
# WebRTC Audio Processing - Essential for clean audio
ECHO_CANCELLATION = True  # Removes feedback from speakers
NOISE_SUPPRESSION = True  # Reduces background noise
AUTO_GAIN_CONTROL = True  # Normalizes volume levels
VOICE_DETECTION_THRESHOLD = 0.5  # Silero VAD confidence (0-1)

# ============================================================================
# WAKE WORD CONFIGURATION
# ============================================================================
# YOUR PRONUNCIATION - Not the spelling!
WAKE_WORD = "Hey Genos"  # Text display
WAKE_WORD_PRONUNCIATION = "Hey JEH-noss"  # How you say it
WAKE_WORD_MODEL_PATH = MODELS_DIR / "wake_word_model.pkl"

# Wake word detection settings
WAKE_WORD_THRESHOLD = 0.7  # Confidence threshold (0-1)
WAKE_WORD_TIMEOUT = 10  # Seconds to listen for wake word before resetting

# ============================================================================
# SPEAKER VERIFICATION
# ============================================================================
# Your voice profile - Only YOU can activate Genos
SPEAKER_PROFILE_PATH = MODELS_DIR / "speaker_profile.json"
SPEAKER_VERIFICATION_ENABLED = True
SPEAKER_VERIFICATION_THRESHOLD = 0.85  # Confidence threshold (0-1)
SPEAKER_VERIFICATION_MIN_DURATION = 1.0  # Minimum seconds of speech

# ============================================================================
# VOICE ACTIVITY DETECTION (Silero VAD)
# ============================================================================
# Intelligent silence detection
VOICE_ACTIVITY_DETECTOR = "silero"  # "silero" or "webrtcvad"
VAD_THRESHOLD = 0.5  # Speech confidence threshold (0-1)
SILENCE_DURATION_START = 0.5  # Seconds to start recording
SILENCE_DURATION_END = 2.0  # Seconds of silence to end recording

# ============================================================================
# SESSION MANAGEMENT
# ============================================================================
SESSION_TIMEOUT = 15  # Seconds of silence before session ends
MAX_SESSION_DURATION = 300  # Max 5 minutes per session
SESSION_AUTO_SAVE = True
SESSION_DB_PATH = MODELS_DIR / "conversation_db.sqlite"

# ============================================================================
# SPEECH-TO-TEXT (Faster-Whisper)
# ============================================================================
STT_MODEL = "medium"  # tiny, base, small, medium, large
STT_DEVICE = "cuda"  # cuda or cpu
STT_COMPUTE_TYPE = "float16"  # float32, float16, int8
STT_LANGUAGE = "en"
STT_BEAM_SIZE = 5
STT_PATIENCE = 1.0

# RTX 4070 Laptop Settings (Recommended)
# MODEL_SIZE = "medium"  # Best accuracy/speed balance
# DEVICE = "cuda"
# COMPUTE_TYPE = "float16"
# Don't use "tiny" or "base" - they sacrifice accuracy

# ============================================================================
# TEXT-TO-SPEECH (Piper)
# ============================================================================
TTS_VOICE = "en_US-amy-medium"  # High quality voice
TTS_SPEED = 1.0  # 0.5 = slow, 1.0 = normal, 2.0 = fast
TTS_NOISE = 0.667  # Voice quality (0-1, higher = more natural)
TTS_NOISE_W = 0.8  # Noise weight

# TTS Pronunciation Replacements
# Fix how Genos pronounces its own name
TTS_REPLACEMENTS = {
    "Genos": "Jeh-noss",
    "JEH-noss": "Jeh-noss",
    "AI": "A-I",
}

# ============================================================================
# LANGUAGE MODEL (Ollama Integration)
# ============================================================================
OLLAMA_API_URL = "http://localhost:11434"  # Default Ollama port
LLM_MODEL = "llama2"  # or "mistral", "neural-chat", etc.
LLM_TEMPERATURE = 0.7  # Creativity (0 = deterministic, 1 = creative)
LLM_TOP_P = 0.9
LLM_TOP_K = 40
LLM_MAX_TOKENS = 500  # Max response length
LLM_CONTEXT_WINDOW = 4096  # Tokens of context
LLM_NUM_THREADS = 4

# System Prompt for Genos
SYSTEM_PROMPT = """You are Genos, a personal AI assistant. You are helpful, friendly, and concise.
You respond to user queries with accurate information and assist with tasks.
Keep responses brief (1-3 sentences) unless asked for more detail.
Your name is pronounced "Jeh-noss" not "Gee-nos".
You are running locally on the user's computer - never mention cloud services."""

# ============================================================================
# INTERRUPTION HANDLING
# ============================================================================
INTERRUPTION_ENABLED = True
INTERRUPTION_REQUIRES_SPEAKER_VERIFICATION = True
INTERRUPTION_GRACE_PERIOD = 0.5  # Seconds before checking for interruption

# ============================================================================
# CONVERSATION MEMORY
# ============================================================================
MEMORY_TYPE = "sqlite"  # sqlite or redis
SHORT_TERM_MEMORY_SIZE = 10  # Messages to keep in current session
LONG_TERM_MEMORY_ENABLED = True
MEMORY_AUTO_SAVE = True

# ============================================================================
# WEB UI SETTINGS
# ============================================================================
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

# WebSocket settings
SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
SOCKETIO_ASYNC_HANDLERS = True
SOCKETIO_MESSAGE_QUEUE = None

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL = "DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = LOGS_DIR / "genos.log"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_CONSOLE_OUTPUT = True
LOG_FILE_OUTPUT = True
LOG_FILE_SIZE = 10485760  # 10MB
LOG_BACKUP_COUNT = 5

# ============================================================================
# DEBUG & MONITORING
# ============================================================================
DEBUG_MODE = False
SHOW_AUDIO_WAVEFORM = False  # Show real-time audio visualization
SHOW_TRANSCRIPTION_CONFIDENCE = True
SHOW_SPEAKER_VERIFICATION_SCORE = True
SHOW_LATENCY_METRICS = True
SHOW_STATE_TRANSITIONS = True

# Debug indicators for UI
DEBUG_INDICATORS = {
    "wake_word_detected": False,
    "speaker_verified": False,
    "speech_detected": False,
    "listening_timeout": 0,
    "current_state": "idle",
    "transcription_confidence": 0.0,
    "speaker_confidence": 0.0,
}

# ============================================================================
# PERFORMANCE OPTIMIZATION
# ============================================================================
ENABLE_AUDIO_CACHING = True
ENABLE_MODEL_CACHING = True
NUM_WORKERS = 2
BUFFER_SIZE = 4096

# ============================================================================
# DEVELOPMENT & TESTING
# ============================================================================
TEST_MODE = False
TEST_AUDIO_FILE = None  # Path to test audio file
SKIP_SPEAKER_VERIFICATION = False  # For testing only
SKIP_WAKE_WORD_DETECTION = False  # For testing only

# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================
from dotenv import load_dotenv

load_dotenv()

# Override settings with environment variables if set
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", OLLAMA_API_URL)
LLM_MODEL = os.getenv("LLM_MODEL", LLM_MODEL)
STT_MODEL = os.getenv("STT_MODEL", STT_MODEL)
FLASK_DEBUG = os.getenv("FLASK_DEBUG", FLASK_DEBUG).lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", LOG_LEVEL)

# ============================================================================
# VALIDATION
# ============================================================================
def validate_config():
    """Validate configuration values"""
    errors = []
    
    if not 0 <= WAKE_WORD_THRESHOLD <= 1:
        errors.append("WAKE_WORD_THRESHOLD must be between 0 and 1")
    
    if not 0 <= SPEAKER_VERIFICATION_THRESHOLD <= 1:
        errors.append("SPEAKER_VERIFICATION_THRESHOLD must be between 0 and 1")
    
    if SESSION_TIMEOUT < 5:
        errors.append("SESSION_TIMEOUT should be at least 5 seconds")
    
    if STT_MODEL not in ["tiny", "base", "small", "medium", "large"]:
        errors.append("STT_MODEL must be: tiny, base, small, medium, or large")
    
    if not 0 <= LLM_TEMPERATURE <= 1:
        errors.append("LLM_TEMPERATURE must be between 0 and 1")
    
    if errors:
        raise ValueError("\n".join(errors))
    
    return True

# Validate on import
try:
    validate_config()
except ValueError as e:
    print(f"Configuration Error: {e}")
    raise