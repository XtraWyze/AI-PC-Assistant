"""Tool that lets Wyzer open local files or folders by friendly names."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import log

_BASE_DIR = Path(__file__).resolve().parents[2]
_DATA_DIR = _BASE_DIR / "data"
_APP_REGISTRY_PATH = _DATA_DIR / "app_registry.json"
_FILE_INDEX_PATH = _DATA_DIR / "file_index.json"
_KNOWN_FOLDER_ALIASES: Dict[str, str] = {
    "downloads": "Downloads",
    "downloads folder": "Downloads",
    "documents": "Documents",
    "documents folder": "Documents",
    "my documents": "Documents",
    "desktop": "Desktop",
    "desktop folder": "Desktop",
    "pictures": "Pictures",
    "pictures folder": "Pictures",
    "photos": "Pictures",
    "photos folder": "Pictures",
    "music": "Music",
    "music folder": "Music",
    "videos": "Videos",
    "videos folder": "Videos",
}
_PREFIXES_TO_STRIP: Tuple[str, ...] = (
    "open ",
    "launch ",
    "start ",
    "show ",
    "show me ",
    "go to ",
    "goto ",
    "take me to ",
    "please open ",
    "please show ",
)
_SUFFIXES_TO_STRIP: Tuple[str, ...] = (
    " folder",
    " directory",
    " file",
    " files",
    " path",
    " location",
)
_APP_PREFIXES: Tuple[str, ...] = (
    "open ",
    "launch ",
    "start ",
    "run ",
    "please open ",
)
_WORD_SPLIT_PATTERN = re.compile(r"[^\w]+", re.UNICODE)
_MIN_FILE_MATCH_SCORE = 2
_FILE_INDEX_CACHE: Optional[List[Dict[str, Any]]] = None
_APP_REGISTRY_CACHE: Optional[Dict[str, str]] = None

TOOL_DEFINITION = {
    "name": "open_path",
    "description": "Open a file or folder on the local Windows system by friendly name or path.",
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Name, friendly phrase, or absolute path of the item to open.",
            }
        },
        "required": ["target"],
    },
}


def _normalize_target(target: str) -> str:
    cleaned = re.sub(r"\s+", " ", (target or "").strip())
    return cleaned.strip('\"\'')


def _looks_like_path(value: str) -> bool:
    candidate = value.strip().strip('\"\'')
    if not candidate:
        return False
    if re.match(r"^[a-zA-Z]:[\\/]", candidate):
        return True
    lowered = candidate.lower()
    if lowered.startswith(("./", "../", ".\\", "..\\", "~/", "~\\")):
        return True
    if candidate.startswith(("\\\\", "//")):
        return True
    if candidate.startswith(("/", "\\")):
        return True
    if ":" in candidate and ("\\" in candidate or "/" in candidate):
        return True
    return False


def _expand_path(raw: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(raw))
    absolute = os.path.abspath(expanded)
    return Path(absolute)


def _simplify_phrase(value: str) -> str:
    working = value.strip()
    for prefix in _PREFIXES_TO_STRIP:
        if working.startswith(prefix):
            working = working[len(prefix) :]
            break
    if working.startswith("the "):
        working = working[4:]
    if working.startswith("my "):
        working = working[3:]
    for suffix in _SUFFIXES_TO_STRIP:
        if working.endswith(suffix):
            working = working[: -len(suffix)]
            break
    return working.strip()


def _resolve_known_folder(lowered_target: str) -> Optional[Path]:
    simplified = _simplify_phrase(lowered_target)
    alias = _KNOWN_FOLDER_ALIASES.get(lowered_target) or _KNOWN_FOLDER_ALIASES.get(simplified)
    if not alias:
        return None
    candidate = Path.home() / alias
    if candidate.exists():
        return candidate
    return None


def _load_app_registry() -> Dict[str, str]:
    global _APP_REGISTRY_CACHE
    if _APP_REGISTRY_CACHE is not None:
        return _APP_REGISTRY_CACHE
    try:
        payload = json.loads(_APP_REGISTRY_PATH.read_text(encoding="utf-8"))
        lowered = {key.lower(): value for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)}
        _APP_REGISTRY_CACHE = lowered
    except (OSError, json.JSONDecodeError) as exc:
        log(f"open_path: failed to load app registry: {exc}")
        _APP_REGISTRY_CACHE = {}
    return _APP_REGISTRY_CACHE


def _match_app_path(lowered_target: str) -> Optional[Path]:
    cleaned = lowered_target
    for prefix in _APP_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    registry = _load_app_registry()
    candidate = registry.get(lowered_target) or registry.get(cleaned)
    if not candidate:
        return None
    path = Path(candidate)
    if path.exists():
        return path
    return None


def _load_file_index() -> List[Dict[str, Any]]:
    global _FILE_INDEX_CACHE
    if _FILE_INDEX_CACHE is not None:
        return _FILE_INDEX_CACHE
    try:
        payload = json.loads(_FILE_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            _FILE_INDEX_CACHE = payload
        else:
            _FILE_INDEX_CACHE = []
    except (OSError, json.JSONDecodeError) as exc:
        log(f"open_path: failed to load file index: {exc}")
        _FILE_INDEX_CACHE = []
    return _FILE_INDEX_CACHE


def _tokenize(value: str) -> List[str]:
    tokens = [chunk for chunk in _WORD_SPLIT_PATTERN.split(value.lower()) if chunk]
    return tokens


def _score_entry(entry: Dict[str, Any], tokens: List[str]) -> int:
    if not tokens:
        return 0
    name = str(entry.get("name", "")).lower()
    folder = str(entry.get("folder", "")).lower()
    keywords = {str(keyword).lower() for keyword in entry.get("keywords", []) if isinstance(keyword, str)}
    score = 0
    for token in tokens:
        if not token:
            continue
        if token in name:
            score += 2
        if token == folder:
            score += 2
        if token in keywords:
            score += 1
    return score


def _search_file_index(target: str) -> Optional[Dict[str, Any]]:
    index = _load_file_index()
    if not index:
        return None
    tokens = _tokenize(target)
    if not tokens:
        return None
    best_entry: Optional[Dict[str, Any]] = None
    best_score = 0
    for entry in index:
        score = _score_entry(entry, tokens)
        if score <= 0:
            continue
        if score > best_score:
            candidate_path = entry.get("path")
            if not candidate_path:
                continue
            best_entry = entry
            best_score = score
    if not best_entry or best_score < _MIN_FILE_MATCH_SCORE:
        return None
    candidate_path = Path(best_entry["path"])
    if not candidate_path.exists():
        return None
    return {"entry": best_entry, "path": candidate_path, "score": best_score}


def _launch_path(path: Path, source: str, *, dry_run: bool = False) -> Dict[str, Any]:
    if not path.exists():
        return {
            "status": "error",
            "message": "Path does not exist",
            "requested": str(path),
        }
    payload: Dict[str, Any] = {
        "status": "ok",
        "opened": str(path),
        "path_type": "directory" if path.is_dir() else "file",
        "source": source,
    }
    if dry_run:
        payload["dry_run"] = True
        return payload
    try:
        os.startfile(str(path))  # type: ignore[arg-type]
    except OSError as exc:
        return {
            "status": "error",
            "message": f"Unable to open path: {exc}",
            "requested": str(path),
        }
    return payload


def _handle_explicit_path(target: str, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    if not _looks_like_path(target):
        return None
    candidate = _expand_path(target)
    if not candidate.exists():
        return {
            "status": "error",
            "message": "Path does not exist",
            "requested": str(candidate),
        }
    return _launch_path(candidate, source="explicit_path", dry_run=dry_run)


def _handle_known_folder(lowered_target: str, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    folder = _resolve_known_folder(lowered_target)
    if not folder:
        return None
    return _launch_path(folder, source="known_folder", dry_run=dry_run)


def _handle_app_registry(lowered_target: str, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    app_path = _match_app_path(lowered_target)
    if not app_path:
        return None
    return _launch_path(app_path, source="app_registry", dry_run=dry_run)


def _handle_file_index(target: str, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    match = _search_file_index(target)
    if not match:
        return None
    path = match["path"]
    entry = match["entry"].copy()
    entry.pop("keywords", None)
    result = _launch_path(path, source="file_index", dry_run=dry_run)
    if result.get("status") == "ok":
        result["match"] = {
            "name": entry.get("name"),
            "folder": entry.get("folder"),
            "score": match["score"],
        }
    return result


def run_tool(target: str, context: Optional[Dict[str, Any]] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    """Open a user-requested file, folder, or app path."""
    del context  # Unused placeholder for future metadata.
    normalized = _normalize_target(target)
    if not normalized:
        return {"status": "error", "message": "target is required"}
    lowered = normalized.lower()

    explicit = _handle_explicit_path(normalized, dry_run=dry_run)
    if explicit:
        return explicit

    folder_result = _handle_known_folder(lowered, dry_run=dry_run)
    if folder_result:
        return folder_result

    app_result = _handle_app_registry(lowered, dry_run=dry_run)
    if app_result:
        return app_result

    file_match = _handle_file_index(normalized, dry_run=dry_run)
    if file_match:
        return file_match

    return {
        "status": "error",
        "message": "Could not find a file or folder matching the target.",
        "requested": normalized,
    }


def _debug_run() -> None:
    tests = [
        "downloads folder",
        "documents",
        "desktop.ini in documents",
    ]
    for query in tests:
        print(f"Testing open_path -> {query!r}")
        response = run_tool(query, dry_run=True)
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    _debug_run()
