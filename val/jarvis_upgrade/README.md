# VAL to Jarvis Upgrade Pack

This upgrade pack contains modular additions to transform your VAL v14.0 installation into a fully functional Jarvis assistant capable of interactive voice communication, safe system automation, blue teaming, and educational routines.

## Installation

1. **Install new dependencies:**
   You will need to install the packages required by these new modules. Make sure your virtual environment is active.
   ```bash
   pip install faster-whisper pyttsx3 sounddevice numpy
   ```
   *(Note: Depending on your OS, you may need to install `portaudio` for `sounddevice` to work. On Ubuntu: `sudo apt-get install libportaudio2`)*

2. **Integrate Modules into VAL:**
   Copy the python files in this folder into your existing `val/tools` or `val/core` directories.

## Overview of Modules

### 1. Voice Module (`voice_assistant.py`)
- **What it does:** Provides completely local Speech-to-Text (using `faster-whisper`) and Text-to-Speech (using `pyttsx3`).
- **How to use it:** Initialize `JarvisVoiceModule` in your main VAL loop. Call `start_listening()` when a hotkey is pressed, and `stop_listening_and_transcribe()` when released. Pass the transcribed text into the VAL API, and use `.speak()` on the text response.

### 2. Safe System Executor (`safe_executor.py`)
- **What it does:** Allows the AI to run system commands to automate daily tasks, while strictly blocking dangerous commands (like `rm -rf`).
- **How to use it:** Register this as a new tool in the ReAct agent tool list (`val/tools/`). When the AI decides it needs to run a system command, it can use this tool safely.

### 3. Blue Team Toolkit (`blue_team_tools.py`)
- **What it does:** Provides purely defensive tools for auditing and securing your system (firewall builder, rapid local port scanner, local log analyzer).
- **How to use it:** Register these methods as tools for the ReAct agent, specifically when you are operating in "Blue Team" mode.

### 4. Learning Engine (`learning_engine.py`)
- **What it does:** Indexes local study materials (e.g., AI/ML textbooks) and provides standard prompts for generating quizzes and summaries.
- **How to use it:** Tie this into a daily cron job or scheduler within VAL so that upon startup, Jarvis greets you and provides a daily learning summary or quiz.

## Important Note on "Red Teaming"

As an AI, I am committed to safety and ethical usage. The tools provided here are strictly for defensive auditing (Blue Teaming), system management, and education. Automated offensive exploitation (Red Teaming) is not supported by these modules to ensure system stability and prevent unintended harm.
