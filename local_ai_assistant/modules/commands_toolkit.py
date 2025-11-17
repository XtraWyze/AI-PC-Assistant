"""Local PC control commands that run entirely offline."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config
from utils.logger import log as default_logger

from . import app_registry, audio_control, file_indexer, file_search

REPO_ROOT = Path(__file__).resolve().parents[2]
FALLBACK_HOMEPAGE = "https://github.com"

_SCAN_COMMANDS = {"scan apps", "rescan apps", "refresh apps"}
_LIST_COMMANDS = {"list apps", "list applications"}
_CLOSE_COMMANDS = {"close app", "close application"}
_FILE_INDEX_PREFIXES = ("index files", "reindex files", "scan files")
_FILE_SEARCH_PREFIXES = (
    "find file",
    "find my files",
    "search files for",
    "search my files for",
    "where is",
)
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_MUTE = 0xAD

_MEDIA_COMMANDS: list[tuple[str, int, str]] = [
    ("pause music", VK_MEDIA_PLAY_PAUSE, "Music paused."),
    ("pause", VK_MEDIA_PLAY_PAUSE, "Music paused."),
    ("play music", VK_MEDIA_PLAY_PAUSE, "Resuming your music."),
    ("play", VK_MEDIA_PLAY_PAUSE, "Resuming your music."),
    ("resume", VK_MEDIA_PLAY_PAUSE, "Resuming your music."),
    ("skip", VK_MEDIA_NEXT_TRACK, "Skipping the track."),
    ("next song", VK_MEDIA_NEXT_TRACK, "Skipping the track."),
    ("next track", VK_MEDIA_NEXT_TRACK, "Skipping the track."),
    ("next", VK_MEDIA_NEXT_TRACK, "Skipping the track."),
    ("previous song", VK_MEDIA_PREV_TRACK, "Going to the previous track."),
    ("previous", VK_MEDIA_PREV_TRACK, "Going to the previous track."),
    ("prev", VK_MEDIA_PREV_TRACK, "Going to the previous track."),
    ("mute", VK_VOLUME_MUTE, "Muted your audio."),
    ("volume up", VK_VOLUME_UP, "Volume increased."),
    ("turn up", VK_VOLUME_UP, "Volume increased."),
    ("volume down", VK_VOLUME_DOWN, "Volume decreased."),
    ("turn down", VK_VOLUME_DOWN, "Volume decreased."),
]

_FOLDER_PATTERN = re.compile(r"open\s+folder\s+(.+)", re.IGNORECASE)
_TYPE_PATTERN = re.compile(r"type\s*:\s*(.+)", re.IGNORECASE)

_SET_VOLUME_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (
        re.compile(
            r"set\s+(?:the\s+)?(?P<app>[\w\s]+?)\s+volume\s+to\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        re.compile(
            r"set\s+volume\s+of\s+(?:the\s+)?(?P<app>[\w\s]+?)\s+to\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        re.compile(
            r"set\s+(?:the\s+)?(?P<app>[\w\s]+?)\s+to\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?",
            re.IGNORECASE,
        ),
        True,
    ),
)

_DELTA_VOLUME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?P<verb>lower|decrease|reduce)\s+(?:the\s+)?(?P<app>[\w\s]+?)(?:\s+volume)?\s+by\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<verb>raise|increase|boost)\s+(?:the\s+)?(?P<app>[\w\s]+?)(?:\s+volume)?\s+by\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"turn\s+(?:the\s+)?(?P<app>[\w\s]+?)(?:\s+volume)?\s+(?P<direction>up|down)(?:\s+by\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)?)?",
        re.IGNORECASE,
    ),
)

_UNMUTE_PATTERN = re.compile(r"\bunmute\s+(?:the\s+)?(?P<app>[\w\s]+)", re.IGNORECASE)
_MUTE_PATTERN = re.compile(r"\bmute\s+(?:the\s+)?(?P<app>[\w\s]+)", re.IGNORECASE)
_FILLER_TOKENS = {"the", "a", "an", "app", "application", "volume", "audio", "sound", "percent", "please", "thanks", "thank", "you"}
_DEFAULT_VOLUME_DELTA = 5.0


def _contains_percent_marker(text: str, normalized: str) -> bool:
    return "percent" in normalized or "%" in text


def _sanitize_app_name(raw: str) -> str:
    candidate = raw.replace("%", " ").strip().strip(" .,!?:;")
    if not candidate:
        return ""
    tokens = [token for token in re.split(r"\s+", candidate) if token.lower() not in _FILLER_TOKENS]
    cleaned = " ".join(tokens).strip().strip(" .,!?:;")
    return cleaned


def _format_app_label(app_name: str) -> str:
    if not app_name:
        return "that app"
    if len(app_name) <= 3:
        return app_name.upper()
    return app_name.title()


def _direction_is_negative(word: str) -> bool:
    lowered = word.lower()
    return lowered in {"lower", "decrease", "reduce", "down"}


def _parse_volume_command(text: str) -> Optional[dict[str, Any]]:
    normalized = _normalize(text)
    if not normalized:
        return None
    percent_marker = _contains_percent_marker(text, normalized)

    for pattern, requires_percent in _SET_VOLUME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if requires_percent and not percent_marker:
            continue
        app = _sanitize_app_name(match.group("app"))
        if not app:
            continue
        try:
            value = float(match.group("value"))
        except (TypeError, ValueError):
            continue
        return {"type": "set", "app": app, "value": value}

    for pattern in _DELTA_VOLUME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        app = _sanitize_app_name(match.group("app"))
        if not app:
            continue
        value_str = match.groupdict().get("value")
        try:
            delta = float(value_str) if value_str else _DEFAULT_VOLUME_DELTA
        except (TypeError, ValueError):
            delta = _DEFAULT_VOLUME_DELTA
        direction_word = match.groupdict().get("direction") or match.groupdict().get("verb") or ""
        if _direction_is_negative(direction_word or ""):
            delta = -abs(delta)
        else:
            delta = abs(delta)
        return {"type": "delta", "app": app, "value": delta}

    for pattern, mute_flag in ((_UNMUTE_PATTERN, False), (_MUTE_PATTERN, True)):
        match = pattern.search(text)
        if not match:
            continue
        app = _sanitize_app_name(match.group("app"))
        if not app:
            continue
        return {"type": "mute", "app": app, "mute": mute_flag}

    return None


def _execute_volume_command(command: dict[str, Any], logger=default_logger) -> str:
    app_query = (command.get("app") or "").strip()
    if not app_query:
        return "Please tell me which app to control."
    app_label = _format_app_label(app_query)
    cmd_type = command.get("type")

    if cmd_type == "set":
        target_value = max(0.0, min(100.0, float(command.get("value", 0.0))))
        logger(f"Setting volume for {app_query} to {target_value:.1f}%")
        success = audio_control.set_app_volume(app_query, target_value)
        if success:
            return f"Set {app_label} volume to {target_value:.0f} percent."
        return f"I couldn't find an audio session for {app_label}."

    if cmd_type == "delta":
        delta_value = float(command.get("value", 0.0))
        if delta_value == 0:
            return f"Please provide how much to change {app_label}'s volume."
        direction = "down" if delta_value < 0 else "up"
        logger(f"Changing volume for {app_query} by {delta_value:.1f}%")
        success = audio_control.change_app_volume(app_query, delta_value)
        if success:
            return f"Turned {app_label} volume {direction} by {abs(delta_value):.0f} percent."
        return f"I couldn't find an audio session for {app_label}."

    if cmd_type == "mute":
        mute_flag = bool(command.get("mute", True))
        logger(f"Setting mute={mute_flag} for {app_query}")
        success = audio_control.mute_app(app_query, mute=mute_flag)
        if success:
            action = "Muted" if mute_flag else "Unmuted"
            return f"{action} {app_label}."
        return f"I couldn't find an audio session for {app_label}."

    return "Sorry, I couldn't parse that volume request."

def _extract_search_query(text: str) -> str:
    normalized = text.lower()
    for prefix in _FILE_SEARCH_PREFIXES:
        if normalized.startswith(prefix):
            remainder = text[len(prefix) :].strip(" :,-")
            return remainder
    return ""


def _match_media_command(normalized: str) -> tuple[int, str] | None:
    for trigger, keycode, message in _MEDIA_COMMANDS:
        if normalized == trigger or normalized.startswith(f"{trigger} "):
            return keycode, message
        if normalized.startswith(trigger) and len(normalized) == len(trigger):
            return keycode, message
    return None


def _send_key_event(keycode: int) -> None:
    if os.name != "nt":  # pragma: no cover - Windows-specific behavior
        raise RuntimeError("Media key simulation is only supported on Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(keycode, 0, KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(keycode, 0, KEYEVENTF_KEYUP, 0)


def _normalize(text: str) -> str:
    return text.strip().lower()


def is_command(text: str) -> bool:
    """Return True when *text* should be handled locally instead of via the LLM."""
    if not text:
        return False
    normalized = _normalize(text)
    if _parse_volume_command(text):
        return True
    if normalized in _SCAN_COMMANDS or normalized in _LIST_COMMANDS:
        return True
    if normalized in {"open browser", "open chrome", "open notepad", "take screenshot"}:
        return True
    if normalized.startswith("open folder") or normalized.startswith("type:"):
        return True
    if normalized in _CLOSE_COMMANDS or normalized.startswith("close "):
        return True
    if normalized.startswith("open ") or normalized.startswith("launch "):
        return True
    if normalized.startswith(_FILE_INDEX_PREFIXES) or normalized.startswith(_FILE_SEARCH_PREFIXES):
        return True
    if _match_media_command(normalized):
        return True
    return False


def handle_command(text: str, logger=default_logger) -> str:
    """Parse and execute supported PC-control commands."""
    if not text:
        return "I didn't catch any command."

    cleaned = text.strip()
    normalized = cleaned.lower()
    logger(f"Handling local command: {text}")

    try:
        volume_command = _parse_volume_command(cleaned)
        if volume_command:
            return _execute_volume_command(volume_command, logger=logger)
        media_match = _match_media_command(normalized)
        if media_match:
            keycode, message = media_match
            _send_key_event(keycode)
            logger(f"Media command executed: {message}")
            return message
        if normalized.startswith(_FILE_INDEX_PREFIXES):
            entries = file_indexer.build_file_index(logger=logger)
            count = len(entries)
            noun = "file" if count == 1 else "files"
            return f"I indexed {count} {noun} in your Documents, Desktop, and Downloads."
        if normalized.startswith(_FILE_SEARCH_PREFIXES):
            query = _extract_search_query(cleaned)
            if not query:
                return "Please tell me what to look for in your files."
            results = file_search.search_files(query, logger=logger)
            console_str = file_search.format_search_results_for_console(results)
            print(console_str)
            return file_search.format_search_results_for_speech(results)
        if normalized in _SCAN_COMMANDS:
            return _handle_scan_apps(logger=logger)
        if normalized in _LIST_COMMANDS:
            return _handle_list_apps()
        if normalized in {"open browser", "open chrome"}:
            return _handle_open_browser(prefer_chrome="chrome" in normalized)
        if normalized == "open notepad":
            return _handle_open_notepad()
        if normalized.startswith("open folder"):
            return _handle_open_folder(text)
        if normalized == "take screenshot":
            return _handle_screenshot()
        if normalized.startswith("type:"):
            return _handle_type(text)
        if normalized in _CLOSE_COMMANDS or normalized.startswith("close "):
            return _handle_close_app(text, logger=logger)
        if normalized.startswith("open ") or normalized.startswith("launch "):
            return _handle_launch_app(text, logger=logger)
    except RuntimeError as exc:
        logger(f"Command failed: {exc}")
        return str(exc)
    except Exception as exc:  # pragma: no cover - OS/hardware interactions
        logger(f"Command error: {exc}")
        return "That command failed. Please try again."

    return "Sorry, I don't recognize that command yet."


def _browser_homepage() -> str:
    candidate = getattr(config, "COMMAND_BROWSER_HOME", "")
    candidate = candidate.strip()
    return candidate or FALLBACK_HOMEPAGE


def _screenshot_dir() -> Path:
    folder = getattr(config, "SCREENSHOT_DIR", "screenshots")
    if not folder:
        folder = "screenshots"
    return (REPO_ROOT / folder).resolve()


def _handle_open_browser(prefer_chrome: bool = False) -> str:
    homepage = _browser_homepage()
    if prefer_chrome and _launch_chrome(homepage):
        return "Opening Chrome."
    webbrowser.open(homepage)
    return "Opening your browser."


def _launch_chrome(url: str) -> bool:
    """Attempt to launch Chrome manually if available."""
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        subprocess.Popen([str(path), url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


def _handle_open_notepad() -> str:
    subprocess.Popen(["notepad.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Opening Notepad."


def _handle_open_folder(command_text: str) -> str:
    match = _FOLDER_PATTERN.match(command_text.strip())
    if not match:
        return "Please provide a folder path after 'open folder'."
    raw_path = match.group(1).strip().strip('"')
    if not raw_path:
        return "Please provide a folder path after 'open folder'."

    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    target = Path(expanded)
    if not target.exists():
        return f"I couldn't find '{raw_path}'."
    if not target.is_dir():
        return f"'{raw_path}' is not a folder."

    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
    except AttributeError as exc:  # Non-Windows safeguard
        raise RuntimeError("Folder opening is only supported on Windows.") from exc
    return f"Opening {target}."


def _handle_screenshot() -> str:
    pyautogui = _load_pyautogui()
    screenshot_dir = _screenshot_dir()
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = screenshot_dir / f"screenshot_{timestamp}.png"
    time.sleep(0.3)  # Give the user a moment before capturing
    image = pyautogui.screenshot()
    image.save(destination)
    return f"Screenshot saved to {destination}."


def _handle_type(command_text: str) -> str:
    match = _TYPE_PATTERN.match(command_text.strip())
    if not match:
        return "Please provide text after 'type:'."
    payload = match.group(1).strip()
    if not payload:
        return "Please provide text after 'type:'."

    pyautogui = _load_pyautogui()
    time.sleep(0.4)
    pyautogui.typewrite(payload, interval=0.02)
    return "Typing now."


def _handle_close_app(command_text: str, logger=default_logger) -> str:
    parts = command_text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Please tell me which application to close."
    target = parts[1].strip()
    if not target:
        return "Please tell me which application to close."

    registry = app_registry.load_registry()
    path = app_registry.find_app(target, registry=registry)

    candidate_names: list[tuple[str, str]] = []
    if path:
        exe_name = Path(path).name
        friendly = Path(path).stem.replace("_", " ").title()
        candidate_names.append((exe_name, friendly))
    else:
        process_name = target if target.lower().endswith(".exe") else f"{target}.exe"
        friendly = target.title()
        candidate_names.append((process_name, friendly))

    for process_name, friendly in candidate_names:
        success, details = _terminate_process(process_name)
        if success:
            return f"Closing {friendly}."
        logger(f"Unable to close {process_name}: {details}")

    return "I couldn't close that application. Make sure it is running."


def _handle_scan_apps(logger=default_logger) -> str:
    registry = app_registry.scan_for_apps()
    app_registry.save_registry(registry)
    count = len(registry)
    logger(f"Application scan indexed {count} executables.")
    noun = "application" if count == 1 else "applications"
    return f"Scanned and indexed {count} {noun}."


def _handle_launch_app(command_text: str, logger=default_logger) -> str:
    parts = command_text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Please tell me which application to open."
    target = parts[1].strip()
    if not target:
        return "Please tell me which application to open."

    path = app_registry.find_app(target)
    if not path:
        return "I couldn't find that application. Try saying 'scan apps' first."
    if not os.path.exists(path):
        return "That shortcut looks stale. Please run 'scan apps' again."

    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except AttributeError:
        return "Launching applications is only supported on Windows."
    except OSError as exc:
        logger(f"Unable to launch {path}: {exc}")
        return "I couldn't launch that application."

    friendly = Path(path).stem.replace("_", " ").title()
    return f"Opening {friendly}."


def _handle_list_apps(limit: int = 10) -> str:
    registry = app_registry.load_registry()
    if not registry:
        return "No applications are indexed yet. Say 'scan apps' to build the list."
    names = sorted(registry.keys())[:limit]
    pretty = [name.title() for name in names]
    joined = ", ".join(pretty)
    return f"Here are some apps I can open: {joined}."


def _terminate_process(process_name: str) -> tuple[bool, str]:
    command = ["taskkill", "/IM", process_name, "/F"]
    run_kwargs = {"capture_output": True, "text": True, "check": False}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        run_kwargs["creationflags"] = creationflags
    try:
        result = subprocess.run(command, **run_kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError("taskkill utility is unavailable on this system.") from exc
    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    return result.returncode == 0, output


def _load_pyautogui():
    try:
        import pyautogui
    except ImportError as exc:  # pragma: no cover - env specific
        raise RuntimeError("pyautogui is required. Please install dependencies first.") from exc
    return pyautogui
