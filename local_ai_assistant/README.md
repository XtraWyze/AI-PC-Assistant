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

## Orchestrator + tool calling

- `assistant.orchestrator.Orchestrator` now owns every LLM turn, including JSON tool-calling via the Ollama HTTP API.
- Tool definitions live in `tools/tools_manifest.json`. Each entry specifies the module, function name, and JSON schema so the model can call it safely.
- If your local Ollama build does not yet support chat tool-calling, set `ENABLE_LLM_TOOLS = False` in `config.py`; the orchestrator will automatically skip the `tools` payload and fall back to plain chat completions.
- To add a new capability:
	1. Implement a Python function (typically under `modules/`) that exposes the functionality you need.
	2. Append a new object to `tools/tools_manifest.json` with the tool name, description, module path, callable name, and parameter schema.
	3. Restart `assistant.py` so the orchestrator reloads the manifest.

The orchestrator automatically handles routing, executing tools, and feeding tool responses back into the LLM, so the main loop stays lean.

### Window / app control tool

- `modules/window_control.py` exposes `handle_window_control(action, target_app=None, monitor=None)` for focus/minimize/maximize/restore/move.
- The manifest entry is named `window_control`; the LLM calls it with actions like `"switch"`, `"bring_up"`, `"minimize"`, `"move"`, etc.
- Spoken app names are normalized using `APP_ALIASES`, and the module can fall back to launching an app via `APP_LAUNCH_MAP` when no window is found.
- To move windows between monitors, pass action `"move"` (or `"move_to_monitor"`) plus a `monitor` hint (e.g., `"left"`, `"right"`, `"primary"`, or `"monitor 2"`). The module keeps window size reasonable for the new display.
- Extend the alias, launch map, or monitor hint handling to cover additional setups.

### Voice typing control tool

- `modules/voice_typing.py` now exposes `control_voice_typing(action, text=None)` so the LLM can enable/disable dictation, check status, or inject keystrokes on demand.
- The manifest entry `voice_typing_control` accepts `action` values `enable`, `disable`, `toggle`, `status`, or `type`; provide `text` only when action is `type`.
- Results include whether typing mode is currently enabled plus metadata such as backend readiness or the number of characters typed, giving the model clear feedback.

### Xbox Game Bar capture tool

- `modules/gamebar_recorder.py` drives the Windows shortcut keys (`Win+Alt+G` / `Win+Alt+R`) so the assistant can save recent gameplay or toggle an ongoing recording.
- The manifest entry `gamebar_capture` exposes the action list `record_last_30_seconds`, `record_that`, `start_recording`, `stop_recording`, and `toggle_recording`.
- Game Bar shortcuts require Windows and that background recording is already enabled in the Xbox app settings.

## Built-in local commands

These run instantly without the LLM:

- `scan apps` / `list apps` keeps the executable registry up to date.
- `open <app>` or `launch <app>` starts any indexed application.
- `close <app>` issues a Windows `taskkill` for the target process (falls back to `<name>.exe` if the app isn't indexed).
- `open folder <path>` opens a directory in Explorer.
- `open browser`, `open chrome`, `open notepad`, `take screenshot`, and `type: ...` provide quick PC controls.
- `record that`, `start recording this`, and `stop recording` forward to Xbox Game Bar hotkeys so you can capture highlights hands-free.

Set `MERGE_COMMAND_RESPONSES=False` in `config.py` if you prefer instant local acknowledgements instead of routing the action summary back through the LLM.

## Notes

- Toggle `USE_STT`/`USE_TTS` in `config.py` to disable audio subsystems.
- Voice interrupts are enabled by default—say "stop" or "cancel" while TTS is speaking to cut it off (`ENABLE_VOICE_INTERRUPTS`).
- The interrupt listener keeps the microphone stream open at all times for near-zero latency; disable the feature entirely if you need to reclaim the input device.
- `data/memory.json` stores lightweight key/value context.
- Logs can optionally be written to `logs/assistant.log` via `utils/logger.py`.
