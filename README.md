# Local AI PC Assistant

Offline-first console assistant that runs entirely on Windows using locally hosted Ollama models. The project previously included GUI shells and speech pipelines; it now focuses on a fast, text-first workflow that still keeps every request on-device.

## Features

- Streams Ollama responses directly to the terminal for low-latency feedback
- Local automation commands (launch apps, take screenshots, control audio, trigger Xbox Game Bar)
- Tool calling via the orchestrator for window management, web access, typing automation, etc.
- Lightweight key/value memory persisted to `data/memory.json`
- Windows-friendly launcher script (`run_assistant.bat`)

## Repository Layout

```
local_ai_assistant/
├── assistant.py          # main loop (text-only)
├── config.py             # LLM + behavior configuration
├── modules/              # tools, commands, memory helpers
├── utils/logger.py       # minimal logging helper
├── requirements.txt      # Python dependencies
└── README.md             # module-level usage notes
run_assistant.bat         # convenience launcher for the venv
```

## Prerequisites

- Windows 10/11
- Python 3.10+
- [Ollama](https://ollama.ai/) running locally with a pulled model (defaults to `llama3`)

## Quick Start

```powershell
# Clone and enter the repo
cd AI-PC-Assistant

# Create & activate a virtual environment
python -m venv .venv
\.\.venv\Scripts\activate

# Install Python requirements
pip install -r local_ai_assistant\requirements.txt

# Launch (from repo root)
python local_ai_assistant\assistant.py
# or use the helper
run_assistant.bat
```

1. Ensure Ollama is running and `ollama pull llama3` (or your preferred model).
2. Adjust any options in `local_ai_assistant/config.py` (model name, tool toggles, memory settings).
3. Type requests directly and press ENTER; type `quit` or press `Ctrl+C` to exit.

## Configuration Notes

- `ENABLE_COMMANDS` toggles the built-in local command parser inside `modules/commands_toolkit.py`.
- `MERGE_COMMAND_RESPONSES` controls whether local command results are merged back through the LLM for extra commentary.
- `ENABLE_VOICE_TYPING` controls whether the `voice_typing_control` tool is available for pyautogui-based typing automation.
- Memory is a simple JSON dict stored at `local_ai_assistant/data/memory.json`; delete the file to reset history.

## Typing Automation Tool

`modules/voice_typing.py` exposes `control_voice_typing(action, text=None)` so the assistant can:

- Enable/disable dictation mode when the user asks it to take over typing
- Send literal keystrokes (`type` action) into the currently active window
- Issue navigation hotkeys (Ctrl+C, Ctrl+V, Alt+Tab, arrow keys, etc.) through pyautogui

This tool is registered in `tools/tools_manifest.json` as `voice_typing_control`. Use it carefully—keystrokes always target the foreground application.

## Ready for GitHub

- `.gitignore` excludes virtual environments, downloaded data, logs, and runtime artifacts.
- All setup/run instructions live here and in `local_ai_assistant/README.md`.
- `run_assistant.bat` provides a turnkey launcher for contributor testing on Windows.

Feel free to open issues or pull requests once you add a license file that matches how you plan to share the project.
