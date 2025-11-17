"""Local file indexing utilities for the assistant."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, List, Optional, Set

from utils.logger import log as default_logger

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FILE_INDEX_PATH = DATA_DIR / "file_index.json"
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
    ".ini",
    ".cfg",
    ".conf",
    ".bat",
    ".ps1",
    ".rtf",
}
CONTENT_SAMPLE_BYTES = 4096
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "build",
    "dist",
}


def get_default_paths() -> List[Path]:
    """Return the default folders the assistant is allowed to scan."""
    home = Path.home()
    candidates = [
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
    ]
    return [path for path in candidates if path.exists() and path.is_dir()]


def tokenize_text_for_keywords(text: str) -> List[str]:
    """Break text into lowercase keywords with punctuation removed."""
    cleaned = []
    current = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
        else:
            current.append(" ")
    merged = "".join(current)
    seen = set()
    for token in merged.split():
        if len(token) < 3:
            continue
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _iter_search_paths(extra_paths: Optional[Iterable[Path]] = None) -> List[Path]:
    paths = get_default_paths()
    if extra_paths:
        for raw in extra_paths:
            try:
                resolved = Path(raw).expanduser().resolve()
            except OSError:
                continue
            if resolved.is_dir() and resolved not in paths:
                paths.append(resolved)
    return paths


def _sample_file_text(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(CONTENT_SAMPLE_BYTES)
    except (OSError, UnicodeDecodeError):
        return ""


def _build_keywords(path: Path, content_sample: str) -> List[str]:
    parts = [path.name, path.stem, path.suffix.lstrip("."), path.parent.name]
    if content_sample:
        parts.append(content_sample)
    combined = " ".join(filter(None, parts))
    return tokenize_text_for_keywords(combined)


def _create_entry(path: Path, size: int, mtime: float, keywords: List[str]) -> Optional[dict]:
    return {
        "path": str(path),
        "name": path.name,
        "ext": path.suffix.lower(),
        "folder": path.parent.name,
        "size": int(size),
        "mtime": float(mtime),
        "keywords": keywords,
    }


def build_file_index(
    extra_paths: Optional[Iterable[Path]] = None,
    max_file_size_mb: int = 50,
    logger=default_logger,
) -> List[dict]:
    """Walk allowed folders, capture metadata, and persist the index."""
    max_bytes = max(1, int(max_file_size_mb)) * 1024 * 1024
    entries: List[dict] = []
    seen_files: Set[str] = set()
    visited_dirs: Set[str] = set()

    search_paths = _iter_search_paths(extra_paths)
    if not search_paths:
        logger("No default directories were found for indexing.")
        save_file_index([])
        return []

    logger(
        "Starting file index scan in: %s"
        % ", ".join(str(path) for path in search_paths)
    )

    processed = 0
    for base_path in search_paths:
        logger(f"Scanning {base_path} ...")
        for root, dirs, files in os.walk(base_path):
            root_path = Path(root)
            normalized_root = _normalize_path(root_path)
            if normalized_root in visited_dirs:
                dirs[:] = []
                continue
            visited_dirs.add(normalized_root)

            dirs[:] = _filter_child_dirs(root_path, dirs, visited_dirs)

            for filename in files:
                file_path = root_path / filename
                stats = _safe_stat(file_path)
                if not stats:
                    continue
                if stats.st_size > max_bytes:
                    continue
                normalized_file = _normalize_path(file_path)
                if normalized_file in seen_files:
                    continue
                seen_files.add(normalized_file)
                content = _sample_file_text(file_path)
                keywords = _build_keywords(file_path, content)
                if not keywords:
                    continue
                entry = _create_entry(file_path, stats.st_size, stats.st_mtime, keywords)
                if entry:
                    entries.append(entry)
                    processed += 1
                    if processed % 250 == 0:
                        logger(f"Indexed {processed} files so far ...")

    save_file_index(entries)
    logger(f"Indexing complete. {len(entries)} files captured.")
    return entries


def _filter_child_dirs(root_path: Path, dirs: List[str], visited_dirs: Set[str]) -> List[str]:
    kept: List[str] = []
    for dirname in dirs:
        child = root_path / dirname
        normalized_child = _normalize_path(child)
        if normalized_child in visited_dirs:
            continue
        if _should_skip_dir(child):
            continue
        kept.append(dirname)
    return kept


def _should_skip_dir(path: Path) -> bool:
    name = path.name.lower()
    if name in SKIP_DIR_NAMES:
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    return False


def _safe_stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def _normalize_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def load_file_index() -> List[dict]:
    if not FILE_INDEX_PATH.exists():
        return []
    try:
        with FILE_INDEX_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []


def save_file_index(entries: List[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with FILE_INDEX_PATH.open("w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
