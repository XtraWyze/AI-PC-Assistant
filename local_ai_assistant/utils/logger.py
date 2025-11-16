"""Minimal logging helper to avoid repeating boilerplate."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOGS_DIR / "assistant.log"
LOG_TO_FILE = False  # Flip to True to keep a rolling log file.


def _write_to_file(message: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def log(message: str, *, also_print: bool = True) -> None:
    """Print a timestamped message and optionally persist to disk."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    if also_print:
        print(formatted)
    if LOG_TO_FILE:
        _write_to_file(formatted)
