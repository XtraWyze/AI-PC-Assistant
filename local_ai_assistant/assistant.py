"""Main entry point for the local AI assistant loop."""
from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional, Tuple

from colorama import Fore, Style, init as colorama_init

import config
from assistant.orchestrator import Orchestrator
from modules import commands_toolkit, conversation_manager, memory_manager
from utils.logger import log


colorama_init()


def _capture_text_input() -> str:
    prompt = f"{Fore.CYAN}You>{Style.RESET_ALL} "
    try:
        return input(prompt).strip()
    except EOFError:
        return "quit"


def initialize_subsystems() -> None:
    """Warm up disk-backed stores and reset transient context."""
    try:
        memory_manager.load_memory()
    except Exception as exc:  # pragma: no cover - file system issues
        log(f"Memory initialization failed: {exc}")
    try:
        conversation_manager.clear_context()
    except Exception as exc:  # pragma: no cover - defensive guard
        log(f"Conversation manager reset failed: {exc}")


def print_startup_banner() -> None:
    """Display basic runtime instructions for the current mode."""
    print(f"{Fore.GREEN}{config.ASSISTANT_NAME}{Style.RESET_ALL} ready for text input.")
    print("Type your request and press ENTER. Type 'quit' to exit.")


def _get_user_input() -> str:
    return _capture_text_input()






def _stream_and_deliver_reply(
    user_text: str,
    orchestrator: Orchestrator,
    conversation_state: List[Dict[str, str]],
    *,
    command_feedback: Optional[str] = None,
    assistant_directive_override: Optional[str] = None,
) -> str:
    """Stream assistant output directly to the console."""
    printed_any = False
    header_printed = False

    def _ensure_header() -> None:
        nonlocal header_printed
        if not header_printed:
            print(f"{Fore.GREEN}{config.ASSISTANT_NAME}:{Style.RESET_ALL} ", end="", flush=True)
            header_printed = True

    def chunk_consumer(chunk: str) -> Optional[bool]:
        nonlocal printed_any
        if not chunk:
            return True
        _ensure_header()
        printed_any = True
        print(chunk, end="", flush=True)
        return True

    reply = ""
    follow_up_used = False
    try:
        reply, follow_up_used = _process_user_query_streaming(
            user_text,
            orchestrator,
            conversation_state,
            chunk_consumer=chunk_consumer,
            command_feedback=command_feedback,
            assistant_directive_override=assistant_directive_override,
        )
    finally:
        if printed_any:
            print(Style.RESET_ALL)

    if follow_up_used or not printed_any:
        _ensure_header()
        print(f"{reply}{Style.RESET_ALL}")

    return reply

def _process_user_query_streaming(
    user_text: str,
    orchestrator: Orchestrator,
    conversation_state: List[Dict[str, str]],
    chunk_consumer: Optional[Callable[[str], Optional[bool]]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    command_feedback: Optional[str] = None,
    *,
    assistant_directive_override: Optional[str] = None,
) -> Tuple[str, bool]:
    """Stream assistant text while still updating memory + conversation."""

    memory_manager.add_history_entry(user_text)
    memory_manager.set_fact("last_query", user_text)
    memory_manager.add_conversation_turn("user", user_text)
    conversation_manager.add_turn("user", user_text)

    directive_parts: List[str] = []
    if command_feedback:
        directive_parts.append(
            "A trusted local automation command already executed in response to the latest user request. "
            f"Command result: {command_feedback}. In your reply, briefly acknowledge the action and continue "
            "helping the user without mentioning any separate subsystems."
        )
    if assistant_directive_override:
        directive_parts.append(assistant_directive_override)
    directive = " ".join(directive_parts) if directive_parts else None

    try:
        response_message, follow_up_used = orchestrator.stream_route(
            user_message=user_text,
            conversation_state=conversation_state,
            assistant_directive=directive,
            on_text_chunk=chunk_consumer,
            should_stop=should_stop,
        )
    except Exception as exc:
        log(f"Orchestrator streaming error: {exc}")
        fallback = "I ran into a local orchestration error while streaming. Please try again."
        conversation_state.append({"role": "assistant", "content": fallback})
        conversation_manager.add_turn("assistant", fallback)
        memory_manager.add_conversation_turn("assistant", fallback)
        return fallback, False

    reply = response_message.get("content", "") or "(No response from model.)"
    conversation_manager.add_turn("assistant", reply)
    memory_manager.add_conversation_turn("assistant", reply)
    return reply, follow_up_used


def _hydrate_saved_conversation(orchestrator: Optional[Orchestrator] = None) -> List[Dict[str, str]]:
    """Return conversation state seeded with the stored history + system prompt."""
    conversation_state: List[Dict[str, str]] = []
    system_preamble = getattr(config, "SYSTEM_PREAMBLE", None)
    if orchestrator:
        orchestrator.set_system_prompt(system_preamble)
    if system_preamble:
        conversation_state.append({"role": "system", "content": system_preamble.strip()})

    limit = max(1, getattr(config, "MAX_CONTEXT_TURNS", 6) * 2)
    for turn in memory_manager.get_recent_turns(limit=limit):
        role = (turn.get("role") or "").strip().lower()
        text = (turn.get("text") or "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        conversation_manager.add_turn(role, text)
        conversation_state.append({"role": role, "content": text})

    return conversation_state


def main() -> None:
    initialize_subsystems()
    print_startup_banner()
    orchestrator = Orchestrator()
    orchestrator.load_tools()
    conversation_state = _hydrate_saved_conversation(orchestrator)
    while True:
        try:
            user_text = _get_user_input()
            cleaned = user_text.strip()
            if not cleaned:
                continue
            lower_text = cleaned.lower()
            if lower_text in {"quit", "exit"}:
                log("Exiting on user request.")
                return
            print(f"{Fore.CYAN}You:{Style.RESET_ALL} {cleaned}")
            if config.ENABLE_COMMANDS and commands_toolkit.is_command(cleaned):
                reply = commands_toolkit.handle_command(cleaned, log)
                if getattr(config, "MERGE_COMMAND_RESPONSES", False):
                    _stream_and_deliver_reply(
                        cleaned,
                        orchestrator,
                        conversation_state,
                        command_feedback=reply,
                    )
                else:
                    print(f"{config.ASSISTANT_NAME}: {reply}")
                continue

            _stream_and_deliver_reply(
                cleaned,
                orchestrator,
                conversation_state,
            )
        except KeyboardInterrupt:
            print("\n")
            log("Keyboard interrupt received. Goodbye!")
            return
        except Exception as exc:  # pragma: no cover
            log(f"Unexpected error: {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # pragma: no cover
        log(f"Fatal error: {error}")
        sys.exit(1)
