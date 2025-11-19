"""Main entry point for the local AI assistant loop."""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from colorama import Fore, Style, init as colorama_init
from pynput import keyboard

import config
from assistant.orchestrator import Orchestrator
from modules import (
    commands_toolkit,
    conversation_manager,
    hotword_detector,
    llm_engine,
    memory_manager,
    stt_vosk,
    tts_engine,
)
from utils.logger import log


colorama_init()

_FORCE_TEXT_MODE = os.environ.get("WYZER_FORCE_TEXT_MODE", "").strip().lower() in {"1", "true", "yes", "text"}
if _FORCE_TEXT_MODE:
    config.MODE = "text"
    config.ENABLE_HOTWORD = False

# Global interrupt flag
_interrupt_requested = threading.Event()
_interrupt_key = config.INTERRUPT_KEY if hasattr(config, 'INTERRUPT_KEY') else 'esc'
_voice_listener_running = False
_voice_listener_thread: Optional[threading.Thread] = None
_voice_listener_stop_event: Optional[threading.Event] = None


def _voice_interrupt_listener(stop_event: threading.Event) -> None:
    """Background thread that listens for voice interrupt commands."""
    global _voice_listener_running

    if not getattr(config, "ENABLE_VOICE_INTERRUPTS", False):
        _voice_listener_running = False
        return
    if not config.USE_STT:
        log("Voice interrupts require USE_STT=True. Ignoring request.")
        _voice_listener_running = False
        return

    phrases = getattr(config, "VOICE_INTERRUPT_PHRASES", [])
    if not phrases:
        log("Voice interrupts enabled but no phrases configured. Disabling listener.")
        _voice_listener_running = False
        return

    try:
        detector = stt_vosk.VoiceInterruptDetector(phrases)
    except Exception as exc:
        log(f"Unable to initialize voice interrupt detector: {exc}")
        _voice_listener_running = False
        return

    log("Voice interrupt listener running. Say 'stop' to cut off playback.")

    try:
        try:
            detected = detector.listen_continuous(stop_event=stop_event)
        except Exception as exc:  # pragma: no cover - audio hardware
            log(f"Voice interrupt listener error: {exc}")
            detected = False

        if detected and not _interrupt_requested.is_set():
            log("Voice interrupt detected.")
            _interrupt_requested.set()
            try:
                tts_engine.stop_audio()
            except Exception:
                pass
    finally:
        detector.close()
        _voice_listener_running = False


def _start_voice_interrupt_listener() -> None:
    """Start the voice interrupt listener thread."""
    global _voice_listener_running, _voice_listener_thread, _voice_listener_stop_event

    if _voice_listener_running:
        return

    if not getattr(config, "ENABLE_VOICE_INTERRUPTS", False):
        return

    if not config.USE_STT:
        return

    if not getattr(config, "VOICE_INTERRUPT_PHRASES", None):
        return

    _voice_listener_stop_event = threading.Event()
    _voice_listener_running = True
    _voice_listener_thread = threading.Thread(
        target=_voice_interrupt_listener,
        args=(_voice_listener_stop_event,),
        daemon=True,
    )
    _voice_listener_thread.start()


def _stop_voice_interrupt_listener() -> None:
    """Stop the voice interrupt listener thread."""
    global _voice_listener_running, _voice_listener_thread, _voice_listener_stop_event
    _voice_listener_running = False
    if _voice_listener_stop_event:
        _voice_listener_stop_event.set()
    if _voice_listener_thread and _voice_listener_thread.is_alive():
        _voice_listener_thread.join(timeout=1.0)
    _voice_listener_thread = None
    _voice_listener_stop_event = None


def _on_key_press(key):
    """Handle key press events for interrupt."""
    try:
        # Check for ESC key or configured interrupt key
        if key == keyboard.Key.esc:
            _interrupt_requested.set()
            return
        # Check for specific character keys
        if hasattr(key, 'char') and key.char and key.char.lower() == _interrupt_key.lower():
            _interrupt_requested.set()
    except AttributeError:
        pass


def _capture_text_input() -> str:
    prompt = f"{Fore.CYAN}You>{Style.RESET_ALL} "
    try:
        return input(prompt).strip()
    except EOFError:
        return "quit"


def _speak_text(text: str) -> None:
    """Play a one-off TTS phrase with console fallback."""
    message = (text or "").strip()
    if not message:
        return
    print(f"{Fore.GREEN}{config.ASSISTANT_NAME}:{Style.RESET_ALL} {message}")
    if not config.USE_TTS:
        return
    try:
        tts_engine.speak(message)
    except Exception as exc:  # pragma: no cover - device issues
        log(f"Immediate TTS failed: {exc}")


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
    if getattr(config, "USE_TTS", False):
        try:
            tts_engine.init_tts()
        except Exception as exc:  # pragma: no cover - device/dependency issues
            log(f"TTS initialization failed: {exc}. Disabling USE_TTS for this session.")
            config.USE_TTS = False
    if getattr(config, "USE_STT", False):
        try:
            stt_vosk.init_recognizer()
        except Exception as exc:  # pragma: no cover - missing model/hardware
            log(f"STT initialization failed: {exc}. Disabling voice features for this session.")
            config.USE_STT = False
            config.ENABLE_HOTWORD = False
            config.ENABLE_VOICE_INTERRUPTS = False


def print_startup_banner() -> None:
    """Display basic runtime instructions for the current mode."""
    mode = getattr(config, "MODE", "voice").strip().lower()
    print(f"{Fore.GREEN}{config.ASSISTANT_NAME}{Style.RESET_ALL} ready in {mode} mode.")
    if mode == "text":
        print("Type your request and press ENTER. Say 'quit' to exit.")
        return
    if getattr(config, "ENABLE_HOTWORD", False):
        hotword = getattr(config, "HOTWORD", "Hey Wyzer")
        print(f"Say '{hotword}' to wake the assistant, or type 'quit' to exit.")
    elif getattr(config, "ENABLE_PUSH_TO_TALK", False):
        print(getattr(config, "PUSH_TO_TALK_PROMPT", "Press ENTER and speak..."))
    else:
        print("Press ENTER when you want to speak.")


def _capture_voice_input() -> str:
    if not config.USE_STT:
        log("Voice mode requires USE_STT=True. Falling back to empty input.")
        return ""

    if config.ENABLE_HOTWORD:
        detected = hotword_detector.listen_for_hotword(
            config_module=config,
            logger=log,
            timeout_seconds=getattr(config, "HOTWORD_TIMEOUT_SECONDS", None),
        )
        if not detected:
            return ""
        _speak_text("I'm listening.")
    else:
        if config.ENABLE_PUSH_TO_TALK:
            input(config.PUSH_TO_TALK_PROMPT)
        else:
            input("Press ENTER to speak...")

    log("Listening for your query...")
    text = stt_vosk.listen_once(timeout_seconds=config.MAX_LISTEN_SECONDS)
    if text:
        log(f"Heard: {text}")
    else:
        log("No speech recognized.")
    return text.strip()


def _get_user_input() -> str:
    mode = config.MODE.lower()
    if mode == "voice":
        return _capture_voice_input()
    return _capture_text_input()


_SENTENCE_PATTERN = re.compile(r"(?<=[.!?\n])")


def _extract_complete_segments(buffer: str) -> Tuple[List[str], str]:
    """Return completed sentences and the remaining buffer."""
    segments: List[str] = []
    start = 0
    for match in _SENTENCE_PATTERN.finditer(buffer):
        end = match.end()
        segment = buffer[start:end].strip()
        if segment:
            segments.append(segment)
        start = end
    remainder = buffer[start:]
    return segments, remainder


def _iter_tts_chunks(text: str, max_chunk_chars: int = 240) -> Iterable[str]:
    """Yield trimmed chunks sized for low-latency speech playback."""
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return

    segments, remainder = _extract_complete_segments(normalized)
    if remainder.strip():
        segments.append(remainder.strip())

    for segment in segments:
        chunk = segment.replace("\n", " ").strip()
        if not chunk:
            continue
        while len(chunk) > max_chunk_chars:
            split_at = chunk.rfind(" ", 0, max_chunk_chars)
            if split_at <= 0:
                split_at = max_chunk_chars
            yield chunk[:split_at].strip()
            chunk = chunk[split_at:].strip()
        if chunk:
            yield chunk


class TTSPipeline:
    """Handles queueing, synthesis, and playback for streamed speech."""

    def __init__(self) -> None:
        self.enabled = config.USE_TTS
        self.interrupted = False
        if not self.enabled:
            self.mode: Optional[str] = None
            return

        if tts_engine.supports_buffered_audio():
            self.mode = "buffered"
            self.text_queue: "queue.Queue[Optional[str]]" = queue.Queue()
            self.audio_queue: "queue.Queue[Optional[Tuple[Any, int]]]" = queue.Queue()
            self.threads = [
                threading.Thread(target=self._synth_worker, daemon=True),
                threading.Thread(target=self._play_worker, daemon=True),
            ]
            for thread in self.threads:
                thread.start()
        else:
            self.mode = "simple"
            self.text_queue = queue.Queue()
            self.threads = [threading.Thread(target=self._speak_worker, daemon=True)]
            self.threads[0].start()

    def enqueue(self, text: str) -> None:
        if not self.enabled or not text or self.interrupted:
            return
        self.text_queue.put(text)

    def interrupt(self) -> None:
        """Stop all ongoing speech synthesis and playback."""
        if not self.enabled:
            return
        self.interrupted = True
        # Stop any currently playing audio immediately
        tts_engine.stop_audio()
        # Clear queues
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
                self.text_queue.task_done()
            except queue.Empty:
                break
        if self.mode == "buffered":
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                except queue.Empty:
                    break

    def close(self) -> None:
        if not self.enabled:
            return
        self.text_queue.put(None)
        self.text_queue.join()
        if self.mode == "buffered":
            self.audio_queue.join()
        for thread in self.threads:
            thread.join(timeout=2)

    # Worker implementations -------------------------------------------------
    def _speak_worker(self) -> None:  # pragma: no cover - runtime behavior
        while True:
            text = self.text_queue.get()
            try:
                if text is None:
                    self.text_queue.task_done()
                    return
                if not self.interrupted:
                    tts_engine.speak(text)
                    # Check if interrupted during speech
                    if _interrupt_requested.is_set():
                        self.interrupted = True
                        tts_engine.stop_audio()
            except Exception as exc:
                log(f"TTS playback failed: {exc}")
            finally:
                if text is not None:
                    self.text_queue.task_done()

    def _synth_worker(self) -> None:  # pragma: no cover
        while True:
            text = self.text_queue.get()
            try:
                if text is None:
                    self.audio_queue.put(None)
                    self.text_queue.task_done()
                    return
                if not self.interrupted:
                    audio = tts_engine.synthesize_audio(text)
                    self.audio_queue.put(audio)
            except Exception as exc:
                log(f"TTS synthesis failed: {exc}")
            finally:
                if text is not None:
                    self.text_queue.task_done()

    def _play_worker(self) -> None:  # pragma: no cover
        while True:
            audio = self.audio_queue.get()
            try:
                if audio is None:
                    self.audio_queue.task_done()
                    return
                if not self.interrupted:
                    buffer, sample_rate = audio
                    tts_engine.play_audio(buffer, sample_rate)
                    # Check if interrupted during playback
                    if _interrupt_requested.is_set():
                        self.interrupted = True
                        tts_engine.stop_audio()
            except Exception as exc:
                log(f"TTS playback failed: {exc}")
            finally:
                if audio is not None:
                    self.audio_queue.task_done()


def stream_llm_reply(prompt: str) -> str:
    """Stream LLM output to console and TTS for faster feedback."""
    print(f"{Fore.GREEN}{config.ASSISTANT_NAME}:{Style.RESET_ALL} ", end="", flush=True)
    tts_worker = TTSPipeline()
    aggregated: List[str] = []
    buffer = ""
    _interrupt_requested.clear()
    
    # Start voice interrupt listener
    _start_voice_interrupt_listener()

    def enqueue(text: str) -> None:
        if tts_worker:
            tts_worker.enqueue(text)

    try:
        for chunk in llm_engine.stream_response(prompt):
            # Check for interrupt
            if _interrupt_requested.is_set():
                if tts_worker:
                    tts_worker.interrupt()
                print(f"\n{Fore.YELLOW}[Interrupted]{Style.RESET_ALL}")
                aggregated.append(" [interrupted]")
                break
            
            if not chunk:
                continue
            aggregated.append(chunk)
            print(chunk, end="", flush=True)
            buffer += chunk
            completed, buffer = _extract_complete_segments(buffer)
            for piece in completed:
                enqueue(piece)
        
        # Final check for interrupt
        if not _interrupt_requested.is_set():
            leftover = buffer.strip()
            if leftover:
                enqueue(leftover)
        else:
            if tts_worker:
                tts_worker.interrupt()
        
        print(Style.RESET_ALL)
        return "".join(aggregated).strip() or "(No response from model.)"
    finally:
        if tts_worker:
            tts_worker.close()
        _stop_voice_interrupt_listener()
        _interrupt_requested.clear()


def _deliver_text_reply(text: str) -> None:
    print(f"{Fore.GREEN}{config.ASSISTANT_NAME}:{Style.RESET_ALL} {text}")
    if config.USE_TTS:
        _play_reply_with_streaming_tts(text)


def _stream_and_deliver_reply(
    user_text: str,
    orchestrator: Orchestrator,
    conversation_state: List[Dict[str, str]],
    *,
    command_feedback: Optional[str] = None,
    assistant_directive_override: Optional[str] = None,
) -> str:
    """Stream assistant output to console + TTS for low latency."""
    tts_worker = TTSPipeline()
    printed_any = False
    header_printed = False
    interrupted = False
    buffer = ""

    _interrupt_requested.clear()
    _start_voice_interrupt_listener()

    def _ensure_header() -> None:
        nonlocal header_printed
        if not header_printed:
            print(f"{Fore.GREEN}{config.ASSISTANT_NAME}:{Style.RESET_ALL} ", end="", flush=True)
            header_printed = True

    def chunk_consumer(chunk: str) -> Optional[bool]:
        nonlocal printed_any, buffer, interrupted
        if not chunk:
            return True
        if _interrupt_requested.is_set():
            interrupted = True
            tts_worker.interrupt()
            return False
        _ensure_header()
        printed_any = True
        print(chunk, end="", flush=True)
        buffer += chunk
        completed, remainder = _extract_complete_segments(buffer)
        buffer = remainder
        for piece in completed:
            tts_worker.enqueue(piece)
        return True

    def should_stop() -> bool:
        return _interrupt_requested.is_set()

    reply = ""
    follow_up_used = False
    try:
        reply, follow_up_used = _process_user_query_streaming(
            user_text,
            orchestrator,
            conversation_state,
            chunk_consumer=chunk_consumer,
            should_stop=should_stop,
            command_feedback=command_feedback,
            assistant_directive_override=assistant_directive_override,
        )
    finally:
        interrupted = interrupted or _interrupt_requested.is_set()
        # If we streamed chunks successfully, flush any leftover text
        if not interrupted and buffer.strip():
            tts_worker.enqueue(buffer.strip())
        if printed_any or interrupted:
            print(Style.RESET_ALL)
        tts_worker.close()
        _stop_voice_interrupt_listener()
        _interrupt_requested.clear()

    if interrupted:
        print(f"{Fore.YELLOW}[Interrupted]{Style.RESET_ALL}")
        return reply

    if follow_up_used or not printed_any:
        _ensure_header()
        print(reply)
        if config.USE_TTS:
            _play_reply_with_streaming_tts(reply)

    return reply


def _play_reply_with_streaming_tts(text: str) -> None:
    """Stream assistant replies through TTS with optional voice interrupts."""
    content = (text or "").strip()
    if not content or not config.USE_TTS:
        return

    tts_worker = TTSPipeline()
    _interrupt_requested.clear()
    _start_voice_interrupt_listener()

    try:
        for chunk in _iter_tts_chunks(content):
            if _interrupt_requested.is_set():
                tts_worker.interrupt()
                break
            tts_worker.enqueue(chunk)
    finally:
        tts_worker.close()
        _stop_voice_interrupt_listener()
        _interrupt_requested.clear()


def _listen_for_follow_up_query() -> str:
    """Give the user a brief post-reply window to ask another question."""
    if getattr(config, "MODE", "voice").lower() != "voice":
        return ""
    if not (config.USE_TTS and config.USE_STT):
        return ""
    window = float(getattr(config, "FOLLOW_UP_WINDOW_SECONDS", 0.0) or 0.0)
    if window <= 0:
        return ""

    try:
        log(f"Listening up to {window:.1f}s for a quick follow-up...")
        heard = stt_vosk.listen_follow_up(window, getattr(config, "MAX_LISTEN_SECONDS", 10.0))
    except Exception as exc:
        log(f"Follow-up listener error: {exc}")
        return ""

    text = heard.strip()
    if text:
        log(f"Follow-up heard: {text}")
    return text



def _process_user_query(
    user_text: str,
    orchestrator: Orchestrator,
    conversation_state: List[Dict[str, str]],
    command_feedback: Optional[str] = None,
    *,
    assistant_directive_override: Optional[str] = None,
) -> str:
    """Persist conversation state and let the orchestrator handle the turn."""

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
        response_message = orchestrator.route(
            user_message=user_text,
            conversation_state=conversation_state,
            assistant_directive=directive,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log(f"Orchestrator error: {exc}")
        fallback = "I ran into a local orchestration error. Please try again."
        conversation_state.append({"role": "assistant", "content": fallback})
        conversation_manager.add_turn("assistant", fallback)
        memory_manager.add_conversation_turn("assistant", fallback)
        return fallback

    reply = response_message.get("content", "") or "(No response from model.)"
    conversation_manager.add_turn("assistant", reply)
    memory_manager.add_conversation_turn("assistant", reply)
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
    pending_follow_up: Optional[str] = None
    
    # Start keyboard listener for interrupts
    listener = keyboard.Listener(on_press=_on_key_press)
    listener.start()

    while True:
        try:
            if pending_follow_up:
                user_text = pending_follow_up
                pending_follow_up = None
            else:
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
                    if config.USE_TTS:
                        assistant_reply = _stream_and_deliver_reply(
                            cleaned,
                            orchestrator,
                            conversation_state,
                            command_feedback=reply,
                        )
                        follow_up = _listen_for_follow_up_query()
                        if follow_up:
                            pending_follow_up = follow_up
                    else:
                        assistant_reply = _process_user_query(
                            cleaned,
                            orchestrator,
                            conversation_state,
                            command_feedback=reply,
                        )
                        _deliver_text_reply(assistant_reply)
                else:
                    print(f"{config.ASSISTANT_NAME}: {reply}")
                    if config.USE_TTS:
                        _play_reply_with_streaming_tts(reply)
                        follow_up = _listen_for_follow_up_query()
                        if follow_up:
                            pending_follow_up = follow_up
                continue

            if config.USE_TTS:
                assistant_reply = _stream_and_deliver_reply(
                    cleaned,
                    orchestrator,
                    conversation_state,
                )
                follow_up = _listen_for_follow_up_query()
                if follow_up:
                    pending_follow_up = follow_up
            else:
                assistant_reply = _process_user_query(
                    cleaned,
                    orchestrator,
                    conversation_state,
                )
                _deliver_text_reply(assistant_reply)
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
