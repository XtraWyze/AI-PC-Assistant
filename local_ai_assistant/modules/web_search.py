"""Lightweight web search helper built for swapping providers easily."""
from __future__ import annotations

import html
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

import config
from utils.logger import log

DEFAULT_PROVIDER = "duckduckgo"
DEFAULT_BASE_URL = "https://duckduckgo.com/html/"
DEFAULT_TIMEOUT = 8


def _normalized_provider() -> str:
    provider = getattr(config, "SEARCH_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER
    return provider.strip().lower()


def _resolve_max_results(num_results: int | None) -> int:
    default_max = getattr(config, "SEARCH_MAX_RESULTS", 5)
    limit = num_results or default_max
    return max(1, min(limit, 10))  # avoid hammering the provider


def _resolve_timeout() -> int:
    timeout = getattr(config, "SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT)
    return max(2, int(timeout))


def _get_base_url() -> str:
    base_url = getattr(config, "SEARCH_BASE_URL", DEFAULT_BASE_URL)
    return base_url or DEFAULT_BASE_URL


def _duckduckgo_search(query: str, limit: int, timeout: int) -> List[Dict[str, str]]:
    params = {"q": query, "kl": "us-en"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
        )
    }
    response = requests.get(
        _get_base_url(),
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: List[Dict[str, str]] = []
    for block in soup.select("div.result"):
        if len(results) >= limit:
            break
        link = block.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        snippet_tag = block.select_one("a.result__snippet") or block.select_one("div.result__snippet")
        snippet_text = snippet_tag.get_text(" ").strip() if snippet_tag else ""
        results.append(
            {
                "title": html.unescape(link.get_text(" ").strip()),
                "url": link.get("href"),
                "snippet": html.unescape(snippet_text),
            }
        )
    return results


def web_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Return simple search results (title/url/snippet) using the configured provider."""
    cleaned = (query or "").strip()
    if not cleaned:
        log("web_search received an empty query.")
        return []

    provider = _normalized_provider()
    limit = _resolve_max_results(num_results)
    timeout = _resolve_timeout()

    try:
        if provider == "duckduckgo":
            results = _duckduckgo_search(cleaned, limit, timeout)
        else:
            log(f"Unsupported SEARCH_PROVIDER '{provider}'.")
            return []
    except requests.RequestException as exc:
        log(f"Web search network error: {exc}")
        return []
    except Exception as exc:  # pragma: no cover - defensive safety
        log(f"Unexpected web search failure: {exc}")
        return []

    if not results:
        log("No web search results returned.")
    return results


__all__ = ["web_search"]
