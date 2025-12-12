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

## Hotword Detection & Tuning

The assistant uses **openWakeWord** for real offline keyword spotting (KWS) with adaptive noise gating and live diagnostics. This provides:

- **Lower latency**: Continuous keyword detection without full STT overhead
- **Higher accuracy**: Purpose-built models reduce false positives
- **Adaptive noise gate**: Automatically adjusts to ambient noise levels
- **Two-stage activation**: KWS trigger → Whisper confirmation for high confidence
- **Live diagnostics**: Real-time audio/score logging with Ctrl+Shift+Space toggle

### Quick Start: Tuning Your Detection

**Step 1: Enable Debug Mode**

While the assistant is running, press **Ctrl+Shift+Space** to toggle diagnostic logging. You'll see:
- `[AUDIO]` logs: RMS levels, noise floor, and why frames pass/block
- `[WAKE]` logs: Confidence scores for each wake word model

**Step 2: Start with Lower Threshold**

In `config.py`, set a lower threshold to ensure it triggers:

```python
HOTWORD_THRESHOLD = 0.50  # Lower than default 0.80
DEBUG_HOTWORD_AUDIO = True  # Enable by default (or toggle with Ctrl+Shift+Space)
```

Say the wake word and watch the logs. You should see scores spike above threshold.

**Step 3: Gradually Raise Threshold**

Once you confirm it triggers, gradually increase the threshold to reduce false positives:

```python
HOTWORD_THRESHOLD = 0.70  # Increase gradually: 0.50 → 0.70 → 0.80 → 0.85
```

Test each increment to find the sweet spot where it triggers reliably but not spuriously.

### Configuration

Key settings in `config.py`:

```python
# Engine selection
HOTWORD_ENGINE = "openwakeword"  # Use "legacy" for old Whisper-based detection

# Detection parameters
HOTWORD_KEYWORDS = ["hey jarvis"]  # Use actual pretrained models
HOTWORD_THRESHOLD = 0.80  # Confidence threshold (0.0-1.0)
HOTWORD_DEBOUNCE_FRAMES = 4  # Consecutive frames above threshold required
HOTWORD_COOLDOWN_S = 3.0  # Cooldown after confirmed wake

# Two-stage activation
HOTWORD_CONFIRM_WHISPER = True  # Use Whisper to confirm triggers
HOTWORD_CONFIRM_TIMEOUT_S = 2.5  # Max time for confirmation audio
HOTWORD_RECENT_WINDOW_S = 8.0  # Window blocking voice typing after wake

# Adaptive noise gate (automatically adjusts to ambient noise)
NOISE_GATE_ENABLED = True  # Enable adaptive noise gate
NOISE_GATE_RMS_MIN = 0.0015  # Minimum RMS threshold (float audio)
NOISE_GATE_MULTIPLIER = 2.5  # Gate = max(min, noise_floor * multiplier)

# VAD (Voice Activity Detection)
VAD_ENABLED = True  # Enable VAD (applies after noise gate)
VAD_AGGRESSIVENESS = 2  # 0-3, higher = more aggressive

# Debug logging (toggle live with Ctrl+Shift+Space)
DEBUG_HOTWORD_AUDIO = False  # Enable detailed audio/wake score logging

# Custom models (optional)
HOTWORD_MODEL_PATHS = []  # Add paths to custom .tflite/.onnx models
```

### Understanding the Adaptive Noise Gate

The noise gate automatically learns your ambient noise level:

1. **Noise Floor Tracking**: Maintains a rolling median of RMS values during non-speech
2. **Dynamic Threshold**: Gate threshold = `max(NOISE_GATE_RMS_MIN, noise_floor * NOISE_GATE_MULTIPLIER)`
3. **Speech Bypass**: If VAD detects speech, noise gate is bypassed to avoid blocking real speech

**Example logs with debug enabled:**

```
[AUDIO] rms=0.0012 noise_floor=0.0008 threshold=0.0020   # Quiet background
[AUDIO] Frame blocked by noise gate (rms=0.0012)          # Too quiet, blocked
[AUDIO] rms=0.0045 noise_floor=0.0008 threshold=0.0020   # Speaking!
[AUDIO] Frame passed (rms=0.0045)                         # Loud enough, passed
[WAKE] scores={'hey_jarvis': 0.23} max=0.230 threshold=0.800  # Not wake word
[WAKE] scores={'hey_jarvis': 0.87} max=0.870 threshold=0.800  # Detected!
```

### Testing & Tuning

**Option 1: Test Script (Standalone)**

```powershell
python local_ai_assistant\scripts\test_hotword.py
```

Shows live scores, VAD decisions, state transitions, and statistics.

**Option 2: Live Diagnostic Mode (In Assistant)**

1. Start the assistant: `python local_ai_assistant\assistant.py`
2. Press **Ctrl+Shift+Space** to enable diagnostic logging
3. Say the wake word and watch the logs
4. Press **Ctrl+Shift+Space** again to disable

**Tuning Matrix:**

| Symptom | Solution |
|---------|----------|
| Too many false positives | Increase `HOTWORD_THRESHOLD` (0.80 → 0.85) |
| Missing real triggers | Lower `HOTWORD_THRESHOLD` (0.80 → 0.70) |
| Triggers in noisy room | Increase `NOISE_GATE_MULTIPLIER` (2.5 → 3.5) |
| Blocks your voice | Lower `NOISE_GATE_MULTIPLIER` (2.5 → 2.0) or increase `VAD_AGGRESSIVENESS` |
| Repeated triggers | Increase `HOTWORD_COOLDOWN_S` (3.0 → 5.0) |
| Intermittent triggers | Increase `HOTWORD_DEBOUNCE_FRAMES` (4 → 6) |
| Noise gate too sensitive | Adjust `NOISE_GATE_RMS_MIN` (0.0015 → 0.001 for quiet, → 0.003 for loud) |

### Pretrained Models Available

Use these actual openWakeWord models (no placeholder mapping):

```python
HOTWORD_KEYWORDS = ["hey jarvis"]   # Recommended: works well
HOTWORD_KEYWORDS = ["alexa"]        # Amazon's wake word
HOTWORD_KEYWORDS = ["hey mycroft"]  # Mycroft AI wake word
HOTWORD_KEYWORDS = ["hey rhasspy"]  # Rhasspy wake word
```

Or load multiple: `HOTWORD_KEYWORDS = ["hey jarvis", "alexa"]`

### Custom "Wyzer" Model

To train a custom model for exact "wyzer" matching:

1. Collect wake word samples (your voice saying "wyzer")
2. Train using [openWakeWord training tools](https://github.com/dscripka/openWakeWord)
3. Save the `.tflite` or `.onnx` file to `local_ai_assistant/models/hotword/`
4. Update config:
   ```python
   HOTWORD_MODEL_PATHS = ["models/hotword/wyzer.tflite"]
   HOTWORD_KEYWORDS = []  # Empty to use only custom models
   ```

### Voice Typing Protection

The state machine automatically blocks voice typing when:
- State is `LISTENING_QUERY` or `PROCESSING` (query in progress)
- Wake was confirmed within `HOTWORD_RECENT_WINDOW_S` (default 8 seconds)

This prevents voice typing from stealing commands intended for the assistant.

## Voice Typing / Dictation Mode

- Flip `ENABLE_VOICE_TYPING = True` in `local_ai_assistant/config.py` to allow transcripts to be typed into whichever window currently has focus (uses `pyautogui`).
- Say "start typing" or "start typing mode" after the hotword to enable dictation, and "stop typing" or "stop typing mode" to turn it off.
- While dictation is enabled, every recognized utterance is sent to the foreground app; say "new line" for Enter, "backspace" to delete the last character, and "stop typing" to exit the mode.
- Use this feature carefully—the assistant cannot tell which window you intend to target and will blindly type into the active application.

### Voice Navigation Commands

Regardless of whether dictation mode is currently on, you can steer the cursor hands-free with these phrases (case/wording is flexible; partial matches are accepted):

- `press enter/new line/newline/line break`
- `press tab` / `press shift tab`
- `press escape`, `press space`, `press space bar`
- `press backspace/delete last/undo last`, `press delete`
- `press up/down/left/right (arrow)`
- `press control c/v/x/a`, `go to the top/bottom`, `select all`
- `undo` (`ctrl+z`), `redo` (`ctrl+y`), `press alt tab`

> ⚠️ **Safety**: Voice typing sends hotkeys to *whatever* app currently has focus—even if you haven’t explicitly enabled dictation—so make sure the intended window is active before issuing navigation commands.

## Ready for GitHub

- `.gitignore` excludes virtual environments, downloaded models, logs, and runtime artifacts.
- No large model files are tracked—users download their own Vosk/Ollama assets.
- All setup/run instructions live here and in `local_ai_assistant/README.md` for convenience.
- `run_assistant.bat` provides a turnkey launcher for contributor testing on Windows.

Feel free to open issues or pull requests once you add a license file that matches how you plan to share the project.
