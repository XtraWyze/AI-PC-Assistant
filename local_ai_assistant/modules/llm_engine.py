"""Simple wrapper around the local Ollama HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, Generator, Iterable, List, Optional

import requests
import simplejson as json

import config
from utils.logger import log

LOGGER = logging.getLogger(__name__)


def _stream_ollama(prompt: str) -> Generator[Dict[str, str], None, None]:
    """Stream chunks from the Ollama /api/generate endpoint."""
    url = f"{config.OLLAMA_HOST.rstrip('/')}/api/generate"
    payload = {"model": config.LLM_MODEL, "prompt": prompt, "stream": True}
    with requests.post(url, json=payload, stream=True, timeout=90) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            yield data


def stream_response(prompt: str) -> Generator[str, None, None]:
    """Yield response text incrementally as it streams from Ollama."""
    if not prompt:
        return

    try:
        for packet in _stream_ollama(prompt):
            chunk = packet.get("response", "")
            if chunk:
                yield chunk
            if packet.get("done"):
                break
    except requests.exceptions.RequestException as exc:
        error_msg = (
            "LLM backend unreachable. Ensure Ollama is running locally and the model is pulled. "
            f"Details: {exc}"
        )
        log(error_msg)
        yield error_msg
    except json.JSONDecodeError as exc:  # pragma: no cover
        error_msg = f"Invalid response from Ollama. Details: {exc}"
        log(error_msg)
        yield error_msg


def generate_response(prompt: str) -> str:
    """Send a prompt to the local LLM and return the generated text."""
    text = "".join(stream_response(prompt or ""))
    text = text.strip()
    return text or "(No response from model.)"


def chat(
    *,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    stream: bool = False,
    timeout: int = 90,
) -> Dict[str, Any]:
    """Call Ollama's /api/chat endpoint with optional tool definitions."""
    if not messages:
        raise ValueError("chat() requires at least one message.")

    url = f"{(base_url or config.OLLAMA_HOST).rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        error_msg = (
            "LLM backend unreachable. Ensure Ollama is running locally and the model is pulled. "
            f"Details: {exc}"
        )
        log(error_msg)
        raise RuntimeError(error_msg) from exc
    except json.JSONDecodeError as exc:  # pragma: no cover
        error_msg = f"Invalid response from Ollama. Details: {exc}"
        log(error_msg)
        raise RuntimeError(error_msg) from exc


def chat_stream(
    *,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: int = 90,
) -> Generator[Dict[str, Any], None, None]:
    """Yield streaming chat chunks from Ollama's /api/chat endpoint."""
    if not messages:
        raise ValueError("chat_stream() requires at least one message.")

    url = f"{(base_url or config.OLLAMA_HOST).rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    try:
        with requests.post(url, json=payload, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:  # pragma: no cover
                    log(f"Invalid JSON chunk from Ollama: {exc}")
                    continue
                yield data
    except requests.RequestException as exc:
        error_msg = (
            "LLM backend unreachable. Ensure Ollama is running locally and the model is pulled. "
            f"Details: {exc}"
        )
        log(error_msg)
        yield {"error": error_msg, "done": True}
