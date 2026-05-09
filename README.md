<![CDATA[<div align="center">

```
██╗   ██╗ █████╗ ██╗
██║   ██║██╔══██╗██║
██║   ██║███████║██║
╚██╗ ██╔╝██╔══██║██║
 ╚████╔╝ ██║  ██║███████╗
  ╚═══╝  ╚═╝  ╚═╝╚══════╝
```

**Virtual Autonomous Logic — v15.0**
*JARVIS-Class Local AI Operating System*

Voice-first · Owner-authenticated · Sub-second inference · Fully offline

</div>

---

## Overview

VAL is a **production-grade, local-first AI platform** that runs entirely on your machine — no cloud, no API keys, no data leaving your hardware. It combines a multi-model inference engine, full-duplex voice pipeline, persistent memory, cybersecurity tooling, and a cinematic React dashboard into a unified system that behaves like a private JARVIS.

### Core Capabilities

| Domain | Features |
|--------|----------|
| **Voice** | Faster-Whisper STT, Piper TTS, wake words ("Hey VAL", "Jarvis", "Commander"), voiceprint auth, 4 voice modes |
| **Inference** | 3-tier routing (Qwen 7B + Mistral 7B + TinyLLaMA), 4-bit quantization, dual backend (HF + llama.cpp) |
| **Security** | SOC log triage, OSINT recon, firewall builder, sandboxed execution, SAFE/POWER/LAB modes |
| **Tools** | Terminal, code analysis, repo intel, power tools (nmap/hashcat/sqlmap), system control |
| **Memory** | 3-layer conversation memory + SQLite persistent memory + auto fact extraction |
| **Agents** | Multi-agent framework (VALCoreAgent, TaskAgent, BackgroundAgent) with ReAct loop |
| **UI** | React 19 dashboard with floating voice orb, telemetry HUD, SSE streaming |

---

## Architecture

```
PAV2/
├── val/                        # Python backend
│   ├── core/                   # Execution engine
│   │   ├── engine.py           # Kernel — async execution pipeline
│   │   ├── orchestrator.py     # Multi-step task decomposition
│   │   ├── planner.py          # Intent → execution plan mapping
│   │   ├── cache.py            # 4-layer cache (L1 routing → L4 vector)
│   │   ├── event_bus.py        # Async pub/sub event system
│   │   └── scheduler.py        # Background task scheduler
│   │
│   ├── models/                 # Model management
│   │   ├── governor.py         # Dual-backend model loader (HF + llama.cpp)
│   │   ├── router.py           # 3-tier intent router with 20+ intents
│   │   └── llama_backend.py    # llama.cpp / GGUF inference backend
│   │
│   ├── voice/                  # JARVIS voice pipeline
│   │   ├── voice_bridge.py     # Orchestrator: Wake→Auth→STT→Kernel→TTS
│   │   ├── stt_engine.py       # Faster-Whisper STT with VAD
│   │   ├── tts_engine.py       # Piper TTS with voice modes
│   │   ├── voice_auth.py       # Speaker verification (resemblyzer)
│   │   ├── wake_word.py        # Wake word detection
│   │   └── persona.py          # JARVIS response rewriting
│   │
│   ├── agents/                 # Agent framework
│   │   └── agent.py            # VALCoreAgent + TaskAgent + BackgroundAgent
│   │
│   ├── api/                    # REST API
│   │   └── server.py           # FastAPI server (40+ endpoints)
│   │
│   ├── tools/                  # Tool registry
│   │   ├── executor.py         # Safe tool execution with sandbox
│   │   ├── terminal.py         # Shell command runner
│   │   ├── analyzer.py         # Code analysis engine
│   │   ├── firewall.py         # iptables/nftables rule builder
│   │   ├── power_tools.py      # nmap, hashcat, sqlmap wrappers
│   │   ├── repo_intel.py       # Git repo intelligence
│   │   ├── cleanup.py          # Project cleanup utility
│   │   ├── wiki.py             # Wikipedia search
│   │   └── system_control.py   # OS control (apps, volume, clipboard)
│   │
│   ├── security/               # Security layer
│   │   ├── sandbox.py          # Tool sandbox with path/command restrictions
│   │   ├── scope.py            # Trust boundary enforcement
│   │   ├── audit.py            # Audit logging with tamper detection
│   │   └── rate_limiter.py     # Per-IP rate limiting
│   │
│   ├── soc/                    # Security Operations Center
│   │   ├── soc_engine.py       # Log analysis + threat detection
│   │   └── enrichment.py       # IOC enrichment + context
│   │
│   ├── osint/                  # OSINT module
│   │   └── osint_engine.py     # Domain/IP/URL reconnaissance
│   │
│   ├── state/                  # Memory & state
│   │   ├── memory.py           # 3-layer conversation memory
│   │   ├── persistent_memory.py# SQLite persistent memory (4 domains)
│   │   ├── memory_extractor.py # Auto fact extraction from conversations
│   │   └── store.py            # Key-value state store
│   │
│   ├── config/                 # Configuration
│   │   └── settings.py         # Typed dataclass config (VoiceConfig, etc.)
│   │
│   ├── cli/                    # CLI interface
│   │   └── interface.py        # Interactive terminal UI
│   │
│   └── utils/                  # Utilities
│       ├── logger.py           # Structured JSONL logging
│       ├── watchdog.py         # System health monitor
│       ├── ram_guard.py        # RAM ceiling enforcement
│       ├── memory_budget.py    # VRAM budget allocator
│       └── memory_monitor.py   # Real-time memory tracking
│
├── val-ui/                     # React frontend
│   └── src/
│       ├── App.jsx             # Root shell + routing
│       ├── api/client.js       # API client (40+ functions)
│       ├── store/index.js      # Zustand state management
│       ├── components/
│       │   ├── Sidebar.jsx     # Navigation sidebar
│       │   ├── SystemPanel.jsx # System status panel
│       │   ├── VoiceOrb.jsx    # Floating JARVIS voice orb + overlay
│       │   ├── TelemetryHUD.jsx# CPU/RAM/GPU gauges overlay
│       │   ├── ChatMessage.jsx # Message renderer with markdown
│       │   └── Header.jsx      # Top bar
│       └── pages/
│           ├── Chat.jsx        # Main console
│           ├── SOC.jsx         # SOC analysis dashboard
│           ├── OSINT.jsx       # OSINT reconnaissance
│           ├── Tools.jsx       # Tool execution
│           ├── Agents.jsx      # Agent management
│           ├── Models.jsx      # Model switching
│           ├── Memory.jsx      # Memory viewer
│           ├── Workspace.jsx   # File workspace
│           ├── Settings.jsx    # System settings
│           ├── DualPanel.jsx   # Red/Blue team split view
│           ├── RedTeamPanel.jsx# Offensive operations
│           └── BlueTeamPanel.jsx# Defensive operations
│
├── models/                     # Model weights (not committed)
│   ├── qwen/                   # Qwen2.5-Coder-7B-Instruct
│   └── mistral/                # Mistral-7B-Instruct-v0.3
│
├── tests/
│   └── test_val.py             # Comprehensive test suite
│
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Pytest config
├── run.bat                     # Windows launcher
├── run.sh                      # Linux/Mac launcher
├── .env.example                # Environment template
└── .env                        # Local config (not committed)
```

---

## Routing Engine

Every user input flows through a **3-tier routing system** that decides whether to use tools, a fast model, or a heavy model:

| Tier | Model | Token Cap | Use Case |
|------|-------|-----------|----------|
| **Tier 0** | None | 0 | Greetings, mode switches, tool calls — no LLM needed |
| **Tier 1** | Mistral 7B | 64 | SOC triage, security analysis, defensive ops |
| **Tier 2** | Qwen 7B | 256 | Code generation, reasoning, offensive ops |

### Intent Categories (20+)

```
GREETING · SWITCH · MODE_SET · SYSTEM_CMD · POWER_TOOL · CODING · RECON
SECURITY · RESEARCH · REASONING · CHAT · FILE_OP · AGENT · ANALYZE
CLEANUP · KNOWLEDGE · REPO_INTEL · FIREWALL · SOC_TRIAGE · EXPLOIT_GEN
PAYLOAD_CRAFT · OPEN_APP · CLOSE_APP · VOLUME · CLIPBOARD · FILE_SEARCH
VOICE_MODE · VOICE_AUTH · SYS_CONTROL
```

---

## Voice Pipeline (JARVIS Mode)

Full-duplex voice assistant with state machine:

```
IDLE → WAKE_DETECTED → AUTHENTICATING → LISTENING → TRANSCRIBING → PROCESSING → SPEAKING → IDLE
```

| Component | Technology | Latency |
|-----------|-----------|---------|
| **STT** | Faster-Whisper (CTranslate2) + Silero VAD | ~200ms |
| **TTS** | Piper (CPU, male voice) / pyttsx3 fallback | ~150ms |
| **Auth** | resemblyzer d-vector embeddings (cosine > 0.82) | ~100ms |
| **Wake** | Keyword spotting on short transcription windows | ~50ms |

### Voice Modes

| Mode | Behavior |
|------|----------|
| **Formal** | Calm, articulate, full sentences — default JARVIS style |
| **Tactical** | Clipped, fast, military precision |
| **Friendly** | Warmer, casual tone |
| **Silent** | Text-only, no audio output |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Space` | Push-to-talk (anywhere in UI) |
| `Alt+V` | Toggle voice overlay |
| Double-click orb | Expand full-screen voice mode |

---

## Memory System

### Layer 1 — Short-term (Conversation)
- Last 10 turns kept in memory
- Auto-cleared between sessions
- Injected into every LLM prompt

### Layer 2 — Working State
- Tracks active model, security mode, tool results
- Zustand store on frontend, dict on backend

### Layer 3 — Persistent (SQLite)
- 4 domains: `personal`, `project`, `security`, `context`
- Auto fact extraction from conversations
- WAL mode for concurrent reads
- Path: `val/state/store/memory.db`

---

## Security Modes

| Mode | Terminal | Network | Tools | Description |
|------|----------|---------|-------|-------------|
| **SAFE** | Allowlisted only | Blocked | Read-only | Default — locked down |
| **POWER** | Most commands | Limited | Full | Operator mode |
| **LAB** | Unrestricted | Open | All + offensive | Pentesting / research |

### Security Infrastructure

- **Sandbox** — Path traversal prevention, command allowlisting, signed tool loading
- **Scope** — Trust boundary enforcement per session
- **Audit** — Tamper-resistant JSONL logging
- **Rate Limiter** — 60 req/min per IP
- **Voice Auth** — Speaker verification with anti-replay (energy variance analysis)

---

## API Endpoints

Backend runs on `http://127.0.0.1:8765` (FastAPI + Uvicorn).

### Core
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Full system status |
| POST | `/chat` | SSE streaming chat |
| POST | `/query` | Non-streaming chat |
| POST | `/mode` | Set security mode (SAFE/POWER/LAB) |

### Voice
| Method | Path | Description |
|--------|------|-------------|
| GET | `/voice/status` | Voice pipeline status |
| POST | `/voice/transcribe` | Upload audio → text |
| POST | `/voice/speak` | Text → speech |
| POST | `/voice/interrupt` | Stop current speech |
| POST | `/voice/mode` | Set voice mode |
| POST | `/voice/enroll` | Enroll owner voiceprint |
| GET | `/voice/auth/status` | Auth status |

### Models
| Method | Path | Description |
|--------|------|-------------|
| GET | `/models/status` | Model info |
| POST | `/models/select` | Switch active model |
| POST | `/models/load` | Load model weights |
| POST | `/models/unload` | Unload from VRAM |

### Tools & Security
| Method | Path | Description |
|--------|------|-------------|
| POST | `/terminal` | Execute shell command |
| POST | `/soc/scan` | SOC log analysis |
| POST | `/soc/analyze` | Threat analysis |
| POST | `/osint/gather` | OSINT reconnaissance |
| POST | `/firewall` | Firewall rule generation |
| POST | `/system/control` | OS control (open apps, volume, etc.) |
| POST | `/agent/run` | Run agent task |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/memory` | View conversation memory |
| POST | `/memory/reset` | Clear session memory |
| GET | `/logs/{category}` | Read log files |
| GET | `/orchestrator/status` | Task orchestrator status |

---

## Installation

### Prerequisites
- **Python** 3.10+
- **Node.js** 18+ (for the dashboard)
- **CUDA** 12.1+ (recommended) or CPU-only mode
- **8 GB+ RAM** minimum, 16 GB recommended
- **GPU** with 6 GB+ VRAM for 4-bit models (optional)

### Step 1 — Clone & Setup

```bash
git clone https://github.com/muhamedafnansss-svg/PAV2.git
cd PAV2

# Create virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Copy environment config
copy .env.example .env      # Windows
cp .env.example .env        # Linux/Mac
```

### Step 2 — Install PyTorch

```bash
# GPU (CUDA 12.1) — recommended
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# GPU (CUDA 12.4+)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# CPU only (slower inference)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Download Model Weights

```bash
# Qwen 7B (primary — code + reasoning)
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct --local-dir models/qwen

# Mistral 7B (SOC + security analysis)
huggingface-cli download mistralai/Mistral-7B-Instruct-v0.3 --local-dir models/mistral
```

### Step 5 — Install Voice Dependencies (Optional)

```bash
# STT — Faster-Whisper
pip install faster-whisper

# TTS — Piper (download voice model separately)
pip install piper-tts

# Speaker verification
pip install resemblyzer

# Audio I/O
pip install sounddevice soundfile
```

### Step 6 — Setup Dashboard

```bash
cd val-ui
npm install
cd ..
```

---

## Running

### Quick Start (Windows)

```bash
run.bat
```

### Manual Start

```bash
# Terminal 1 — Backend
python -c "from val.api.server import start_api_server; start_api_server()"

# Terminal 2 — Frontend
cd val-ui
npm run dev
```

- **Backend**: http://127.0.0.1:8765
- **Dashboard**: http://localhost:3000
- **API Docs**: http://127.0.0.1:8765/docs

---

## Configuration

All configuration via `.env` file. Key settings:

```env
# Device: cuda | cpu | auto
VAL_DEVICE=cuda

# Default model: tinyllama | mistral | qwen
VAL_DEFAULT_MODEL=tinyllama

# Security mode at startup
SAFE_MODE=false
POWER_MODE=true

# Voice settings
VAL_STT_MODEL=base          # tiny|base|small|medium|large
VAL_VOICE_MODE=formal       # formal|tactical|friendly|silent
VAL_ALWAYS_LISTEN=false     # true = always-on mic

# Memory
VAL_MEMORY_DB=val/state/store/memory.db
VAL_MEMORY_ENCRYPT=false

# Server
VAL_API_HOST=127.0.0.1
VAL_API_PORT=8765
```

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.10+ |
| API | FastAPI + Uvicorn |
| Inference | PyTorch + Transformers + bitsandbytes (4-bit NF4) |
| Fallback | llama.cpp via llama-cpp-python (GGUF) |
| STT | Faster-Whisper (CTranslate2) |
| TTS | Piper / pyttsx3 |
| Voice Auth | resemblyzer (d-vector) |
| Memory | SQLite (WAL mode) |
| OSINT | python-whois + dnspython |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | React 19 + Vite 8 |
| State | Zustand 4 |
| Animations | Framer Motion 11 |
| Routing | React Router 6 |
| Styling | Vanilla CSS (dark theme, glassmorphism) |

---

## Testing

```bash
# Unit tests (no GPU required)
pytest tests/ -v --tb=short

# Integration tests (requires model weights + GPU)
pytest tests/ -v -m integration
```

---

## Project Stats

| Metric | Value |
|--------|-------|
| Backend modules | 14 packages, 40+ Python files |
| Frontend components | 6 components, 13 pages |
| API endpoints | 40+ |
| Total codebase | ~25,000 lines |
| Router intents | 28 |
| Voice modes | 4 |
| Security modes | 3 |
| Memory layers | 3 |
| Cache layers | 4 |

---

## License

Private project. All rights reserved.

---

<div align="center">
<sub>VAL v15.0 · JARVIS-Class AI Platform · Built for private, local-first operation</sub>
</div>
]]>
