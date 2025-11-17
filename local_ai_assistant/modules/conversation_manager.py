"""In-memory conversation context utilities for multi-turn prompts."""
from __future__ import annotations

from typing import Dict, List, Optional

import config

ConversationTurn = Dict[str, str]

_HISTORY: List[ConversationTurn] = []


def add_turn(role: str, text: str) -> None:
    """Append a user/assistant turn to the rolling history."""
    role = role.strip().lower()
    if role not in {"user", "assistant"} or not text:
        return
    _HISTORY.append({"role": role, "text": text.strip()})
    max_turns = max(1, getattr(config, "MAX_CONTEXT_TURNS", 6) * 2)
    del _HISTORY[:-max_turns]


def get_recent_context(max_turns: Optional[int] = None) -> List[ConversationTurn]:
    """Return up to ``max_turns`` most recent turns (user+assistant)."""
    if max_turns is None:
        max_turns = getattr(config, "MAX_CONTEXT_TURNS", 6) * 2
    max_turns = max(1, max_turns)
    return _HISTORY[-max_turns:]


def clear_context() -> None:
    """Reset in-memory conversation state (does not touch disk memory)."""
    _HISTORY.clear()


def build_prompt_with_context(
    user_input: str,
    system_preamble: Optional[str] = None,
    assistant_directive: Optional[str] = None,
) -> str:
    """Assemble a prompt with optional system preamble, history, and directives."""
    lines: List[str] = []
    if system_preamble:
        lines.append(system_preamble.strip())

    assistant_name = getattr(config, "ASSISTANT_NAME", "Assistant")
    for turn in get_recent_context():
        speaker = "User" if turn["role"] == "user" else assistant_name
        lines.append(f"{speaker}: {turn['text']}")

    lines.append(f"User: {user_input}")
    if assistant_directive:
        lines.append(f"System: {assistant_directive.strip()}")
    lines.append(f"{assistant_name}:")
    return "\n".join(lines)
