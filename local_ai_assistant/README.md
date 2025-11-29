# Local AI Assistant

Offline-first console assistant that runs entirely on Windows using a locally hosted Ollama model. Audio input/output and GUI shells have been removed—everything happens inside the terminal for faster, simpler workflows.

## Setup

1. Install Python 3.10+ and [Ollama](https://ollama.ai/) on Windows.
2. (Optional) Pull your preferred Ollama model, e.g. `ollama pull llama3`.
3. Create a virtual environment and install dependencies:

```powershell
cd local_ai_assistant
python -m venv .venv
\.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

1. Ensure Ollama is running.
2. Adjust `config.py` if you want to change the default model or tool behavior.
3. Start the assistant loop:

```powershell
python assistant.py
```

Type requests directly into the console and press ENTER. Type `quit` (or press `Ctrl+C`) to exit.

## Orchestrator + tool calling

- `assistant.orchestrator.Orchestrator` owns every LLM turn, including JSON tool-calling through the Ollama HTTP API.
- Tool definitions live in `tools/tools_manifest.json`. Each entry specifies the module, function name, and JSON schema so the model can call it safely.
- If your Ollama build does not yet support chat tool-calling, set `ENABLE_LLM_TOOLS = False` in `config.py`; the orchestrator will automatically fall back to plain chat completions.
- To add a capability:
	1. Implement a Python function (usually under `modules/`).
	2. Append a manifest entry with the tool name, module path, callable, description, and parameter schema.
	3. Restart `assistant.py` so the orchestrator reloads the manifest.

The orchestrator streams text chunks straight to the terminal, so responses start appearing immediately even for longer answers.

### Window / app control tool

- `modules/window_control.py` exposes `handle_window_control(action, target_app=None, monitor=None)` for focus/minimize/maximize/restore/move.
- The manifest entry `window_control` receives actions like `"switch"`, `"bring_up"`, `"minimize"`, `"move"`, etc.
- Window aliases (`APP_ALIASES`) and `APP_LAUNCH_MAP` help map natural language requests to running apps or launch commands.
- For multi-monitor setups, pass action `"move"` (or `"move_to_monitor"`) plus a monitor hint like `"left"`, `"right"`, or `"monitor 2"`.

### Typing automation tool

- `modules/voice_typing.py` exposes `control_voice_typing(action, text=None)` so the LLM can toggle dictation mode or issue keystrokes via pyautogui when the user asks it to "type this" or "press Ctrl+C".
- The `voice_typing_control` manifest entry accepts actions `enable`, `disable`, `toggle`, `status`, or `type`; provide `text` only for the `type` action.
- Results include whether typing mode is enabled plus metadata such as backend readiness or characters typed so the model can confirm what happened.

### Xbox Game Bar capture tool

- `modules/gamebar_recorder.py` drives the Windows shortcut keys (`Win+Alt+G` / `Win+Alt+R`) so the assistant can save recent gameplay or toggle an ongoing recording.
- The manifest entry `gamebar_capture` exposes the action list `record_last_30_seconds`, `record_that`, `start_recording`, `stop_recording`, and `toggle_recording`.
- Game Bar shortcuts require Windows and that background recording is already enabled in the Xbox app settings.

## Built-in local commands

These run instantly without the LLM:

- `scan apps` / `list apps` refreshes the executable registry.
- `open <app>` or `launch <app>` starts any indexed application.
- `close <app>` issues a Windows `taskkill` for the target process (falls back to `<name>.exe` if the app isn't indexed).
- `open folder <path>` opens a directory in Explorer.
- `open browser`, `open chrome`, `open notepad`, `take screenshot`, and `type: ...` provide quick PC controls.
- `record that`, `start recording this`, and `stop recording` forward to Xbox Game Bar hotkeys for highlight capture.

Set `MERGE_COMMAND_RESPONSES=False` in `config.py` if you prefer instant local acknowledgements instead of routing the action summary back through the LLM.

## Notes

- The assistant is text-only; no microphones, hotwords, or TTS pipelines are required.
- `ENABLE_VOICE_TYPING` governs whether the `voice_typing_control` tool is available for keystroke automation.
- `data/memory.json` stores lightweight key/value context. Delete it to reset history.
- Logs can optionally be written to `logs/assistant.log` via `utils/logger.py`.
