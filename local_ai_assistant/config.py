"""Centralized configuration for the local AI assistant.
Update the values below to point at your preferred models and devices.
"""

# Name of the Ollama model to run. Change this to any local model you have pulled.
LLM_MODEL = "llama3"

# Where your Ollama daemon is listening. Stay on localhost to keep things offline.
OLLAMA_HOST = "http://localhost:11434"

# Feature toggles for optional subsystems.
USE_TTS = True
USE_STT = True

# Filesystem paths for local models. Place your downloaded Vosk model under this folder.
VOSK_MODEL_PATH = "models/vosk_model"

# Audio device overrides. Leave as None to let the libraries auto-select defaults.
VOICE_DEVICE_INDEX = None
MIC_DEVICE_INDEX = None

# Timeout controls for listening / speaking operations.
MAX_LISTEN_SECONDS = 10.0
TTS_VOICE = "en_US"  # Depends on the TTS backend in use.

# Coqui TTS options. Set COQUI_TTS_SPEAKER for multi-speaker models, or
# change COQUI_TTS_MODEL to a single-speaker variant such as "tts_models/en/jenny/jenny".
COQUI_TTS_MODEL = "tts_models/en/jenny/jenny"
COQUI_TTS_SPEAKER = None  # Example: "p269" for VCTK voices.
COQUI_TTS_LANGUAGE = "en"
