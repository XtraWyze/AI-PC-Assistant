"""Tiny JSON-backed memory store for the assistant."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import simplejson as json

from utils.logger import log

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.json"


def _ensure_file() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists():
        DATA_PATH.write_text("{}", encoding="utf-8")


def load_memory() -> Dict[str, str]:
    """Load memory JSON, returning an empty dict on failure."""
    _ensure_file()
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log(f"Memory file corrupt: {exc}. Resetting.")
        DATA_PATH.write_text("{}", encoding="utf-8")
        return {}


def save_memory(memory: Dict[str, str]) -> None:
    """Persist the memory mapping to disk."""
    _ensure_file()
    DATA_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")


def add_entry(key: str, value: str) -> None:
    """Add or update a memory entry."""
    memory = load_memory()
    memory[key] = value
    save_memory(memory)


def search_memory(query: str) -> List[str]:
    """Return memory values where the query substring appears."""
    if not query:
        return []
    memory = load_memory()
    query_lower = query.lower()
    results: List[str] = []
    for key, value in memory.items():
        haystack = f"{key} {value}".lower()
        if query_lower in haystack:
            results.append(f"{key}: {value}")
    return results
