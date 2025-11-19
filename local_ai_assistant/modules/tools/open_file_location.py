"""Tool that opens the folder containing a matched file from file_index.json."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import log

_BASE_DIR = Path(__file__).resolve().parents[2]
_DATA_DIR = _BASE_DIR / "data"
_FILE_INDEX_PATH = _DATA_DIR / "file_index.json"
_FILE_INDEX_CACHE: Optional[List[Dict[str, Any]]] = None
_WORD_SPLIT_PATTERN = re.compile(r"[^\w]+", re.UNICODE)
_MATCH_PREFIXES = (
    "open file location of ",
    "open file location for ",
    "open file location ",
    "file location of ",
    "file location for ",
    "show file location of ",
    "show file location for ",
    "show file location ",
    "show location of ",
    "open location of ",
)
COMMAND_PREFIXES: tuple[str, ...] = tuple(_MATCH_PREFIXES)
_MIN_MATCH_SCORE = 3


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
        log(f"open_file_location: failed to load file index: {exc}")
        _FILE_INDEX_CACHE = []
    return _FILE_INDEX_CACHE


def _strip_prefixes(raw: str) -> str:
    working = raw.strip()
    lowered = working.lower()
    for prefix in COMMAND_PREFIXES:
        if lowered.startswith(prefix):
            working = working[len(prefix) :].strip()
            break
    return working


def _tokenize(value: str) -> List[str]:
    return [chunk for chunk in _WORD_SPLIT_PATTERN.split(value.lower()) if chunk]


def _score_entry(entry: Dict[str, Any], tokens: List[str]) -> int:
    if not tokens:
        return 0
    name = str(entry.get("name", "")).lower()
    folder = str(entry.get("folder", "")).lower()
    keywords = {str(k).lower() for k in entry.get("keywords", []) if isinstance(k, str)}
    score = 0
    for token in tokens:
        if not token:
            continue
        if token == name:
            score += 3
        elif token in name:
            score += 2
        if token == folder:
            score += 2
        if token in keywords:
            score += 1
    return score


def _pick_best_match(index: List[Dict[str, Any]], tokens: List[str]) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    best_mtime = -1.0
    for entry in index:
        score = _score_entry(entry, tokens)
        if score < _MIN_MATCH_SCORE:
            continue
        mtime = float(entry.get("mtime") or 0)
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        if score > best_score or (score == best_score and mtime > best_mtime):
            best = entry
            best_score = score
            best_mtime = mtime
    return best


def _platform_launch(file_path: Path, folder: Path, *, dry_run: bool = False) -> Optional[str]:
    if dry_run:
        return None
    try:
        if os.name == "nt":
            try:
                subprocess.run(["explorer", "/select,", str(file_path)], check=False)
                return None
            except OSError as exc:  # pragma: no cover - Windows explorer fallback
                log(f"open_file_location: explorer selection failed: {exc}")
                os.startfile(str(folder))  # type: ignore[arg-type]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except Exception as exc:  # pragma: no cover - platform launch safety net
        return str(exc)
    return None


def run_tool(target: str, context: Optional[Dict[str, Any]] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    del context
    original = (target or "").strip()
    cleaned = _strip_prefixes(original)
    if not cleaned:
        return {
            "status": "error",
            "message": "target is required",
            "requested": original,
        }
    try:
        index = _load_file_index()
        if not index:
            return {
                "status": "error",
                "message": "file index is unavailable",
                "requested": cleaned,
            }
        tokens = _tokenize(cleaned)
        if not tokens:
            return {
                "status": "error",
                "message": "Unable to derive search tokens from the target phrase.",
                "requested": cleaned,
            }
        match = _pick_best_match(index, tokens)
        if not match:
            return {
                "status": "error",
                "message": "Could not find a file whose location matches the target.",
                "requested": cleaned,
            }
        path_value = match.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            return {
                "status": "error",
                "message": "Matched file entry is missing a path.",
                "requested": cleaned,
            }
        file_path = Path(path_value)
        if not file_path.exists():
            return {
                "status": "error",
                "message": "File from index no longer exists on disk.",
                "requested": cleaned,
                "indexed_path": str(file_path),
            }
        folder = file_path.parent
        if not folder.exists():
            return {
                "status": "error",
                "message": "Folder for indexed file no longer exists on disk.",
                "requested": cleaned,
                "indexed_path": str(file_path),
            }
        launch_error = _platform_launch(file_path, folder, dry_run=dry_run)
        if launch_error:
            return {
                "status": "error",
                "message": f"Unable to open folder: {launch_error}",
                "requested": cleaned,
                "file": str(file_path),
            }
        response = {
            "status": "ok",
            "mode": "file_location",
            "requested": cleaned,
            "file": str(file_path),
            "folder": str(folder),
            "source": "file_index",
        }
        entry_summary = {
            "name": match.get("name"),
            "folder": match.get("folder"),
            "score": _score_entry(match, tokens),
        }
        response["match"] = entry_summary
        if dry_run:
            response["dry_run"] = True
        return response
    except Exception as exc:  # pragma: no cover - outer safety net
        log(f"open_file_location: unexpected error: {exc}")
        return {
            "status": "error",
            "message": "Unexpected error while trying to open the file location.",
            "requested": cleaned,
        }
