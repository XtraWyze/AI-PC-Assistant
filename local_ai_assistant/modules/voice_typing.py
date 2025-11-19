"""Voice typing/dictation helpers that simulate keyboard input on Windows.

This module uses pyautogui to type transcripts into the currently focused window.
Be careful when enabling it: keystrokes will be sent to *whatever* app has focus.
"""
from __future__ import annotations

import platform
import re
import threading
from typing import Any, Callable, Final

import config
from utils.logger import log

try:  # pyautogui is optional at runtime.
    import pyautogui
except Exception:  # pragma: no cover - dependency might be missing in some envs
    pyautogui = None  # type: ignore

VOICE_TYPING_ENABLED = False
_LOCK = threading.Lock()
_BACKEND_READY = False
_DEPENDENCY_WARNING_EMITTED = False
_PLATFORM_WARNING_EMITTED = False

_START_PHRASES: Final[set[str]] = {
    "start typing",
    "start typing mode",
    "enable voice typing",
    "start dictation",
}
_STOP_PHRASES: Final[set[str]] = {
    "stop typing",
    "stop typing mode",
    "disable voice typing",
    "cancel dictation",
}

def _feature_allowed() -> bool:
    return bool(getattr(config, "ENABLE_VOICE_TYPING", False))


def _normalize_phrase(text: str) -> str:
    normalized = (text or "").strip().lower()
    return " ".join(normalized.replace("-", " ").split())


def _strip_phrase_suffix(original: str, phrase: str) -> str:
    """Remove the first occurrence of phrase (case-insensitive) and return the trailing text."""
    if not original:
        return ""
    words = [re.escape(part) for part in phrase.split() if part]
    if not words:
        return ""
    pattern = re.compile(r"\b" + r"\s+".join(words) + r"\b", re.IGNORECASE)
    match = pattern.search(original)
    if not match:
        return ""
    suffix = original[match.end():].lstrip(", .:;-")
    return suffix.strip()


def _ensure_backend_ready() -> bool:
    """Make sure we are on Windows with pyautogui available."""
    global _BACKEND_READY, _DEPENDENCY_WARNING_EMITTED, _PLATFORM_WARNING_EMITTED

    if not _feature_allowed():
        return False

    if platform.system().lower() != "windows":
        if not _PLATFORM_WARNING_EMITTED:
            log("Voice typing is currently only supported on Windows.")
            _PLATFORM_WARNING_EMITTED = True
        return False

    if pyautogui is None:
        if not _DEPENDENCY_WARNING_EMITTED:
            log("Voice typing requires 'pyautogui'. Run 'pip install pyautogui' to enable dictation.")
            _DEPENDENCY_WARNING_EMITTED = True
        return False

    if not _BACKEND_READY:
        try:
            pyautogui.FAILSAFE = False
        except Exception:
            pass
        _BACKEND_READY = True
    return True


def _is_enabled() -> bool:
    with _LOCK:
        return VOICE_TYPING_ENABLED


def enable_voice_typing() -> bool:
    """Turn on dictation if the platform/dependencies allow it."""
    if not _feature_allowed():
        log("Voice typing is disabled via config.ENABLE_VOICE_TYPING=False.")
        return False
    if not _ensure_backend_ready():
        return False
    with _LOCK:
        global VOICE_TYPING_ENABLED
        if VOICE_TYPING_ENABLED:
            return True
        VOICE_TYPING_ENABLED = True
    log("Voice typing enabled. Recognized speech will be typed into the active window.")
    return True


def disable_voice_typing() -> bool:
    """Turn off dictation."""
    changed = False
    with _LOCK:
        global VOICE_TYPING_ENABLED
        if VOICE_TYPING_ENABLED:
            VOICE_TYPING_ENABLED = False
            changed = True
    if changed:
        log("Voice typing disabled.")
    return changed


def toggle_voice_typing() -> bool:
    """Swap the current dictation state."""
    if _is_enabled():
        disable_voice_typing()
        return False
    enable_voice_typing()
    return True


def _press_key(key_name: str) -> None:
    if not _ensure_backend_ready():
        return
    if pyautogui is None:
        return
    try:
        pyautogui.press(key_name)
    except Exception as exc:  # pragma: no cover - guard real hardware
        log(f"Voice typing key press failed: {exc}")


def _press_hotkey(*key_names: str) -> None:
    if not _ensure_backend_ready():
        return
    if pyautogui is None:
        return
    try:
        pyautogui.hotkey(*key_names)
    except Exception as exc:  # pragma: no cover - guard real hardware
        log(f"Voice typing hotkey failed: {exc}")


COMMAND_PATTERNS: Final[dict[str, Callable[[], None]]] = {
    # Basic keys
    "press enter": lambda: _press_key("enter"),
    "new line": lambda: _press_key("enter"),
    "newline": lambda: _press_key("enter"),
    "line break": lambda: _press_key("enter"),
    "press tab": lambda: _press_key("tab"),
    "press escape": lambda: _press_key("esc"),
    "press space": lambda: _press_key("space"),
    "press space bar": lambda: _press_key("space"),
    "space bar": lambda: _press_key("space"),
    "press backspace": lambda: _press_key("backspace"),
    "backspace": lambda: _press_key("backspace"),
    "delete last": lambda: _press_key("backspace"),
    "undo last": lambda: _press_key("backspace"),
    "press delete": lambda: _press_key("delete"),
    # Arrow keys
    "press up arrow": lambda: _press_key("up"),
    "press up": lambda: _press_key("up"),
    "press down arrow": lambda: _press_key("down"),
    "press down": lambda: _press_key("down"),
    "press left arrow": lambda: _press_key("left"),
    "press left": lambda: _press_key("left"),
    "press right arrow": lambda: _press_key("right"),
    "press right": lambda: _press_key("right"),
    # Modifier combos
    "press control c": lambda: _press_hotkey("ctrl", "c"),
    "press control v": lambda: _press_hotkey("ctrl", "v"),
    "press control x": lambda: _press_hotkey("ctrl", "x"),
    "press control a": lambda: _press_hotkey("ctrl", "a"),
    "press alt tab": lambda: _press_hotkey("alt", "tab"),
    "press shift tab": lambda: _press_hotkey("shift", "tab"),
    # Navigation phrases
    "go to the top": lambda: _press_hotkey("ctrl", "home"),
    "go to the bottom": lambda: _press_hotkey("ctrl", "end"),
    "select all": lambda: _press_hotkey("ctrl", "a"),
    "undo": lambda: _press_hotkey("ctrl", "z"),
    "redo": lambda: _press_hotkey("ctrl", "y"),
}

_COMMAND_PHRASES_BY_LENGTH: Final[tuple[str, ...]] = tuple(
    sorted(COMMAND_PATTERNS.keys(), key=len, reverse=True)
)


def _execute_command(phrase: str, action: Callable[[], None]) -> bool:
    if not _ensure_backend_ready():
        return False
    if not _is_enabled():
        log(f"Voice typing command '{phrase}' executed while dictation mode was off.")
    try:
        action()
        log(f"Voice typing command executed: '{phrase}'")
        return True
    except Exception as exc:  # pragma: no cover - guard real hardware
        log(f"Voice typing command '{phrase}' failed: {exc}")
        return False


def _type_text(text: str) -> None:
    if not _ensure_backend_ready():
        return
    if pyautogui is None:
        return
    try:
        pyautogui.typewrite(text, interval=0.01)
    except Exception as exc:  # pragma: no cover
        log(f"Voice typing failed while sending text: {exc}")


def process_transcript(text: str) -> bool:
    """Translate incoming STT transcripts into keystrokes.

    Returns True if the utterance was handled locally (command toggles, hotkeys, or
    actual dictation keystrokes). Returns False when the transcript should continue
    through the normal assistant pipeline.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False

    normalized = _normalize_phrase(cleaned)

    for phrase in _STOP_PHRASES:
        if phrase in normalized:
            disable_voice_typing()
            return True

    for phrase in _START_PHRASES:
        if phrase in normalized:
            enabled = enable_voice_typing()
            if enabled:
                remainder = _strip_phrase_suffix(cleaned, phrase)
                if remainder:
                    _type_text(remainder)
            return True

    spoken = normalized
    for phrase in _COMMAND_PHRASES_BY_LENGTH:
        if phrase in spoken:
            action = COMMAND_PATTERNS[phrase]
            if _execute_command(phrase, action):
                return True

    if not _is_enabled():
        return False

    # No command matched; fall back to literal typing.
    _type_text(cleaned)
    return True


def control_voice_typing(action: str, text: str | None = None) -> dict[str, Any]:
    """Tool-friendly helper to manage or use voice typing from the LLM."""
    normalized = (action or "").strip().lower()
    valid_actions = {"enable", "disable", "toggle", "status", "type"}
    if normalized not in valid_actions:
        raise ValueError(f"Unsupported voice typing action: {action!r}")

    result: dict[str, Any] = {"action": normalized}

    if normalized == "enable":
        success = enable_voice_typing()
        result.update({"typing_enabled": _is_enabled(), "success": bool(success)})
        return result

    if normalized == "disable":
        success = disable_voice_typing()
        result.update({"typing_enabled": _is_enabled(), "success": bool(success)})
        return result

    if normalized == "toggle":
        state = toggle_voice_typing()
        result.update({"typing_enabled": state})
        return result

    if normalized == "status":
        backend_ready = _ensure_backend_ready()
        result.update({"typing_enabled": _is_enabled(), "backend_ready": backend_ready})
        return result

    # normalized == "type"
    payload = (text or "").strip()
    if not payload:
        raise ValueError("The 'text' field is required when action='type'.")
    if not _is_enabled():
        success = enable_voice_typing()
        if not success:
            raise RuntimeError("Voice typing backend is unavailable; cannot type text.")
    _type_text(payload)
    result.update({"typing_enabled": True, "typed_chars": len(payload)})
    return result
