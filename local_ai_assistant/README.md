# Local AI Assistant

Offline-first voice assistant that runs entirely on Windows using local models:

- **Speech-to-Text** via Vosk + sounddevice
- **LLM** via Ollama (defaults to `llama3`)
- **Text-to-Speech** via Coqui TTS with pyttsx3 fallback

## Setup

1. Install system dependencies (Python 3.10+, Ollama, a Vosk acoustic model, microphone/headset drivers).
2. Download a Vosk model from <https://alphacephei.com/vosk/models> and extract it into `models/vosk_model/`.
3. (Optional) Pull an Ollama model: `ollama pull llama3`.

```powershell
cd local_ai_assistant
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

1. Ensure the Vosk model folder exists and Ollama is running.
2. Adjust `config.py` if you want different models/devices.
3. Start the assistant loop:

```powershell
python assistant.py
```

Press Enter to speak or type directly. Say "quit" or press `Ctrl+C` to exit.

## Notes

- Toggle `USE_STT`/`USE_TTS` in `config.py` to disable audio subsystems.
- `data/memory.json` stores lightweight key/value context.
- Logs can optionally be written to `logs/assistant.log` via `utils/logger.py`.
