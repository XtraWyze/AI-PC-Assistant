"""Simple hotword detection built on the existing Vosk STT stack."""
from __future__ import annotations

import threading
import time
from difflib import SequenceMatcher
from typing import Optional

import config
from utils.logger import log as default_logger

from . import stt_vosk


def _fuzzy_match(text: str, target: str, logger=default_logger, threshold: float = 0.75) -> bool:
    """Check if text fuzzy-matches target using similarity ratio."""
    text = text.lower().strip()
    target = target.lower().strip()

    if not text:
        return False

    if target in text:
        return True

    ratio = SequenceMatcher(None, text, target).ratio()
    if ratio >= threshold:
        logger(f"Fuzzy match: '{text}' ~= '{target}' ({ratio:.2f})")
        return True

    target_words = target.split()
    text_words = text.split()

    for target_word in target_words:
        found = False
        for text_word in text_words:
            word_ratio = SequenceMatcher(None, text_word, target_word).ratio()
            if word_ratio >= 0.7:
                found = True
                break
        if not found:
            return False

    logger(f"Word-by-word match: '{text}' matched '{target}'")
    return True


def _ensure_recognizer_ready(logger=default_logger) -> bool:
    recognizer = getattr(stt_vosk, "_RECOGNIZER", None)
    if recognizer is not None:
        return True
    try:
        stt_vosk.init_recognizer()
        return True
    except Exception as exc:  # pragma: no cover - hardware specific
        logger(f"Unable to load Vosk recognizer for hotword detection: {exc}")
        return False


def _normalize_phrase_list(items) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        text = str(item).strip().lower()
        if not text or text in seen:
            continue
        phrases.append(text)
        seen.add(text)
    return phrases


def _get_hotword_phrases(cfg) -> tuple[list[str], list[str]]:
    primary = [getattr(cfg, "HOTWORD", "")] + list(getattr(cfg, "HOTWORD_ALIASES", []) or [])
    visible = _normalize_phrase_list(primary)
    hidden_candidates = _normalize_phrase_list(getattr(cfg, "HOTWORD_HIDDEN_ALIASES", []) or [])
    hidden = [phrase for phrase in hidden_candidates if phrase not in visible]
    return visible, hidden


def listen_for_hotword(
    config_module=None,
    logger=default_logger,
    timeout_seconds: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
    poll_interval: float = 0.1,
) -> bool:
    """Continuously listen until the configured hotword is detected or timeout occurs."""
    cfg = config_module or config
    if not getattr(cfg, "USE_STT", False):
        logger("Hotword detection skipped because STT is disabled in config.")
        return False

    visible_phrases, hidden_phrases = _get_hotword_phrases(cfg)
    phrases = visible_phrases + hidden_phrases
    if not phrases:
        logger("Hotword phrase not configured.")
        return False

    if not _ensure_recognizer_ready(logger=logger):
        return False

    timeout = timeout_seconds if timeout_seconds is not None else getattr(cfg, "HOTWORD_TIMEOUT_SECONDS", None)
    deadline = time.time() + timeout if timeout else None

    if visible_phrases:
        readable = ", ".join(f"'{phrase}'" for phrase in visible_phrases)
        logger(f"Listening for hotword(s) {readable}...")
    else:
        logger("Listening for configured hotword(s)...")
    poll_interval = max(0.05, float(poll_interval))

    while True:
        if stop_event and stop_event.is_set():
            logger("Hotword listener stopped by request.")
            return False
        if deadline and time.time() > deadline:
            logger("Hotword listen timed out.")
            return False

        transcript = stt_vosk.listen_once(timeout_seconds=3.0)
        if stop_event and stop_event.is_set():
            return False
        if transcript:
            logger(f"Heard: '{transcript}'")
            for phrase in phrases:
                if _fuzzy_match(transcript, phrase, logger=logger, threshold=0.65):
                    logger(f"Hotword detected ({phrase}).")
                    return True
        if stop_event:
            if stop_event.wait(poll_interval):
                return False
        else:
            time.sleep(poll_interval)
