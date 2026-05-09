"""
VAL Configuration Management v15.0
=====================================
Centralized, validated configuration for the VAL JARVIS-class AI system.
Loads from .env, validates trust boundaries, and exposes typed config objects.
"""

import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# ─── Root Paths ──────────────────────────────────────────────────────────────
VAL_ROOT = Path(__file__).resolve().parent.parent
MODELS_ROOT = VAL_ROOT.parent / "models"
LOGS_DIR = VAL_ROOT / "logs"
STATE_DIR = VAL_ROOT / "state" / "store"
MEMORY_DIR = VAL_ROOT / "state" / "memdir"
CONFIG_DIR = VAL_ROOT / "config"

# Ensure critical directories exist
for _d in [LOGS_DIR, STATE_DIR, MEMORY_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─── Load .env ────────────────────────────────────────────────────────────────
_env_path = VAL_ROOT / ".env"
# override=True: .env always wins over stale shell/system env vars
load_dotenv(dotenv_path=_env_path, override=True)


@dataclass
class ModelConfig:
    """Typed configuration for a single local model."""
    name: str
    model_type: str
    model_path: Path
    max_new_tokens: int = 256           # Conservative default
    temperature: float = 0.7
    top_p: float = 0.9
    max_context_length: int = 1500      # Hard cap — matches engine MAX_CONTEXT
    device: str = "auto"
    load_in_4bit: bool = True           # 4-bit by default — saves ~60% VRAM
    load_in_8bit: bool = False
    enabled: bool = True

    def validate(self) -> None:
        """Assert model path exists and config is coherent."""
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"[VAL] Model '{self.name}' not found at: {self.model_path}"
            )
        if self.load_in_4bit and self.load_in_8bit:
            raise ValueError(
                f"[VAL] Model '{self.name}' cannot have both 4-bit and 8-bit quantization."
            )


@dataclass
class VoiceConfig:
    """Voice pipeline configuration."""
    stt_model_size: str = "base"            # tiny|base|small|medium|large
    stt_device: str = "auto"                 # auto|cpu|cuda
    stt_compute_type: str = "auto"           # auto|float16|int8
    tts_backend: str = "auto"                # auto|piper|pyttsx3
    voice_mode: str = "formal"               # formal|tactical|friendly|silent
    wake_phrases: list = field(default_factory=lambda: ["hey val", "jarvis", "commander"])
    speaker_threshold: float = 0.82          # cosine similarity for voiceprint
    lockout_duration_s: float = 30.0
    always_listen: bool = False              # True = always-on mic
    push_to_talk_key: str = "ctrl+space"


@dataclass
class MemoryPersistConfig:
    """Persistent memory configuration."""
    db_path: Path = field(default_factory=lambda: VAL_ROOT / "state" / "memory.db")
    encrypt: bool = False
    semantic_enabled: bool = False           # ChromaDB semantic memory
    extraction_enabled: bool = True          # Auto-extract facts from chat
    max_facts: int = 10000


@dataclass
class SecurityConfig:
    """Security policy settings."""
    allow_shell_execution: bool = False
    shell_allowlist: list = field(default_factory=list)
    allow_network_access: bool = False
    allow_file_write: bool = True
    file_write_basedir: Optional[Path] = None
    max_prompt_length: int = 8192
    rate_limit_per_minute: int = 60
    sandbox_mode: bool = True
    trusted_tool_dirs: list = field(default_factory=lambda: ["tools"])


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    log_dir: Path = LOGS_DIR
    enable_jsonl: bool = True
    categories: list = field(default_factory=lambda: [
        "system", "agent", "errors", "security", "inference"
    ])
    max_file_mb: int = 2         # 2 MB per log file (auto-trimmed)
    backup_count: int = 3        # Keep 3 backups only
    max_age_days: int = 3        # Auto-delete logs older than 3 days


@dataclass
class AppConfig:
    """Root application configuration."""
    val_version: str = "15.0.0"
    session_name: str = "val-session"
    interactive_mode: bool = True
    headless: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    default_model: str = "qwen"            # PRIMARY: Qwen 2.5 Coder 7B
    enable_telemetry: bool = False
    max_total_memory_gb: float = 10.0     # Hard ceiling: RAM + VRAM combined
    enable_background_agents: bool = False # DISABLED — saves RAM
    force_tinyllama: bool = False         # Disabled — Qwen is now primary
    disable_streaming: bool = False       # Set True to use generate() instead of stream()
    operator_mode: bool = True            # Operator mode: bypass tool allowlist
    cpu_usage_target: float = 0.75        # Target 75% CPU utilization
    gpu_usage_target: float = 0.80        # Target 80% GPU utilization
    low_ram_mode: bool = True             # Aggressive memory optimization
    models: Dict[str, ModelConfig] = field(default_factory=dict)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    memory_persist: MemoryPersistConfig = field(default_factory=MemoryPersistConfig)

    def get_model(self, name: str) -> ModelConfig:
        """Retrieve a model config by name, raising clearly if missing."""
        if name not in self.models:
            available = list(self.models.keys())
            raise KeyError(
                f"[VAL] Model '{name}' not configured. Available: {available}"
            )
        return self.models[name]


def _resolve_device() -> str:
    """Detect best available device."""
    device = os.getenv("VAL_DEVICE", "auto")
    return device


def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("1", "true", "yes")


def build_config() -> AppConfig:
    """
    Build the full AppConfig from environment variables and defaults.
    This is the single source of truth for all VAL configuration.
    """
    device = _resolve_device()

    mistral_cfg = ModelConfig(
        name="mistral",
        model_type="mistral",
        model_path=MODELS_ROOT / "mistral",
        max_new_tokens=int(os.getenv("MISTRAL_MAX_TOKENS", "512")),
        temperature=float(os.getenv("MISTRAL_TEMPERATURE", "0.7")),
        top_p=float(os.getenv("MISTRAL_TOP_P", "0.9")),
        max_context_length=int(os.getenv("MISTRAL_CONTEXT_LEN", "1500")),  # Capped
        device=device,
        load_in_4bit=_bool_env("MISTRAL_4BIT", True),    # 4-bit ON by default
        load_in_8bit=_bool_env("MISTRAL_8BIT", False),
        enabled=_bool_env("MISTRAL_ENABLED", True),
    )

    # Gemma removed in v15.0 — unused model

    tinyllama_cfg = ModelConfig(
        name="tinyllama",
        model_type="tinyllama",
        model_path=MODELS_ROOT / "tinyllama",
        max_new_tokens=int(os.getenv("TINYLLAMA_MAX_TOKENS", "256")),
        temperature=float(os.getenv("TINYLLAMA_TEMPERATURE", "0.6")),
        top_p=float(os.getenv("TINYLLAMA_TOP_P", "0.9")),
        max_context_length=int(os.getenv("TINYLLAMA_CONTEXT_LEN", "1500")),  # Capped
        device=device,
        load_in_4bit=_bool_env("TINYLLAMA_4BIT", True),  # 4-bit ON by default
        load_in_8bit=_bool_env("TINYLLAMA_8BIT", False),
        enabled=_bool_env("TINYLLAMA_ENABLED", True),
    )

    qwen_cfg = ModelConfig(
        name="qwen",
        model_type="qwen",
        model_path=MODELS_ROOT / "qwen",
        max_new_tokens=int(os.getenv("QWEN_MAX_TOKENS", "1024")),
        temperature=float(os.getenv("QWEN_TEMPERATURE", "0.7")),
        top_p=float(os.getenv("QWEN_TOP_P", "0.9")),
        max_context_length=int(os.getenv("QWEN_CONTEXT_LEN", "4096")),
        device=device,
        load_in_4bit=_bool_env("QWEN_4BIT", True),
        load_in_8bit=_bool_env("QWEN_8BIT", False),
        enabled=_bool_env("QWEN_ENABLED", True),
    )

    security_cfg = SecurityConfig(
        allow_shell_execution=_bool_env("VAL_ALLOW_SHELL", False),
        shell_allowlist=os.getenv("VAL_SHELL_ALLOWLIST", "").split(","),
        allow_network_access=_bool_env("VAL_ALLOW_NETWORK", False),
        allow_file_write=_bool_env("VAL_ALLOW_FILE_WRITE", True),
        file_write_basedir=Path(os.getenv("VAL_FILE_WRITE_DIR", str(VAL_ROOT))),
        max_prompt_length=int(os.getenv("VAL_MAX_PROMPT_LEN", "4096")),  # Reduced
        rate_limit_per_minute=int(os.getenv("VAL_RATE_LIMIT", "30")),   # Conservative
        sandbox_mode=_bool_env("VAL_SANDBOX", True),
    )

    log_cfg = LoggingConfig(
        level=os.getenv("VAL_LOG_LEVEL", "INFO"),
        log_dir=LOGS_DIR,
        enable_jsonl=_bool_env("VAL_LOG_JSONL", True),
        max_file_mb=int(os.getenv("VAL_LOG_MAX_MB", "2")),     # 2 MB max
        backup_count=int(os.getenv("VAL_LOG_BACKUPS", "3")),   # 3 backups
    )

    cfg = AppConfig(
        val_version=os.getenv("VAL_VERSION", "1.0.0"),
        session_name=os.getenv("VAL_SESSION", "val-session"),
        api_host=os.getenv("VAL_API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("VAL_API_PORT", "8765")),
        default_model=os.getenv("VAL_DEFAULT_MODEL", "qwen"),
        enable_telemetry=_bool_env("VAL_TELEMETRY", False),
        enable_background_agents=_bool_env("VAL_BACKGROUND_AGENTS", False),
        max_total_memory_gb=float(os.getenv("VAL_MAX_MEMORY_GB", "10.0")),
        force_tinyllama=_bool_env("VAL_FORCE_TINYLLAMA", False),    # default OFF -- Qwen is primary
        disable_streaming=_bool_env("VAL_DISABLE_STREAMING", False),
        models={
            "qwen": qwen_cfg,
            "mistral": mistral_cfg,
            "tinyllama": tinyllama_cfg,
        },
        security=security_cfg,
        logging=log_cfg,
        voice=VoiceConfig(
            stt_model_size=os.getenv("VAL_STT_MODEL", "base"),
            stt_device=os.getenv("VAL_STT_DEVICE", "auto"),
            voice_mode=os.getenv("VAL_VOICE_MODE", "formal"),
            always_listen=_bool_env("VAL_ALWAYS_LISTEN", False),
        ),
        memory_persist=MemoryPersistConfig(
            db_path=Path(os.getenv("VAL_MEMORY_DB", str(STATE_DIR / "memory.db"))),
            encrypt=_bool_env("VAL_MEMORY_ENCRYPT", False),
            semantic_enabled=_bool_env("VAL_SEMANTIC_MEMORY", False),
        ),
    )

    return cfg


# ─── Singleton Config Instance ────────────────────────────────────────────────
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Return the singleton AppConfig, building it if needed."""
    global _config
    if _config is None:
        _config = build_config()
    return _config


def validate_config(cfg: AppConfig) -> None:
    """
    Validate the full config. Called at startup.
    Raises on any critical misconfiguration.
    """
    errors = []
    for model_name, model_cfg in cfg.models.items():
        if model_cfg.enabled:
            try:
                model_cfg.validate()
            except (FileNotFoundError, ValueError) as e:
                errors.append(str(e))

    if errors:
        msg = "\n".join(errors)
        raise RuntimeError(f"[VAL] Configuration validation failed:\n{msg}")
