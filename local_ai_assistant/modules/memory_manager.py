"""JSON-backed memory store for persistent facts + recent history."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional

import simplejson as json

import config
from utils.logger import log

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / config.MEMORY_FILE

MemoryType = Dict[str, Any]
HistoryType = List[str]

DEFAULT_MEMORY: MemoryType = {"facts": {}, "history": []}


def _fresh_memory() -> MemoryType:
    return {"facts": {}, "history": []}


def _ensure_file() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists():
        DATA_PATH.write_text(json.dumps(_fresh_memory(), indent=2), encoding="utf-8")


def _ensure_structure(payload: Optional[MemoryType]) -> MemoryType:
    data: MemoryType = {"facts": {}, "history": []}
    if isinstance(payload, MutableMapping):
        data["facts"] = dict(payload.get("facts") or {})
        history = payload.get("history") or []
        if isinstance(history, list):
            data["history"] = [str(entry) for entry in history][-config.MAX_HISTORY_ENTRIES :]
    return data


def load_memory() -> MemoryType:
    """Load structured memory, healing/capping on corruption."""
    _ensure_file()
    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log(f"Memory file corrupt: {exc}. Resetting.")
        DATA_PATH.write_text(json.dumps(_fresh_memory(), indent=2), encoding="utf-8")
        return _fresh_memory()
    return _ensure_structure(payload)


def save_memory(memory: MemoryType) -> None:
    """Persist structured memory to disk."""
    _ensure_file()
    capped = _ensure_structure(memory)
    DATA_PATH.write_text(json.dumps(capped, indent=2), encoding="utf-8")


def clear_memory(section: str | None = None) -> None:
    """Clear facts, history, or everything when section is None."""
    memory = load_memory()
    if section == "facts":
        memory["facts"] = {}
    elif section == "history":
        memory["history"] = []
    else:
        memory = _fresh_memory()
    save_memory(memory)


def get_fact(key: str, default: Optional[str] = None) -> Optional[str]:
    data = load_memory()
    value = data["facts"].get(key)
    return value if isinstance(value, str) else default


def set_fact(key: str, value: str) -> None:
    if not key:
        return
    memory = load_memory()
    memory["facts"][key] = value
    save_memory(memory)


def add_history_entry(text: str) -> None:
    if not text:
        return
    memory = load_memory()
    history: HistoryType = memory.setdefault("history", [])  # type: ignore[assignment]
    history.append(text)
    memory["history"] = history[-config.MAX_HISTORY_ENTRIES :]
    save_memory(memory)


def get_recent_history(limit: int = 10) -> HistoryType:
    history = load_memory().get("history", [])
    limit = max(1, limit)
    return history[-limit:]


def add_entry(key: str, value: str) -> None:
    """Backward-compatible alias that stores the value as a fact."""
    set_fact(key, value)


def search_memory(query: str) -> List[str]:
    """Return fact/history entries matching the substring."""
    if not query:
        return []
    memory = load_memory()
    query_lower = query.lower()
    results: List[str] = []
    for key, value in memory.get("facts", {}).items():
        haystack = f"{key} {value}".lower()
        if query_lower in haystack:
            results.append(f"{key}: {value}")
    for item in memory.get("history", []):
        if query_lower in str(item).lower():
            results.append(f"history: {item}")
    return results
