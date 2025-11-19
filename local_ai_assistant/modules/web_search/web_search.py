"""Lightweight web search helper with SerpAPI + DuckDuckGo fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 10  # seconds
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_ENGINE = "duckduckgo"
SERPAPI_DEMO_KEY = "demo"
DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
)


@dataclass
class SearchOutcome:
    payload: Optional[Dict[str, Any]]
    error: Optional[str]
    network_error: bool = False


def run_search(query: str) -> Dict[str, Any]:
    """Return top search results while surviving offline scenarios."""
    cleaned = (query or "").strip()
    base = {"query": cleaned, "results": []}
    if not cleaned:
        base["error"] = "empty query"
        return base

    serp_outcome = _query_serpapi(cleaned)
    if serp_outcome.payload:
        return serp_outcome.payload

    duck_outcome = _scrape_duckduckgo(cleaned)
    if duck_outcome.payload:
        return duck_outcome.payload

    if serp_outcome.network_error and duck_outcome.network_error:
        base["error"] = "no internet"
    else:
        base["error"] = duck_outcome.error or serp_outcome.error or "no results"
    return base


def _query_serpapi(query: str) -> SearchOutcome:
    params = {
        "engine": SERPAPI_ENGINE,
        "q": query,
        "no_cache": "true",
        "api_key": SERPAPI_DEMO_KEY,
    }
    try:
        response = requests.get(
            SERPAPI_ENDPOINT,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return SearchOutcome(None, str(exc), network_error=True)
    except ValueError as exc:  # Invalid JSON
        return SearchOutcome(None, f"SerpAPI decode error: {exc}")

    organic = data.get("organic_results") or []
    results = _normalize_results(organic)
    if not results:
        return SearchOutcome(None, "SerpAPI returned no results")

    return SearchOutcome({"query": query, "results": results}, None)


def _scrape_duckduckgo(query: str) -> SearchOutcome:
    params = {"q": query}
    try:
        response = requests.get(
            DUCKDUCKGO_HTML,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return SearchOutcome(None, str(exc), network_error=True)

    soup = BeautifulSoup(response.text, "html.parser")
    entries = []
    for block in soup.select("div.result"):
        link_tag = block.select_one("a.result__a") or block.select_one("a.result__url")
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        link = link_tag.get("href") or ""
        snippet_tag = block.select_one("a.result__snippet") or block.select_one("div.result__snippet")
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        if not (title and link):
            continue
        entries.append({"title": title, "link": link, "snippet": snippet})
        if len(entries) == 5:
            break

    if not entries:
        return SearchOutcome(None, "DuckDuckGo returned no results")

    return SearchOutcome({"query": query, "results": entries}, None)


def _normalize_results(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for item in items:
        title = item.get("title") or ""
        link = item.get("link") or item.get("url") or ""
        snippet = item.get("snippet") or item.get("description") or ""
        if not (title and link):
            continue
        normalized.append({
            "title": str(title).strip(),
            "link": str(link).strip(),
            "snippet": str(snippet).strip(),
        })
        if len(normalized) == 5:
            break
    return normalized
