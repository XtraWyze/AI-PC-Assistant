"""Main entry point for the local voice assistant loop."""
from __future__ import annotations

import queue
import re
import sys
import threading
from typing import Any, List, Optional, Tuple

from colorama import Fore, Style, init as colorama_init

import config
from modules import llm_engine, memory_manager, stt_vosk, tts_engine
from utils.logger import log


colorama_init()


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


def capture_user_input() -> str:
    """Prompt for typed or spoken input."""
    user_entry = input("Press ENTER to speak, or type 'quit' to exit: ").strip()
    if user_entry:
        return user_entry
    if not config.USE_STT:
        log("Speech input disabled. Type your request instead.")
        return ""
    log("Listening...")
    text = stt_vosk.listen_once(timeout_seconds=config.MAX_LISTEN_SECONDS)
    if text:
        log(f"Heard: {text}")
    else:
        log("No speech recognized.")
    return text


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
        if not self.enabled or not text:
            return
        self.text_queue.put(text)

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
                tts_engine.speak(text)
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
                buffer, sample_rate = audio
                tts_engine.play_audio(buffer, sample_rate)
            except Exception as exc:
                log(f"TTS playback failed: {exc}")
            finally:
                if audio is not None:
                    self.audio_queue.task_done()


def respond_to_query(query: str) -> str:
    """Stream LLM output to console and TTS for faster feedback."""
    print(f"{Fore.GREEN}Assistant:{Style.RESET_ALL} ", end="", flush=True)
    tts_worker = TTSPipeline()
    aggregated: List[str] = []
    buffer = ""

    def enqueue(text: str) -> None:
        if tts_worker:
            tts_worker.enqueue(text)

    try:
        for chunk in llm_engine.stream_response(query):
            if not chunk:
                continue
            aggregated.append(chunk)
            print(chunk, end="", flush=True)
            buffer += chunk
            completed, buffer = _extract_complete_segments(buffer)
            for piece in completed:
                enqueue(piece)
        leftover = buffer.strip()
        if leftover:
            enqueue(leftover)
        print(Style.RESET_ALL)
        return "".join(aggregated).strip() or "(No response from model.)"
    finally:
        if tts_worker:
            tts_worker.close()


def main() -> None:
    log("Starting local AI assistant. Press Ctrl+C to exit.")
    initialize_subsystems()

    while True:
        try:
            query = capture_user_input().strip()
            if query.lower() == "quit":
                log("Exiting on user request.")
                return
            if not query:
                continue

            print(f"{Fore.CYAN}You:{Style.RESET_ALL} {query}")
            memory_manager.add_entry("last_query", query)
            respond_to_query(query)
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
