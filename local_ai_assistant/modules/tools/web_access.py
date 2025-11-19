"""Web access helpers invoked via the LLM tool system."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

_DDG_HTML_ENDPOINT = "https://duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
_TIMEOUT_SECONDS = 12
_MAX_RESULTS_LIMIT = 10
_PRICE_HINT_WORDS = ("price", "cost", "usd", "dollar", "msrp", "$")
_PRICE_PATTERN = re.compile(r"\$\s*\d{2,3}(?:,\d{3})*(?:\.\d{2})?", re.IGNORECASE)
_STRIP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "canvas",
    "form",
    "input",
    "button",
}


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_max_results(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 5
    if count < 1:
        return 1
    return min(count, _MAX_RESULTS_LIMIT)


def _resolve_href(raw_url: Any) -> str:
    if not raw_url:
        return ""
    url = str(raw_url).strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        target = query.get("uddg")
        if target:
            return unquote(target[0])
    return url


def _extract_prices(text: str) -> List[str]:
    if not text:
        return []
    return _PRICE_PATTERN.findall(text)


def _price_value(price_text: str) -> Optional[float]:
    if not price_text:
        return None
    digits = price_text.replace("$", "").replace(",", "").strip()
    try:
        return float(digits)
    except ValueError:
        return None


def _should_require_price(query: str) -> bool:
    lowered = query.lower()
    return any(hint in lowered for hint in _PRICE_HINT_WORDS)


def _capture_numeric_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    parts = [part.strip(".,") for part in query.lower().split() if part.strip()]
    for part in parts:
        if any(ch.isdigit() for ch in part):
            tokens.append(part)
    return tokens


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in list(_STRIP_TAGS):
        for node in soup.find_all(tag):
            node.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned)


def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Return DuckDuckGo search results and flag entries that include explicit price mentions."""
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("query must be provided")

    limit = _normalize_max_results(max_results)
    params = {"q": normalized_query, "kl": "us-en"}
    require_price = _should_require_price(normalized_query)
    numeric_tokens = _capture_numeric_tokens(normalized_query)

    try:
        response = requests.get(
            _DDG_HTML_ENDPOINT,
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"results": [], "error": f"DuckDuckGo search failed: {exc}"}

    soup = BeautifulSoup(response.text, "html.parser")
    results: List[Dict[str, str]] = []

    for block in soup.select("div.result"):
        anchor = block.select_one("a.result__a")
        if not anchor:
            continue
        url = _resolve_href(anchor.get("href"))
        if not url:
            continue
        title = anchor.get_text(strip=True)
        snippet_node = block.select_one(".result__snippet") or block.select_one(".result__body")
        snippet = ""
        if snippet_node:
            snippet = _collapse_whitespace(snippet_node.get_text(" ", strip=True))
        combined_text = f"{title} {snippet}".strip()
        combined_lower = combined_text.lower()
        if numeric_tokens and not all(token in combined_lower for token in numeric_tokens):
            continue
        prices = _extract_prices(combined_text)
        if require_price and not prices:
            continue

        entry: Dict[str, Any] = {"title": title, "url": url, "snippet": snippet}
        if prices:
            entry["price_matches"] = prices
            first_value = _price_value(prices[0])
            if first_value is not None:
                entry["price_value"] = first_value

        results.append(entry)
        if len(results) >= limit:
            break

    return {"results": results}


def fetch_page(url: str) -> Dict[str, Any]:
    """Download a web page and return visible text content."""
    normalized_url = (url or "").strip()
    if not normalized_url:
        raise ValueError("url must be provided")

    try:
        response = requests.get(normalized_url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"url": normalized_url, "text": "", "length": 0, "error": f"Fetch failed: {exc}"}

    text = _extract_visible_text(response.text)
    return {"url": normalized_url, "text": text, "length": len(text)}


def summarize_page(url: str, max_chars: int = 1500) -> Dict[str, Any]:
    """Fetch a page then return a truncated excerpt of the visible text."""
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = 1500
    if limit < 1:
        limit = 1

    page_data = fetch_page(url)
    if page_data.get("error"):
        return page_data

    text = page_data.get("text", "")
    excerpt = text[:limit]
    return {
        "url": page_data.get("url", (url or "").strip()),
        "excerpt": excerpt,
        "length": page_data.get("length", len(text)),
        "truncated_to": limit,
    }


# Example usage for manual tests:
# User: "Wyzer, search the web for the best budget GPUs right now."
# Tool call: {"tool": "search_web", "arguments": {"query": "best budget GPU 2025", "max_results": 5}}
# User: "Wyzer, open the top result and summarize the page for me."
# Tool call: {"tool": "summarize_page", "arguments": {"url": "<top-result-url>", "max_chars": 1500}}
