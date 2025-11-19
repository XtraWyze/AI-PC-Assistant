"""Utility for opening websites in the user's browser."""
from __future__ import annotations

import os
import subprocess
import webbrowser
from typing import Any, Dict, Optional

_COMMON_URLS = {
    "facebook": "https://www.facebook.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
}

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _normalize_url(raw_url: str) -> str:
    cleaned = (raw_url or "").strip()
    if not cleaned:
        raise ValueError("url must be provided")
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    key = cleaned.lower()
    if key in _COMMON_URLS:
        return _COMMON_URLS[key]
    if "." in cleaned:
        return f"https://{cleaned}"
    return f"https://{cleaned}.com"


def _open_default(url: str) -> Dict[str, Any]:
    webbrowser.open(url)
    return {"status": "ok", "url": url, "browser": "default"}


def open_website(url: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """Open the target URL via Chrome when requested, otherwise via the default browser."""
    normalized = _normalize_url(url)
    browser_name = (browser or "").strip().lower()

    if not browser_name or browser_name in {"default", "system"}:
        return _open_default(normalized)

    if browser_name == "chrome":
        chrome_path = next((path for path in _CHROME_PATHS if os.path.exists(path)), None)
        if chrome_path:
            subprocess.Popen([chrome_path, normalized], shell=False)
            return {"status": "ok", "url": normalized, "browser": "chrome"}
        fallback = _open_default(normalized)
        fallback["status"] = "fallback"
        fallback["reason"] = "chrome_not_found"
        return fallback

    fallback = _open_default(normalized)
    fallback["status"] = "fallback"
    fallback["reason"] = "unknown_browser"
    return fallback
