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


def _listen_with_streaming(
    phrases: list[str],
    poll_interval: float,
    blocksize: int,
    idle_reset_seconds: float,
    threshold: float,
    deadline: Optional[float],
    stop_event: Optional[threading.Event],
    logger=default_logger,
) -> Optional[bool]:
    """Attempt a single streaming hotword listen cycle. Returns None if unavailable."""

    def matcher(transcript: str) -> bool:
        cleaned = transcript.strip()
        if not cleaned:
            return False
        logger(f"Heard: '{cleaned}'")
        for phrase in phrases:
            if _fuzzy_match(cleaned, phrase, logger=logger, threshold=threshold):
                logger(f"Hotword detected ({phrase}).")
                return True
        return False

    try:
        detector = stt_vosk.VoiceInterruptDetector(
            phrases,
            blocksize=blocksize,
            match_predicate=matcher,
        )
    except Exception as exc:
        logger(f"Streaming hotword listener unavailable: {exc}")
        return None

    try:
        timeout_seconds = None
        if deadline is not None:
            remaining = max(0.0, deadline - time.time())
            if remaining == 0:
                logger("Hotword listen timed out.")
                return False
            timeout_seconds = remaining

        detected = detector.listen_continuous(
            stop_event=stop_event,
            poll_timeout=poll_interval,
            idle_reset_seconds=idle_reset_seconds,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        logger(f"Streaming hotword listener error: {exc}")
        return None
    finally:
        detector.close()

    if detected:
        return True

    if stop_event and stop_event.is_set():
        logger("Hotword listener stopped by request.")
        return False

    if deadline is not None and time.time() >= deadline:
        logger("Hotword listen timed out.")
        return False

    logger("Streaming hotword listener exited unexpectedly; falling back to polling mode.")
    return None


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
    poll_interval = max(0.02, float(poll_interval))

    threshold = float(getattr(cfg, "HOTWORD_MATCH_THRESHOLD", 0.62) or 0.62)
    blocksize = max(256, int(getattr(cfg, "HOTWORD_STREAM_BLOCKSIZE", 2048) or 2048))
    idle_reset_seconds = max(0.3, float(getattr(cfg, "HOTWORD_IDLE_RESET_SECONDS", 0.9) or 0.9))
    passive_window = max(0.8, float(getattr(cfg, "HOTWORD_PASSIVE_LISTEN_SECONDS", 1.6) or 1.6))
    silence_timeout = max(0.25, float(getattr(cfg, "HOTWORD_SILENCE_TIMEOUT", 0.45) or 0.45))
    min_phrase_seconds = max(0.2, float(getattr(cfg, "HOTWORD_MIN_PHRASE_SECONDS", 0.35) or 0.35))

    if getattr(cfg, "HOTWORD_STREAMING", True):
        streaming_result = _listen_with_streaming(
            phrases,
            poll_interval=poll_interval,
            blocksize=blocksize,
            idle_reset_seconds=idle_reset_seconds,
            threshold=threshold,
            deadline=deadline,
            stop_event=stop_event,
            logger=logger,
        )
        if streaming_result is not None:
            return streaming_result

        logger("Falling back to legacy hotword polling loop.")

    while True:
        if stop_event and stop_event.is_set():
            logger("Hotword listener stopped by request.")
            return False
        if deadline and time.time() > deadline:
            logger("Hotword listen timed out.")
            return False

        transcript = stt_vosk.listen_once(
            timeout_seconds=passive_window,
            silence_timeout=silence_timeout,
            min_seconds=min_phrase_seconds,
            blocksize=blocksize,
        )
        if stop_event and stop_event.is_set():
            return False
        if transcript:
            logger(f"Heard: '{transcript}'")
            for phrase in phrases:
                if _fuzzy_match(transcript, phrase, logger=logger, threshold=threshold):
                    logger(f"Hotword detected ({phrase}).")
                    return True
        if stop_event:
            if stop_event.wait(poll_interval):
                return False
        else:
            time.sleep(poll_interval)
