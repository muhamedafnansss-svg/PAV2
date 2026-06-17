# Setup Instructions for Genos

## Installation

```bash
git clone https://github.com/muhamedafnansss-svg/PAV2.git
cd PAV2
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running Genos

### Step 1: Start Ollama
```bash
ollama serve
```

### Step 2: Pull models (optional)
```bash
ollama pull llama2
ollama pull mistral
ollama pull qwen
```

### Step 3: Run Genos
```bash
python main.py
```

Visit `http://localhost:5000` in your browser.

## Supported Models
- llama2 (7b, 13b)
- mistral
- qwen (7b)
- neural-chat
- dolphin-mistral
- starling-lm
- vicuna

## Configuration

Edit `config.py` to customize settings.
