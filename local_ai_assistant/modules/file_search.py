"""Keyword-based file search powered by the local LLM."""
from __future__ import annotations

from typing import List

from utils.logger import log as default_logger

from . import file_indexer, llm_engine

KEYWORD_PROMPT = (
    "System: You are a file search helper. Given a user query about files on their PC, "
    "output 5-10 important keywords separated by commas, with no explanations or extra text.\n"
    "User: {query}\nAssistant:"
)


def extract_keywords_llm(natural_query: str, logger=default_logger) -> List[str]:
    """Expand a natural language query into concise search keywords."""
    if not natural_query:
        return []
    prompt = KEYWORD_PROMPT.format(query=natural_query.strip())
    raw = llm_engine.generate_response(prompt)
    tokens: List[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        token = chunk.strip().lower()
        if len(token) < 3:
            continue
        if token not in tokens:
            tokens.append(token)
    logger(f"LLM keywords for '{natural_query}': {tokens}")
    return tokens


def _score_entry(entry: dict, keywords: List[str]) -> int:
    if not keywords:
        return 0
    entry_keywords = set(entry.get("keywords", []))
    name_tokens = set(file_indexer.tokenize_text_for_keywords(entry.get("name", "")))
    folder_tokens = set(file_indexer.tokenize_text_for_keywords(entry.get("folder", "")))
    score = 0
    for keyword in keywords:
        if (
            keyword in entry_keywords
            or keyword in name_tokens
            or keyword in folder_tokens
        ):
            score += 1
    return score


def search_files(natural_query: str, logger=default_logger, max_results: int = 10) -> List[dict]:
    """Return top file matches for a natural query."""
    index = file_indexer.load_file_index()
    if not index:
        logger("File search requested but index is empty. Run an indexing command first.")
        return []

    llm_keywords = extract_keywords_llm(natural_query, logger=logger)
    raw_tokens = file_indexer.tokenize_text_for_keywords(natural_query)
    keywords = raw_tokens
    for token in llm_keywords:
        if token not in keywords:
            keywords.append(token)

    scored: List[dict] = []
    for entry in index:
        score = _score_entry(entry, keywords)
        if score <= 0:
            continue
        enriched = entry.copy()
        enriched["score"] = score
        scored.append(enriched)

    scored.sort(key=lambda item: (item["score"], item.get("mtime", 0.0)), reverse=True)
    return scored[:max_results]


def format_search_results_for_speech(results: List[dict]) -> str:
    if not results:
        return "I couldn't find any files matching that description."
    total = len(results)
    phrases = []
    for idx, entry in enumerate(results[:3], start=1):
        location = entry.get("folder") or "Unknown location"
        phrases.append(f"{idx}) {entry.get('name', 'Unnamed')} in {location}")
    joined = " ".join(phrases)
    noun = "file" if total == 1 else "files"
    return f"I found {total} {noun}. Top results: {joined}."


def format_search_results_for_console(results: List[dict]) -> str:
    if not results:
        return "No files matched your query."
    lines = []
    for idx, entry in enumerate(results, start=1):
        path = entry.get("path", "")
        name = entry.get("name", "Unnamed")
        score = entry.get("score", 0)
        lines.append(f"{idx}) {name}  |  score={score}  |  {path}")
    return "\n".join(lines)
