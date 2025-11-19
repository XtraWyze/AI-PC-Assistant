"""Centralized configuration for the local AI assistant.

Everything intentionally stays local/offline. Update the values below to point at
your preferred models, devices, and runtime defaults.
"""

# ---------------------------------------------------------------------------
# Identity & behavior toggles
# ---------------------------------------------------------------------------
ASSISTANT_NAME = "Wyzer"  # Display name + how the assistant introduces itself.
MODE = "voice"  # "voice" for hotword+STT loop, "text" for console input.
ENABLE_HOTWORD = True  # Disable to fall back to push-to-talk for voice mode.
HOTWORD = "hey wyzer"  # Phrase the hotword detector should listen for.
HOTWORD_TIMEOUT_SECONDS = 45.0  # Stop waiting for a wake word after this many seconds (None = unlimited).
HOTWORD_ALIASES = ["wyzer"]  # Additional phrases treated as wake words.
HOTWORD_HIDDEN_ALIASES = ["wiser", "hey wiser"]  # Extra wake phrases kept out of console logs.
ENABLE_PUSH_TO_TALK = False  # Optional fallback while hotword is disabled/unavailable.
PUSH_TO_TALK_PROMPT = "Press ENTER and speak..."  # Shown in console for text fallback prompting.
ENABLE_COMMANDS = True  # Route built-in PC-control commands locally instead of sending to the LLM.
MERGE_COMMAND_RESPONSES = False  # Keep local command replies short by skipping the LLM follow-up.
MAX_CONTEXT_TURNS = 6  # How many historical turns (user+assistant pairs) feed into the LLM prompt.
SYSTEM_PREAMBLE = (
    "You are a helpful, privacy-preserving local assistant called Wyzer. "
    "You run entirely offline and never make network requests."
)

# ---------------------------------------------------------------------------
# LLM backend (Ollama) configuration
# ---------------------------------------------------------------------------
LLM_MODEL = "llama3.1:latest"  # Name of an Ollama model that is already pulled locally.
OLLAMA_HOST = "http://localhost:11434"  # Where the Ollama daemon is listening.
ENABLE_LLM_TOOLS = True  # Flip to False if your Ollama build doesn't support chat tool-calling yet.

# ---------------------------------------------------------------------------
# Speech subsystems (still optional if you want text-only usage)
# ---------------------------------------------------------------------------
USE_TTS = True  # Enable Text-To-Speech responses.
USE_STT = True  # Enable speech recognition via Whisper.
STT_ENGINE = "whisper"  # Future-proof selector in case alternative engines are added.
WHISPER_MODEL = "small"  # Options include "tiny", "base", "small", "medium", "large-v2", etc.
WHISPER_DEVICE = "auto"  # "auto" picks CUDA when available, else CPU.
WHISPER_COMPUTE_TYPE = "auto"  # "auto" => float16 on GPU, int8 on CPU for speed.
WHISPER_BEAM_SIZE = 5  # Trade-off between accuracy and latency.
WHISPER_LANGUAGE = "en"  # ISO language hint or None to auto-detect.
MAX_LISTEN_SECONDS = 10.0  # How long to listen after the user starts speaking.

# Audio device overrides. Leave as None to allow sounddevice to auto-select defaults.
VOICE_DEVICE_INDEX = None  # Playback device index for TTS audio.
MIC_DEVICE_INDEX = None  # Recording device index for STT input.

# Voice interruption (say "stop" to cut off TTS playback)
ENABLE_VOICE_INTERRUPTS = True  # Requires USE_STT plus Vosk assets.
VOICE_INTERRUPT_PHRASES = [
    "stop",
    "cancel",
    "nevermind",
    "pause",
    "quiet",
]

# ---------------------------------------------------------------------------
# TTS fine-tuning (Coqui preferred with pyttsx3 fallback)
# ---------------------------------------------------------------------------
TTS_VOICE = "en_US"  # Used primarily by pyttsx3 backends.
COQUI_TTS_MODEL = "tts_models/en/jenny/jenny"
COQUI_TTS_SPEAKER = None  # Example: "p269" for multi-speaker models.
COQUI_TTS_LANGUAGE = "en"

# ---------------------------------------------------------------------------
# Local PC control / automation commands
# ---------------------------------------------------------------------------
COMMAND_BROWSER_HOME = "https://github.com"  # Homepage opened for browser-related commands.
SCREENSHOT_DIR = "screenshots"  # Relative folder (under repo root) for saved screenshots.

# ---------------------------------------------------------------------------
# Memory persistence
# ---------------------------------------------------------------------------
MEMORY_FILE = "data/memory.json"  # Overridable path for the JSON memory store.
MAX_HISTORY_ENTRIES = 100  # Prevent unbounded growth of on-disk history.
