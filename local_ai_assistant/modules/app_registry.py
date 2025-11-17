"""Filesystem-backed registry of installed Windows applications."""
from __future__ import annotations

import json
import os
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from utils.logger import log

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "app_registry.json"
MAX_SCAN_DEPTH = 5
DEFAULT_EXTENSIONS: Sequence[str] = (".exe",)

_DEFAULT_SEARCH_DIRS = [
    "C:/Program Files",
    "C:/Program Files (x86)",
    os.environ.get("LOCALAPPDATA", ""),
    os.environ.get("APPDATA", ""),
]

_REGISTRY_CACHE: Optional[Dict[str, str]] = None

ALIASES = {
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "ms word": "winword",
    "word": "winword",
    "power point": "powerpnt",
    "powerpoint": "powerpnt",
    "excel": "excel",
}


def _ensure_storage() -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _candidate_dirs(extra_dirs: Optional[Iterable[os.PathLike[str] | str]] = None) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw in list(_DEFAULT_SEARCH_DIRS) + list(extra_dirs or []):
        if raw is None:
            continue
        path_str = str(raw).strip()
        if not path_str:
            continue
        candidate = Path(path_str).expanduser()
        try:
            candidate = candidate.resolve()
        except FileNotFoundError:
            continue
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        yield candidate


def _should_include(filename: str, extensions: Sequence[str]) -> bool:
    suffix = Path(filename).suffix.lower()
    return any(suffix == ext.lower() for ext in extensions)


def _limited_walk(base: Path) -> Iterable[tuple[Path, Sequence[str]]]:
    def _onerror(error: OSError) -> None:  # pragma: no cover - logging only
        log(f"App scan skipped a path: {error}")

    for root, dirs, files in os.walk(base, topdown=True, onerror=_onerror):
        current = Path(root)
        try:
            rel_depth = len(current.relative_to(base).parts)
        except ValueError:
            rel_depth = MAX_SCAN_DEPTH
        if rel_depth >= MAX_SCAN_DEPTH:
            dirs[:] = []
        yield current, files


def _best_path(existing: Optional[str], candidate: str) -> str:
    if not existing:
        return candidate
    return candidate if len(candidate) < len(existing) else existing


def _normalize_registry_payload(payload: object) -> Dict[str, str]:
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


def load_registry() -> Dict[str, str]:
    """Load the cached registry from disk (or an empty mapping)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return dict(_REGISTRY_CACHE)

    _ensure_storage()
    if not REGISTRY_PATH.exists():
        _REGISTRY_CACHE = {}
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt file scenario
        log(f"App registry corrupt ({exc}). Resetting.")
        _REGISTRY_CACHE = {}
        REGISTRY_PATH.write_text("{}", encoding="utf-8")
        return {}
    registry = _normalize_registry_payload(data)
    _REGISTRY_CACHE = dict(registry)
    return dict(registry)


def save_registry(registry: Dict[str, str]) -> None:
    """Persist the registry to disk and refresh the cache."""
    global _REGISTRY_CACHE
    _ensure_storage()
    payload = {str(k): str(v) for k, v in registry.items()}
    REGISTRY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _REGISTRY_CACHE = dict(payload)


def scan_for_apps(
    extra_dirs: Optional[Iterable[os.PathLike[str] | str]] = None,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
) -> Dict[str, str]:
    """Walk common install locations (plus *extra_dirs*) and build a registry mapping."""
    extensions = tuple(ext.lower() for ext in extensions)
    results: Dict[str, str] = {}

    for base in _candidate_dirs(extra_dirs):
        if not base.exists():
            continue
        for current, files in _limited_walk(base):
            for filename in files:
                if not _should_include(filename, extensions):
                    continue
                normalized = _normalize_name(filename)
                if not normalized:
                    continue
                full_path = current / filename
                try:
                    resolved = str(full_path.resolve())
                except (FileNotFoundError, PermissionError):
                    continue
                results[normalized] = _best_path(results.get(normalized), resolved)

    return results


def find_app(query: str, registry: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return an executable path that best matches *query*, or None if not found."""
    if not query:
        return None
    normalized_query = _normalize_name(query)
    if not normalized_query:
        return None

    canonical = ALIASES.get(normalized_query, normalized_query)
    registry = registry or load_registry()
    if not registry:
        return None

    if canonical in registry:
        return registry[canonical]

    matches = get_close_matches(canonical, list(registry.keys()), n=1, cutoff=0.72)
    if matches:
        return registry[matches[0]]
    return None


def _normalize_name(value: str) -> str:
    """Convert executable names into a comparable, lowercase token."""
    base = Path(value).stem
    base = base.replace("_", " ").replace("-", " ")
    sanitized = re.sub(r"[^a-z0-9\s]", " ", base.lower())
    collapsed = re.sub(r"\s+", " ", sanitized).strip()
    return collapsed