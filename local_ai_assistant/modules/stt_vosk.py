"""Compatibility shim: This module re-exports stt_whisper.py.

DEPRECATED: This file is misnamed (Vosk is a different STT engine).
Use stt_whisper.py directly for new code. This shim maintains backwards
compatibility for existing imports.
"""
from __future__ import annotations

import warnings

# Log deprecation warning once
_deprecation_logged = False
if not _deprecation_logged:
    warnings.warn(
        "stt_vosk.py is deprecated and misnamed. This module actually uses Whisper (faster-whisper), "
        "not Vosk. Please update imports to use 'stt_whisper' instead. "
        "This compatibility shim will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )
    _deprecation_logged = True

# Re-export everything from stt_whisper
from .stt_whisper import (
    WhisperSTTEngine,
    VoiceInterruptDetector,
    init_recognizer,
    listen_once,
    listen_follow_up,
    listen_for_interrupt,
    create_interrupt_recognizer,
    transcribe_pcm16,
    _has_repetition_spam,
    _SAMPLERATE,
    _SILENCE_TIMEOUT,
    _ENGINE,
    _RECOGNIZER,
)

__all__ = [
    "WhisperSTTEngine",
    "VoiceInterruptDetector",
    "init_recognizer",
    "listen_once",
    "listen_follow_up",
    "listen_for_interrupt",
    "create_interrupt_recognizer",
    "transcribe_pcm16",
    "_has_repetition_spam",
]

