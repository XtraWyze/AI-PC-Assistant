"""Text-to-speech utilities with Coqui TTS preferred and pyttsx3 fallback."""
from __future__ import annotations

from typing import Any, Optional, Tuple

import sounddevice as sd

import config
from utils.logger import log

try:  # pragma: no cover - optional dependency
    from TTS.api import TTS as CoquiTTS
except ImportError:  # pragma: no cover - optional dependency
    CoquiTTS = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import pyttsx3
except ImportError:  # pragma: no cover - optional dependency
    pyttsx3 = None  # type: ignore[assignment]

_COQUI_ENGINE: Any = None
_COQUI_SPEAKER: Optional[str] = None
_COQUI_LANGUAGES: Optional[list[str]] = None
_LANGUAGE_WARNING_EMITTED = False
_PYTTSX_ENGINE: Any = None
_stop_playback = False  # Flag to interrupt audio playback


def init_tts() -> None:
    """Initialize whichever TTS backend is available."""
    global _COQUI_ENGINE, _COQUI_SPEAKER, _COQUI_LANGUAGES, _PYTTSX_ENGINE

    if config.VOICE_DEVICE_INDEX is not None:
        sd.default.device = (None, config.VOICE_DEVICE_INDEX)

    if CoquiTTS is not None:
        try:
            model_name = getattr(config, "COQUI_TTS_MODEL", "tts_models/en/jenny/jenny")
            _COQUI_ENGINE = CoquiTTS(model_name=model_name)
            available_speakers = getattr(_COQUI_ENGINE, "speakers", None)
            available_languages = getattr(_COQUI_ENGINE, "languages", None)
            requested_speaker = getattr(config, "COQUI_TTS_SPEAKER", None)

            if available_speakers:
                if requested_speaker and requested_speaker not in available_speakers:
                    log(
                        "Requested speaker '%s' not available for %s. Falling back to %s."
                        % (requested_speaker, model_name, available_speakers[0])
                    )
                    requested_speaker = available_speakers[0]
                if requested_speaker is None:
                    requested_speaker = available_speakers[0]
                    log(
                        "No speaker specified for multi-speaker model. Defaulting to '%s'. Other options: %s"
                        % (requested_speaker, ", ".join(available_speakers[:8]))
                    )

            _COQUI_SPEAKER = requested_speaker
            _COQUI_LANGUAGES = list(available_languages) if available_languages else None
            if getattr(config, "COQUI_TTS_LANGUAGE", None):
                _maybe_warn_language(getattr(config, "COQUI_TTS_LANGUAGE"))
            log(f"Coqui TTS model loaded ({model_name}).")
            return
        except Exception as exc:  # pragma: no cover - optional dependency
            log(f"Coqui TTS initialization failed: {exc}")
            _COQUI_ENGINE = None

    if pyttsx3 is None:
        raise RuntimeError("pyttsx3 is required when Coqui TTS is unavailable. Install pyttsx3 and retry.")

    _PYTTSX_ENGINE = pyttsx3.init()
    _PYTTSX_ENGINE.setProperty("rate", 190)
    log("pyttsx3 fallback initialized. Adjust rate/voice in modules/tts_engine.py as needed.")


def speak(text: str) -> None:
    """Speak text synchronously using the initialized backend."""
    if not text:
        return

    if _COQUI_ENGINE is not None:
        audio, sample_rate = synthesize_audio(text)
        play_audio(audio, sample_rate)
        return

    if _PYTTSX_ENGINE is not None:
        _PYTTSX_ENGINE.say(text)
        _PYTTSX_ENGINE.runAndWait()
        return

    raise RuntimeError("TTS not initialized. Call init_tts() before speak().")


def supports_buffered_audio() -> bool:
    """Return True if we can pre-synthesize audio (Coqui available)."""
    return _COQUI_ENGINE is not None


def _build_tts_kwargs() -> dict:
    kwargs = {}
    language = getattr(config, "COQUI_TTS_LANGUAGE", None)
    if language:
        if _COQUI_LANGUAGES:
            if language in _COQUI_LANGUAGES:
                kwargs["language"] = language
            else:
                _maybe_warn_language(language)
        else:
            _maybe_warn_language(language)
    if _COQUI_SPEAKER:
        kwargs["speaker"] = _COQUI_SPEAKER
    return kwargs


def _maybe_warn_language(language: str) -> None:
    global _LANGUAGE_WARNING_EMITTED
    if _LANGUAGE_WARNING_EMITTED:
        return
    if _COQUI_LANGUAGES:
        log(
            "Configured language '%s' not supported by model. Available options: %s"
            % (language, ", ".join(_COQUI_LANGUAGES))
        )
    else:
        log("Language '%s' ignored because this model exposes a single built-in language." % language)
    _LANGUAGE_WARNING_EMITTED = True


def synthesize_audio(text: str) -> Tuple[Any, int]:
    """Return synthesized audio buffer and sample rate."""
    if _COQUI_ENGINE is None:
        raise RuntimeError("Coqui TTS is not initialized.")
    if not text:
        raise ValueError("Cannot synthesize empty text.")
    audio = _COQUI_ENGINE.tts(text, **_build_tts_kwargs())
    sample_rate = getattr(_COQUI_ENGINE.synthesizer, "output_sample_rate", 22_050)
    return audio, sample_rate


def play_audio(audio: Any, sample_rate: int) -> None:
    """Play a numpy audio buffer and wait for completion."""
    global _stop_playback
    _stop_playback = False
    sd.play(audio, samplerate=sample_rate)
    
    # Wait in short intervals so we can check stop flag
    import time
    while not _stop_playback:
        if not sd.get_stream().active:
            break
        time.sleep(0.05)  # Check every 50ms
    
    if _stop_playback:
        sd.stop()


def stop_audio() -> None:
    """Stop any currently playing audio."""
    global _stop_playback
    _stop_playback = True
    try:
        sd.stop()
    except Exception:
        pass
