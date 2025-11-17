"""Simple hotword detection built on the existing Vosk STT stack."""
from __future__ import annotations

import time
from difflib import SequenceMatcher

import config
from utils.logger import log

from . import stt_vosk

_HOTWORD = config.HOTWORD.lower().strip()


def _fuzzy_match(text: str, target: str, threshold: float = 0.75) -> bool:
    """Check if text fuzzy-matches target using similarity ratio."""
    text = text.lower().strip()
    target = target.lower().strip()
    
    # Exact match
    if target in text:
        return True
    
    # Check similarity ratio
    ratio = SequenceMatcher(None, text, target).ratio()
    if ratio >= threshold:
        log(f"Fuzzy match: '{text}' ~= '{target}' (similarity: {ratio:.2f})")
        return True
    
    # Check if words in target appear in text (word-by-word)
    target_words = target.split()
    text_words = text.split()
    
    # Try to find all target words in the transcribed text
    for target_word in target_words:
        found = False
        for text_word in text_words:
            word_ratio = SequenceMatcher(None, text_word, target_word).ratio()
            if word_ratio >= 0.7:  # Per-word threshold
                found = True
                break
        if not found:
            return False
    
    log(f"Word-by-word match: '{text}' matches '{target}'")
    return True


def _ensure_recognizer_ready() -> bool:
    recognizer = getattr(stt_vosk, "_RECOGNIZER", None)
    if recognizer is not None:
        return True
    try:
        stt_vosk.init_recognizer()
        return True
    except Exception as exc:  # pragma: no cover - hardware specific
        log(f"Unable to load Vosk recognizer for hotword detection: {exc}")
        return False


def listen_for_hotword(timeout_seconds: float | None = None) -> bool:
    """Block until the configured hotword is detected or timeout expires."""
    if not config.USE_STT:
        log("Hotword detection skipped because STT is disabled in config.")
        return False
    if not _HOTWORD:
        log("Hotword phrase not configured.")
        return False
    if not _ensure_recognizer_ready():
        return False

    timeout = timeout_seconds if timeout_seconds is not None else config.HOTWORD_TIMEOUT_SECONDS
    deadline = time.time() + timeout if timeout else None

    log(f"Listening for hotword '{config.HOTWORD}'...")
    while True:
        if deadline and time.time() > deadline:
            log("Hotword listen timed out.")
            return False
        # Listen in short bursts so the user can just say the wake-phrase.
        transcript = stt_vosk.listen_once(timeout_seconds=3.0)
        if transcript:
            log(f"Heard: '{transcript}'")
            if _fuzzy_match(transcript, _HOTWORD, threshold=0.65):
                log("Hotword detected.")
                return True
        # Slight pause to avoid hammering the CPU when no audio is coming in.
        time.sleep(0.1)
