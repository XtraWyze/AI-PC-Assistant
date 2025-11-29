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
HOTWORD_TIMEOUT_SECONDS = None  # Stop waiting for a wake word after this many seconds (None = unlimited).
HOTWORD_ALIASES = ["wyzer"]  # Additional phrases treated as wake words.
HOTWORD_HIDDEN_ALIASES = ["wiser", "hey wiser", "computer"]  # Extra wake phrases kept out of console logs.
HOTWORD_STREAMING = True  # Keep an always-on low-latency listener alive instead of polling in 3s chunks.
HOTWORD_STREAM_BLOCKSIZE = 2048  # Larger block sizes reduce CPU load; smaller values lower latency.
HOTWORD_IDLE_RESET_SECONDS = 0.9  # How fast the streaming buffer resets when no speech is present.
HOTWORD_PASSIVE_LISTEN_SECONDS = 1.6  # Window length for the legacy polling fallback.
HOTWORD_SILENCE_TIMEOUT = 0.45  # How quickly to stop recording after the hotword is spoken.
HOTWORD_MIN_PHRASE_SECONDS = 0.35  # Minimum audio capture length to pass to Whisper.
HOTWORD_MATCH_THRESHOLD = 0.62  # Lower values make fuzzy matching more permissive; raises recall at the cost of precision.
ENABLE_PUSH_TO_TALK = False  # Optional fallback while hotword is disabled/unavailable.
PUSH_TO_TALK_PROMPT = "Press ENTER and speak..."  # Shown in console for text fallback prompting.
ENABLE_COMMANDS = True  # Route built-in PC-control commands locally instead of sending to the LLM.
MERGE_COMMAND_RESPONSES = False  # Keep local command replies short by skipping the LLM follow-up.
MAX_CONTEXT_TURNS = 6  # How many historical turns (user+assistant pairs) feed into the LLM prompt.
SYSTEM_PREAMBLE = (
    "You are a helpful, privacy-preserving local assistant called Wyzer. "
    "You run locally on the user's PC and keep data on-device, but you can reach the public web through your dedicated tools when necessary. "
    "Default to concise answers (1-3 sentences) and only provide extra detail, lists, or external links when the user explicitly asks for them. "
    "You can call tools to access external capabilities. In particular, use:\n"
    "- search_web when the user needs up-to-date information or a general web search.\n"
    "- fetch_page when the user wants the content of a specific URL.\n"
    "- summarize_page when the user wants a short summary of a specific URL.\n"
    "Prefer these tools whenever a request obviously requires the internet. "
    "Call the window_control tool whenever the user wants to switch apps, bring an app forward, or change window state. "
    "Use action='focus', 'switch', or 'bring_up' plus a target_app when they name an application, and use 'minimize', 'maximize', or 'restore' for the current foreground window unless another app is specified. "
    "For moving windows between monitors, call window_control with action='move' (or 'move_to_monitor') and include a monitor hint such as 'left monitor', 'monitor 2', or 'primary'. "
    "When reporting window_control results, keep the acknowledgement extremely brief (<=8 words), no extra commentary/log output, just the outcome (e.g., 'Discord minimized.'). "
    "You can open websites on the user's computer using the open_website tool. "
    "When the user says things like 'open Facebook on Chrome', 'go to YouTube', or 'open Twitch in my browser', call open_website with a full https:// URL and optionally set browser='chrome' or 'default'. "
    "Examples: 'open facebook on chrome' -> open_website(url='https://www.facebook.com', browser='chrome'); 'go to youtube' -> open_website(url='https://www.youtube.com'). "
    "Use the 'open_path' tool whenever the user wants to open a folder, file, or specific filesystem path (e.g., 'open downloads folder', 'open my documents', 'open C:\\Users\\...'). "
    "Use the 'open_file_location' tool whenever the user explicitly asks for a file's location or says 'open file location of ...' so you open the folder that contains that file. "
    "You have access to advanced environment tools:\n"
    "- get_time_date(): retrieve the current local time/date.\n"
    "- get_location(): retrieve the user's general location using IP.\n"
    "- get_weather(lat, lon): current temperature, wind, humidity, and a short description.\n"
    "- get_sunrise_sunset(lat, lon): today's sunrise and sunset times.\n"
    "- get_forecast(lat, lon, days): short multi-day forecast with min/max temperature and summary.\n"
    "- get_air_quality(lat, lon): current AQI and pollutant levels.\n"
    "- get_environment_overview(lat, lon, days): combined view of current weather, sun info, forecast, air quality, and simple alerts.\n"
    "If the user asks about whether it's safe to go outside, if they need a jacket, sunrise or sunset, humidity or how it feels outside, air quality or breathing safety, or what the next few days' weather will be like, call the appropriate tools. "
    "Typically run get_location() first when coordinates are missing, then call the weather tool with those lat/lon values. "
    "Report temperatures in Fahrenheit by default (include Celsius only when specifically requested)."
)

# ---------------------------------------------------------------------------
# GUI preferences
# ---------------------------------------------------------------------------
SHOW_GUI_CONSOLE = False  # Hide the embedded CLI console inside wyzer_gui when False.

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
ENABLE_VOICE_TYPING = True  # Allow transcripts to be typed into the active window via pyautogui.
STT_ENGINE = "whisper"  # Future-proof selector in case alternative engines are added.
WHISPER_MODEL = "small"  # Options include "tiny", "base", "small", "medium", "large-v2", etc.
WHISPER_DEVICE = "auto"  # "auto" picks CUDA when available, else CPU.
WHISPER_COMPUTE_TYPE = "auto"  # "auto" => float16 on GPU, int8 on CPU for speed.
WHISPER_BEAM_SIZE = 5  # Trade-off between accuracy and latency.
WHISPER_LANGUAGE = "en"  # ISO language hint or None to auto-detect.
MAX_LISTEN_SECONDS = 10.0  # How long to listen after the user starts speaking.
FOLLOW_UP_WINDOW_SECONDS = 3.0  # After TTS playback, auto-listen this long for a follow-up before requiring a wake word.

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
