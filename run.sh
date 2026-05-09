#!/usr/bin/env bash
# VAL — Virtual Autonomous Logic (Linux launcher)

set -e

echo ""
echo "  ██╗   ██╗ █████╗ ██╗"
echo "  ██║   ██║██╔══██╗██║"
echo "  ██║   ██║███████║██║"
echo "  ╚██╗ ██╔╝██╔══██║██║"
echo "   ╚████╔╝ ██║  ██║███████╗"
echo "    ╚═══╝  ╚═╝  ╚═╝╚══════╝"
echo ""
echo "  Virtual Autonomous Logic — v9.0"
echo "  Model: Qwen2.5-Coder-7B-Instruct"
echo "  ─────────────────────────────────"
echo ""

# Navigate to script directory
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python3 not found. Install Python 3.10+ first."
    exit 1
fi

# Activate venv if it exists
if [ -f "venv/bin/activate" ]; then
    echo "  [OK] Using virtual environment..."
    source venv/bin/activate
fi

# Check FastAPI
python3 -c "import fastapi" 2>/dev/null || {
    echo "  [WARN] FastAPI not installed. Installing deps..."
    pip install -r requirements.txt
}

# Start backend
PORT=${1:-8765}
echo "  [BOOT] Starting VAL API on http://127.0.0.1:${PORT}"
echo "  [BOOT] UI:  Run 'npm run dev' in val-ui/ for the dashboard"
echo "  [BOOT] Docs: http://127.0.0.1:${PORT}/docs"
echo ""

python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())
from val.api.server import start_api_server
start_api_server(host='127.0.0.1', port=${PORT})
"
