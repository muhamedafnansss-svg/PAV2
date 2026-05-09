<p align="center">
  <br>
  <code style="font-size:48px">◈</code>
  <br><br>
  <strong style="font-size:32px">V A L</strong>
  <br>
  <em>Virtual Autonomous Logic</em>
  <br><br>
  <code>v14.1.0</code> · Hybrid CPU+GPU Local AI Operating System
  <br><br>

  ![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?style=flat-square&logo=fastapi&logoColor=white)
  ![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)
  ![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)
  ![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)
  ![CUDA](https://img.shields.io/badge/CUDA-12.x-76B900?style=flat-square&logo=nvidia&logoColor=white)
  ![License](https://img.shields.io/badge/License-Private-333333?style=flat-square)

</p>

---

## What is VAL?

**VAL** is a production-grade, privacy-first AI operating system with **hybrid CPU+GPU acceleration** running entirely on your local machine. It combines an intelligent conversational assistant, a Linux-style operator console, a code engineer, a cybersecurity toolkit, an autonomous ReAct agent, a firewall builder, and a knowledge retrieval system — all powered by local LLMs with zero cloud dependencies.

---

## Key Features

| Capability | Description |
|---|---|
| **🧠 AI Operator Console** | Unified chat + terminal. Ask or execute — VAL routes intelligently |
| **⚡ Hybrid CPU+GPU** | GPU: inference, attention, decoding. CPU: tokenization, routing, I/O |
| **🚀 Dual-Backend Engine** | llama.cpp (GGUF) for <200ms ultra-fast inference + HuggingFace fallback |
| **🤖 ReAct Agent** | Autonomous Multi-step task orchestrator for complex task decomposition |
| **🔍 Code Analyzer** | AST-based vulnerability scanner (13 patterns) + import chain validation |
| **🧹 Project Cleanup** | Duplicate detection + temp/cache scanner with protected-path safety |
| **📚 Wikipedia + RAG** | Knowledge retrieval with optional FAISS semantic search |
| **🧬 Repo Intelligence** | Clone, index, and semantically search GitHub repositories |
| **🏷️ Entity Extraction** | Auto-detects IPs, domains, CVEs, ports, processes from chat |
| **🛡️ Firewall Builder** | NL→netsh/ufw/iptables rule generation + hardened profiles |
| **🔒 Security Modes** | SAFE / POWER / LAB with command allowlists |
| **🔍 Cyber Tools** | nmap, hashcat, gobuster, sqlmap, nikto, subfinder, ffuf, amass |
| **📊 SOC Dashboard** | Log analysis, threat detection, IOC extraction, risk scoring |
| **🌐 OSINT Engine** | WHOIS, DNS, header analysis, tech fingerprinting |

---

## Performance

### v14.1 Live Benchmarks (measured on Qwen 2.5 Coder 7B, CUDA)

| Request Type | Latency | Notes |
|-------------|:-------:|-------|
| Health check | **57ms** | API status |
| Greeting ("hello") | **4ms** | Fast-path, no LLM |
| Cached repeat | **2ms** | LRU response cache hit |
| Short answer ("2+2") | **185ms** | ~4 tokens via llama.cpp GGUF |
| Code gen ("hello world") | **250ms** | ~8 tokens via llama.cpp GGUF |
| Knowledge query | **850ms** | ~40 tokens via llama.cpp GGUF |

### Key Optimizations Applied

| Layer | Optimization | Impact |
|-------|-------------|--------|
| **Attention** | SDPA (PyTorch native) | Fixed FlashAttention2 crash on Windows |
| **Warmup** | CUDA pipeline primed at startup | Eliminates cold-start lag |
| **Matmul** | TF32 + cuDNN benchmark | 30-50% faster on Ampere+ GPUs |
| **Quantization** | 4-bit NF4 + double quant | 5GB VRAM for 7B model |
| **Streaming** | `stream_sync()` direct call | Eliminated 30s double-queue bug |
| **Cache** | 4-layer hierarchical caching system | <5ms for repeated queries |
| **Tokens** | Aggressive adaptive budget | Shorter = faster |
| **Priority** | ABOVE_NORMAL process priority | OS prioritizes inference |
| **GPU** | 90% VRAM cap, 92% utilization target | Maximum GPU usage |
| **CPU** | 75% threads + interop pool | Parallel tokenization + I/O |

---

## Hybrid CPU+GPU Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    VAL v14.1 — Hybrid Acceleration                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─── CPU WORKLOADS ──────────────┐  ┌─── GPU WORKLOADS ────────┐ │
│   │ ● 3-tier intent routing (Fast/SOC/Offensive)       │  │ ● Model inference        │ │
│   │ ● Tokenization (parallel)      │  │ ● SDPA attention         │ │
│   │ ● Prompt building              │  │ ● KV cache               │ │
│   │ ● Request queuing              │  │ ● Token decoding         │ │
│   │ ● File I/O + tool execution    │  │ ● Embedding ops          │ │
│   │ ● SSE streaming                │  │ ● 4-bit dequantization   │ │
│   │ ● Postprocessing               │  │ ● TF32 matmul            │ │
│   │ ● RAM/CPU monitoring           │  │ ● cuDNN benchmarked ops  │ │
│   └────────────────────────────────┘  └──────────────────────────┘ │
│                                                                     │
│   ┌──────────────┐    SSE Stream    ┌────────────────────────────┐ │
│   │   val-ui      │ ◄────────────► │   FastAPI Server v14.1     │ │
│   │   React 19    │    REST API     │   23 endpoints             │ │
│   │   Vite 8      │                │   Rate-limited (60/m)      │ │
│   └──────────────┘                 └─────────────┬──────────────┘ │
│                                                   │                 │
│                  ┌─────────────────────────────────┤                 │
│                  │       Router v14.1               │                 │
│                  │  Fast Path, Mistral/SOC, Qwen/Offensive  │                 │
│                  └─────────────────────────────────┘                 │
│                                                                     │
│   ┌────────┐ ┌─────┐ ┌────┐ ┌───┐ ┌────┐ ┌──────┐ ┌──────────┐   │
│   │Governor│ │Term.│ │Wiki│ │SOC│ │Code│ │React │ │Firewall  │   │
│   │(LLM)  │ │Exec │ │+RAG│ │   │ │Scan│ │Agent │ │Builder   │   │
│   └───┬────┘ └─────┘ └────┘ └───┘ └────┘ └──────┘ └──────────┘   │
│       │                                                             │
│  ┌────┴──────────┐        ┌────────────┐                           │
│  │  VRAM (90%)   │        │  RAM Guard  │                           │
│  │ ┌───────────┐ │        │  Pressure   │                           │
│  │ │ Qwen 2.5  │ │        │  Tiers +    │                           │
│  │ │ Coder 7B  │ │        │  Auto GC    │                           │
│  │ ├───────────┤ │        └────────────┘                           │
│  │ │ Mistral   │ │                                                  │
│  │ │ 7B Inst.  │ │                                                  │
│  │ └───────────┘ │                                                  │
│  └───────────────┘                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend
| Component | Technology |
|---|---|
| API Server | FastAPI + Uvicorn (23 endpoints) |
| Event Bus | Asynchronous event bus for sub-800ms SOC automation |
| LLM Inference | llama.cpp (GGUF, primary) + PyTorch/Transformers (fallback) |
| Attention | SDPA (PyTorch native, Windows-compatible) |
| CUDA Opts | TF32 matmul, cuDNN benchmark, CUDA warmup |
| Model Manager | Governor v14 (single-slot, SDPA, warmup, 90% VRAM) |
| Intent Routing | Router v14.1 — High-performance 3-tier routing engine (Fast Path, Mistral/SOC, Qwen/Offensive) |
| Entity Extraction | IP / domain / CVE / port / process regex extraction |
| Code Analysis | AST-based Python auditor + 13 vulnerability patterns |
| Firewall Builder | NL→netsh/ufw/iptables + hardened profile generator |
| ReAct Agent | Multi-step task orchestrator for complex task decomposition |
| Security | Sandbox, allowlists, rate limiting, AST calculator |

### Frontend
| Component | Technology |
|---|---|
| Framework | React 19 + Vite 8 |
| State | Zustand |
| Animations | Framer Motion |
| Design | Glassmorphism cyber theme |

### Models (Local)
| Model | Role | VRAM (4-bit) |
|---|---|---|
| **Qwen 2.5 Coder 7B** | Code generation, analysis, reasoning | ~5 GB |
| **Mistral 7B Instruct** | Chat, recon, threat intel, research | ~7 GB |
| TinyLlama 1.1B | Emergency fallback under RAM pressure | ~1.5 GB |

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **NVIDIA GPU with 8+ GB VRAM** (recommended) or CPU
- **Windows 10/11** or **Linux**
- **CUDA 12.x** (for GPU acceleration)

### 1. Setup

```bash
git clone <repo-url> PAV2
cd PAV2
python -m venv venv
venv\Scripts\activate        # Windows

# Install PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install dependencies
pip install -r requirements.txt
```

### 2. Download Models

```bash
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct --local-dir models/qwen
huggingface-cli download mistralai/Mistral-7B-Instruct-v0.3 --local-dir models/mistral
```

### 3. Start

```bash
# Backend (Terminal 1)
.\run.bat
# or: python -c "from val.api.server import start_api_server; start_api_server()"

# Frontend (Terminal 2)
cd val-ui && npm install && npm run dev
```

- Backend: `http://127.0.0.1:8765` (docs at `/docs`)
- Frontend: `http://localhost:3000`

---

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `VAL_API_PORT` | `8765` | API port |
| `VAL_DEFAULT_MODEL` | `mistral` | Model loaded at startup |
| `VAL_DEVICE` | `auto` | Force `cuda` or `cpu` |
| `VAL_MAX_MEMORY_GB` | `14.2` | Hard RAM ceiling |
| `GPU_USAGE_TARGET` | `0.92` | Target GPU utilization |
| `CPU_USAGE_TARGET` | `0.75` | CPU thread allocation |
| `LOW_RAM_MODE` | `true` | Aggressive memory optimization |
| `QWEN_4BIT` | `true` | Enable 4-bit quantization |

### GPU Optimization Settings

| Setting | Recommended | Effect |
|---|---|---|
| VRAM cap | 90% | Max GPU memory usage |
| Attention | SDPA | PyTorch native, 2-3× faster |
| TF32 | Enabled | Faster matmul on Ampere+ |
| cuDNN benchmark | Enabled | Auto-tuned convolutions |
| CUDA warmup | Enabled | Primes GPU pipeline at load |
| Process priority | ABOVE_NORMAL | OS prioritizes inference |

---

## Security

1. **CORS** — Locked to localhost only
2. **Rate Limiting** — 60 req/min per IP
3. **Command Allowlists** — SAFE / POWER / LAB modes
4. **Destructive Op Blocking** — `rm -rf /`, `format C:` hard-blocked
5. **AST Calculator** — No `eval()`
6. **Sandboxed Tools** — Path traversal protection
7. **Code Analyzer** — 13 vulnerability patterns
8. **Protected Paths** — Cleanup never deletes source/config/git
9. **Firewall Builder** — Explains rules before applying

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `flash-attn` won't install on Windows | Expected — VAL uses SDPA (PyTorch native, same speed) |
| Slow first response | Model loading. Wait for `[Governor] CUDA warmup complete` in logs |
| High RAM usage | Set `LOW_RAM_MODE=true` in `.env` |
| VRAM OOM | Reduce `VAL_MAX_MEMORY_GB` or use TinyLlama fallback |
| `npm error ENOENT` | Run npm from `val-ui/` directory, not root |
| GPU not detected | Install CUDA toolkit + matching PyTorch build |

---

## Roadmap

### Achieved <200ms Latency
VAL v14.1 has successfully implemented a **dual-backend architecture** to achieve sub-200ms inference times:
- **llama.cpp + GGUF (Primary):** Executes inference at 15-30ms/token via C++, bypassing Python overhead.
- **HuggingFace + SDPA (Fallback):** Seamlessly loads PyTorch models when GGUF files are unavailable.
- **Adaptive Budgets:** Automatically calculates optimal token generation limits based on prompt complexity.

### Planned Features

- [ ] Multi-GPU (tensor parallel) support
- [ ] Persistent vector memory (ChromaDB)
- [ ] WebSocket streaming (replace SSE)
- [ ] Plugin system for custom tools
- [ ] Mobile-responsive UI
- [x] llama.cpp / GGUF backend for 3-5× inference speed
- [x] WSL Kali Linux tool routing (17 tools)
- [x] 4-layer hierarchical caching system
- [x] SDPA attention + eager fallback
- [x] Firewall builder (NL to netsh/ufw/iptables)

---

## License

This project is private and not licensed for redistribution.

---

<p align="center">
  <br>
  <strong>◈ VAL v14.1</strong>
  <br>
  <em>Virtual Autonomous Logic — Hybrid CPU+GPU Local AI Operating System</em>
  <br>
  <code>SDPA · TF32 · NF4 · Qwen 2.5 · Mistral 7B · FastAPI · React 19</code>
  <br><br>
</p>
