"""Local-only command parsing and execution helpers."""
from __future__ import annotations

import re
import webbrowser
from datetime import datetime
from typing import Callable

from utils.logger import log

from . import memory_manager

CommandHandler = Callable[[str], str]


def _normalize(text: str) -> str:
    return text.strip().lower()


_COMMANDS = {
    "open browser": lambda _: _handle_open_browser(),
    "what time is it": lambda _: _handle_time(),
    "what's my name": lambda _: _handle_get_name(),
    "what is my name": lambda _: _handle_get_name(),
    "clear memory": lambda _: _handle_clear_memory(),
    "list recent queries": lambda _: _handle_list_history(),
}


def is_command(text: str) -> bool:
    if not text:
        return False
    normalized = _normalize(text)
    if normalized.startswith("set my name to"):
        return True
    return normalized in _COMMANDS


def handle_command(text: str, memory=memory_manager, logger=log) -> str:
    """Dispatch the provided command to a local handler."""
    normalized = _normalize(text)
    logger(f"Handling command: {text}")

    if normalized.startswith("set my name to"):
        return _handle_set_name(text, memory=memory)

    handler = _COMMANDS.get(normalized)
    if handler:
        return handler(text)
    return "Sorry, I don't recognize that command yet."


# ---------------------------------------------------------------------------
# Individual command handlers
# ---------------------------------------------------------------------------

def _handle_open_browser() -> str:
    try:
        webbrowser.open("https://example.com")
        log("Opened default browser to https://example.com")
        return "Opening your browser."
    except Exception as exc:  # pragma: no cover - system dependent
        log(f"Failed to open browser: {exc}")
        return "I couldn't open the browser."


def _handle_time() -> str:
    now = datetime.now().strftime("%I:%M %p").lstrip("0")
    return f"It's {now}."


def _handle_get_name() -> str:
    name = memory_manager.get_fact("name")
    if name:
        return f"Your name is {name}."
    return "I don't know your name yet. Tell me by saying 'set my name to ...'."


def _handle_set_name(text: str, memory=memory_manager) -> str:
    match = re.search(r"set my name to\s+(.+)$", text, re.IGNORECASE)
    if not match:
        return "Please tell me the name after 'set my name to'."
    name = match.group(1).strip()
    if not name:
        return "I didn't catch the name."
    memory.set_fact("name", name)
    return f"Nice to meet you, {name}."


def _handle_clear_memory() -> str:
    memory_manager.clear_memory()
    return "All stored facts and history have been cleared."


def _handle_list_history(limit: int = 5) -> str:
    entries = memory_manager.get_recent_history(limit)
    if not entries:
        return "I don't have any recent queries stored."
    formatted = "; ".join(entries)
    return f"Your last queries were: {formatted}."
