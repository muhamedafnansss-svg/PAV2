@echo off
title VAL — Local AI Operating System
color 0A

echo.
echo  ██╗   ██╗ █████╗ ██╗
echo  ██║   ██║██╔══██╗██║
echo  ██║   ██║███████║██║
echo  ╚██╗ ██╔╝██╔══██║██║
echo   ╚████╔╝ ██║  ██║███████╗
echo    ╚═══╝  ╚═╝  ╚═╝╚══════╝
echo.
echo  Virtual Autonomous Logic — v14.0
echo  Primary:  Qwen2.5-Coder-7B-Instruct
echo  Fallback: Mistral-7B-Instruct
echo  ─────────────────────────────────
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

:: Check if venv exists, use it if so
if exist "venv\Scripts\activate.bat" (
    echo  [OK] Using virtual environment...
    call venv\Scripts\activate.bat
)

:: Check FastAPI is installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo  [WARN] FastAPI not installed. Installing deps...
    pip install -r requirements.txt
)

:: GPU check
echo  [CHECK] Scanning hardware...
python -c "import torch; print(f'  [GPU] {torch.cuda.get_device_name(0)} ({torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB VRAM)') if torch.cuda.is_available() else print('  [CPU] No GPU detected — CPU mode')" 2>nul || echo  [WARN] PyTorch not installed

:: Check model weights
python -c "from pathlib import Path; qw=Path('models/qwen'); ms=Path('models/mistral'); print(f'  [MODEL] Qwen: {\"found\" if any(qw.glob(\"*.safetensors\")) or any(qw.glob(\"*.bin\")) else \"MISSING\"}') if qw.exists() else print('  [MODEL] Qwen: NOT FOUND'); print(f'  [MODEL] Mistral: {\"found\" if any(ms.glob(\"*.safetensors\")) or any(ms.glob(\"*.bin\")) else \"MISSING\"}') if ms.exists() else print('  [MODEL] Mistral: NOT FOUND')" 2>nul
echo.

:: Start backend
echo  [BOOT] Starting VAL API on http://127.0.0.1:8765
echo  [BOOT] UI:  Run 'npm run dev' in val-ui/ for the dashboard
echo  [BOOT] Docs: http://127.0.0.1:8765/docs
echo.

:: Allow override via args
set PORT=8765
if not "%1"=="" set PORT=%1

python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from val.api.server import start_api_server
start_api_server(host='127.0.0.1', port=%PORT%)
"
pause
