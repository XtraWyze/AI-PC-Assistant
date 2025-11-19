"""Xbox Game Bar capture helpers and tool entry points."""
from __future__ import annotations

import ctypes
import os
import time
from typing import Any, Dict, Iterable, Tuple

from utils.logger import log as default_logger

VK_LWIN = 0x5B
VK_MENU = 0x12  # Alt key
VK_G = 0x47
VK_R = 0x52

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

_HOTKEY_RECORD_LAST_30S: Tuple[int, int, int] = (VK_LWIN, VK_MENU, VK_G)
_HOTKEY_RECORD_TOGGLE: Tuple[int, int, int] = (VK_LWIN, VK_MENU, VK_R)

_USER32 = None


def _ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Xbox Game Bar controls are only available on Windows.")


def _get_user32():
    global _USER32
    if _USER32 is None:
        _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    return _USER32


def _press_key(vk_code: int, key_up: bool = False) -> None:
    user32 = _get_user32()
    flags = KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    user32.keybd_event(vk_code, 0, flags, 0)


def _send_hotkey(combo: Iterable[int]) -> None:
    keys = list(combo)
    if not keys:
        return
    time.sleep(0.03)
    for vk_code in keys:
        _press_key(vk_code, key_up=False)
        time.sleep(0.01)
    time.sleep(0.02)
    for vk_code in reversed(keys):
        _press_key(vk_code, key_up=True)
        time.sleep(0.01)


def _perform(action: str, combo: Tuple[int, ...], message: str, logger=default_logger) -> Dict[str, Any]:
    _ensure_windows()
    _send_hotkey(combo)
    logger(f"Xbox Game Bar: {message}")
    return {"success": True, "action": action, "message": message}


def record_last_30_seconds(logger=default_logger) -> Dict[str, Any]:
    """Trigger Win+Alt+G to save the last 30 seconds."""
    return _perform(
        action="record_last_30_seconds",
        combo=_HOTKEY_RECORD_LAST_30S,
        message="Captured the last 30 seconds via Xbox Game Bar.",
        logger=logger,
    )


def start_recording(logger=default_logger) -> Dict[str, Any]:
    """Trigger Win+Alt+R to begin an on-going recording."""
    return _perform(
        action="start_recording",
        combo=_HOTKEY_RECORD_TOGGLE,
        message="Asked Xbox Game Bar to start recording (Win+Alt+R).",
        logger=logger,
    )


def stop_recording(logger=default_logger) -> Dict[str, Any]:
    """Trigger Win+Alt+R to stop the current recording."""
    return _perform(
        action="stop_recording",
        combo=_HOTKEY_RECORD_TOGGLE,
        message="Asked Xbox Game Bar to stop recording (Win+Alt+R).",
        logger=logger,
    )


def toggle_recording(logger=default_logger) -> Dict[str, Any]:
    """Toggle the recording state (Win+Alt+R)."""
    return _perform(
        action="toggle_recording",
        combo=_HOTKEY_RECORD_TOGGLE,
        message="Toggled Xbox Game Bar recording (Win+Alt+R).",
        logger=logger,
    )


def handle_gamebar_action(action: str, logger=default_logger) -> Dict[str, Any]:
    """Tool-friendly entry point for Xbox Game Bar shortcuts."""
    normalized = (action or "").strip().lower().replace(" ", "_")
    if normalized in {"record_that", "record_last_30_seconds", "record_last_30_secs"}:
        return record_last_30_seconds(logger=logger)
    if normalized in {"start_recording", "start", "record_this", "begin_recording"}:
        return start_recording(logger=logger)
    if normalized in {"stop_recording", "stop", "end_recording"}:
        return stop_recording(logger=logger)
    if normalized in {"toggle_recording", "toggle"}:
        return toggle_recording(logger=logger)
    raise ValueError(f"Unsupported Xbox Game Bar action: {action!r}")
