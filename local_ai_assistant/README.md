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

## Built-in local commands

These run instantly without the LLM:

- `scan apps` / `list apps` keeps the executable registry up to date.
- `open <app>` or `launch <app>` starts any indexed application.
- `close <app>` issues a Windows `taskkill` for the target process (falls back to `<name>.exe` if the app isn't indexed).
- `open folder <path>` opens a directory in Explorer.
- `open browser`, `open chrome`, `open notepad`, `take screenshot`, and `type: ...` provide quick PC controls.

Set `MERGE_COMMAND_RESPONSES=False` in `config.py` if you prefer instant local acknowledgements instead of routing the action summary back through the LLM.

## Notes

- Toggle `USE_STT`/`USE_TTS` in `config.py` to disable audio subsystems.
- Voice interrupts are enabled by default—say "stop" or "cancel" while TTS is speaking to cut it off (`ENABLE_VOICE_INTERRUPTS`).
- The interrupt listener keeps the microphone stream open at all times for near-zero latency; disable the feature entirely if you need to reclaim the input device.
- `data/memory.json` stores lightweight key/value context.
- Logs can optionally be written to `logs/assistant.log` via `utils/logger.py`.
