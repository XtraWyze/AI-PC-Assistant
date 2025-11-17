"""Main entry point for the local AI assistant loop."""
from __future__ import annotations

import queue
import re
import sys
import threading
from typing import Any, List, Optional, Tuple

from colorama import Fore, Style, init as colorama_init
from pynput import keyboard

import config
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


def initialize_subsystems() -> None:
    """Initialize STT and TTS subsystems when enabled."""
    if config.USE_STT:
        try:
            stt_vosk.init_recognizer()
            log("Speech recognizer loaded.")
        except Exception as exc:  # pragma: no cover - hardware specific
            log(f"Failed to initialize STT: {exc}")
            log("Continuing without speech input. Set USE_STT=False to silence this warning.")
    if config.USE_TTS:
        try:
            tts_engine.init_tts()
            log("TTS engine initialized.")
        except Exception as exc:  # pragma: no cover - hardware specific
            log(f"Failed to initialize TTS: {exc}")
            log("Continuing without speech output. Set USE_TTS=False to silence this warning.")


def print_startup_banner() -> None:
    mode = config.MODE.lower()
    log(
        "Starting %s in %s mode (hotword=%s, commands=%s)."
        % (
            config.ASSISTANT_NAME,
            mode,
            "on" if config.ENABLE_HOTWORD else "off",
            "on" if config.ENABLE_COMMANDS else "off",
        )
    )
    if mode == "voice" and config.ENABLE_HOTWORD:
        log(f"Say '{config.HOTWORD}' to wake the assistant.")
    elif mode == "voice" and config.ENABLE_PUSH_TO_TALK:
        log("Voice mode fallback: press ENTER to talk when prompted.")
    
    log(f"Press ESC to interrupt the assistant.")
    log("Type 'quit' or 'exit' at any time to stop.")


def _speak_text(text: str) -> None:
    if not text or not config.USE_TTS:
        return
    try:
        tts_engine.speak(text)
    except Exception as exc:  # pragma: no cover - audio hardware
        log(f"TTS playback failed: {exc}")


def _capture_text_input() -> str:
    prompt = f"{Fore.CYAN}You>{Style.RESET_ALL} "
    try:
        return input(prompt).strip()
    except EOFError:
        return "quit"


def _capture_voice_input() -> str:
    if not config.USE_STT:
        log("Voice mode requires USE_STT=True. Falling back to empty input.")
        return ""

    if config.ENABLE_HOTWORD:
        detected = hotword_detector.listen_for_hotword()
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
    _speak_text(text)


def _process_user_query(user_text: str) -> None:
    memory_manager.add_history_entry(user_text)
    memory_manager.set_fact("last_query", user_text)
    conversation_manager.add_turn("user", user_text)

    if config.ENABLE_COMMANDS and commands_toolkit.is_command(user_text):
        result = commands_toolkit.handle_command(user_text, memory=memory_manager, logger=log)
        conversation_manager.add_turn("assistant", result)
        _deliver_text_reply(result)
        return

    prompt = conversation_manager.build_prompt_with_context(
        user_text,
        system_preamble=getattr(config, "SYSTEM_PREAMBLE", None),
    )
    reply = stream_llm_reply(prompt)
    conversation_manager.add_turn("assistant", reply)


def main() -> None:
    initialize_subsystems()
    print_startup_banner()
    
    # Start keyboard listener for interrupts
    listener = keyboard.Listener(on_press=_on_key_press)
    listener.start()

    while True:
        try:
            user_text = _get_user_input().strip()
            if not user_text:
                continue
            if user_text.lower() in {"quit", "exit"}:
                log("Exiting on user request.")
                return
            print(f"{Fore.CYAN}You:{Style.RESET_ALL} {user_text}")
            _process_user_query(user_text)
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
