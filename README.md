# Local AI PC Assistant

Offline-first voice assistant that runs entirely on Windows using locally hosted models for STT (Vosk), LLM (Ollama), and TTS (Coqui TTS with pyttsx3 fallback).

## Features

- Works without cloud services once dependencies are installed locally
- Streams Ollama responses while simultaneously feeding them to the TTS pipeline
- Optional speech input/output (toggle via `config.py`)
- Hands-free "stop talking" voice interrupts while TTS is speaking
- Lightweight key/value memory persisted to `data/memory.json`
- Windows-friendly launcher script (`run_assistant.bat`)

## Repository Layout

```
local_ai_assistant/
├── assistant.py          # main loop
├── config.py             # model + device configuration
├── modules/              # STT, TTS, LLM, memory helpers
├── utils/logger.py       # minimal logging helper
├── requirements.txt      # Python dependencies
└── README.md             # module-level usage notes
run_assistant.bat         # convenience launcher for the venv
```

## Prerequisites

- Windows 10/11
- Python 3.10+
- [Ollama](https://ollama.ai/) running locally with a pulled model (defaults to `llama3`)
- [Vosk acoustic model](https://alphacephei.com/vosk/models) extracted into `local_ai_assistant/models/vosk_model/`
- Microphone and speakers/headset with proper drivers (if using audio I/O)

## Quick Start

```powershell
# Clone and enter the repo
cd AI-PC-Assistant

# Create & activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install Python requirements
pip install -r local_ai_assistant\requirements.txt

# Launch (from repo root)
python local_ai_assistant\assistant.py
# or use the helper
run_assistant.bat
```

1. Download a Vosk model (e.g., `vosk-model-en-us-0.22`) and extract it to `local_ai_assistant/models/vosk_model/`.
2. Ensure Ollama is running and `ollama pull llama3` (or your preferred model).
3. Adjust any options in `local_ai_assistant/config.py` (STT/TTS toggles, device indexes, TTS voices).
4. Press Enter to trigger listening or type directly; say "quit" or press `Ctrl+C` to exit.

## Configuration Notes

- Set `USE_STT` or `USE_TTS` to `False` in `config.py` if you only want typing/console output.
- `COQUI_TTS_MODEL`, `COQUI_TTS_SPEAKER`, and `COQUI_TTS_LANGUAGE` map directly to [Coqui TTS](https://github.com/coqui-ai/TTS) model options.
- Voice interruptions are controlled by `ENABLE_VOICE_INTERRUPTS`, `VOICE_INTERRUPT_PHRASES`, and timing knobs in `config.py` (defaults stop playback when you say "stop"/"cancel").
- Memory is a simple JSON dict stored at `local_ai_assistant/data/memory.json` (ignored by git); delete the file to reset history.

## Ready for GitHub

- `.gitignore` excludes virtual environments, downloaded models, logs, and runtime artifacts.
- No large model files are tracked—users download their own Vosk/Ollama assets.
- All setup/run instructions live here and in `local_ai_assistant/README.md` for convenience.
- `run_assistant.bat` provides a turnkey launcher for contributor testing on Windows.

Feel free to open issues or pull requests once you add a license file that matches how you plan to share the project.
