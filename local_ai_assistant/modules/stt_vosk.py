"""Speech-to-text pipeline powered by Whisper (faster-whisper)."""
from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

import config
from utils.logger import log

try:  # Torch is optional; only used for CUDA availability checks.
    import torch

    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - torch may be absent in lightweight installs
    torch = None  # type: ignore
    _TORCH_AVAILABLE = False


_SAMPLERATE = 16_000
_SILENCE_TIMEOUT = 1.2
_ENGINE_LOCK = threading.Lock()
_ENGINE: Optional["WhisperSTTEngine"] = None
_RECOGNIZER: Optional["WhisperSTTEngine"] = None  # Backwards compatibility for callers poking this attr


def _normalize_phrases(phrases: List[str]) -> List[str]:
    normalized: List[str] = []
    for phrase in phrases:
        cleaned = phrase.lower().strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _contains_interrupt_phrase(transcript: str, phrases: List[str]) -> bool:
    if not transcript or not phrases:
        return False
    lowered = transcript.lower().strip()
    if not lowered:
        return False
    for phrase in phrases:
        if phrase in lowered:
            return True
    return False


def _pcm_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    if not pcm_bytes:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)
    return samples.astype(np.float32) / 32768.0


def _chunk_has_audio(pcm_bytes: bytes, threshold: int = 600) -> bool:
    if not pcm_bytes:
        return False
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    if samples.size == 0:
        return False
    return np.max(np.abs(samples)) >= threshold


class WhisperSTTEngine:
    """Wrapper around faster-whisper that keeps configuration in one place."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        beam_size: Optional[int] = None,
        language: Optional[str] = None,
    ) -> None:
        cfg = config
        self.model_name = model_name or getattr(cfg, "WHISPER_MODEL", "small")
        requested_device = (device or getattr(cfg, "WHISPER_DEVICE", "auto")).lower()
        self.device = self._select_device(requested_device)
        requested_compute = (compute_type or getattr(cfg, "WHISPER_COMPUTE_TYPE", "auto")).lower()
        self.compute_type = self._select_compute_type(self.device, requested_compute)
        self.beam_size = beam_size or int(getattr(cfg, "WHISPER_BEAM_SIZE", 5) or 5)
        self.language = language or getattr(cfg, "WHISPER_LANGUAGE", "en") or None
        self.temperature = 0.0

        log(
            f"Loading Whisper model '{self.model_name}' on {self.device} ({self.compute_type}, beam={self.beam_size})..."
        )
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )
        log("Whisper model ready.")

    @staticmethod
    def _select_device(requested: str) -> str:
        if requested != "auto":
            return requested
        if _TORCH_AVAILABLE and torch.cuda.is_available():  # type: ignore[attr-defined]
            return "cuda"
        return "cpu"

    @staticmethod
    def _select_compute_type(device: str, requested: str) -> str:
        if requested != "auto":
            return requested
        if device == "cpu":
            return "int8"
        return "float16"

    def transcribe_bytes(self, pcm_bytes: bytes) -> str:
        audio = _pcm_bytes_to_float32(pcm_bytes)
        if audio.size == 0:
            return ""
        return self._run_transcription(audio)

    def transcribe_file(self, audio_path: str) -> str:
        return self._run_transcription(audio_path)

    def _run_transcription(self, audio_source) -> str:
        text_fragments: List[str] = []
        segments, _ = self.model.transcribe(
            audio_source,
            beam_size=self.beam_size,
            temperature=self.temperature,
            language=self.language,
        )
        for segment in segments:
            text_fragments.append(segment.text)
        return "".join(text_fragments).strip()


def init_recognizer(force_reload: bool = False) -> None:
    """Initialize the shared Whisper engine (idempotent)."""
    global _ENGINE, _RECOGNIZER
    with _ENGINE_LOCK:
        if _ENGINE is not None and not force_reload:
            return
        _ENGINE = WhisperSTTEngine()
        _RECOGNIZER = _ENGINE


def _ensure_engine() -> WhisperSTTEngine:
    if _ENGINE is None:
        init_recognizer()
    if _ENGINE is None:  # pragma: no cover - defensive guard
        raise RuntimeError("Whisper STT engine failed to initialize.")
    return _ENGINE


def _create_stream_queue(blocksize: int = 0) -> queue.Queue[bytes]:
    audio_queue: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):  # pragma: no cover - hardware callback
        if status:
            log(f"sounddevice status: {status}")
        audio_queue.put(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=_SAMPLERATE,
        channels=1,
        dtype="int16",
        callback=callback,
        device=config.MIC_DEVICE_INDEX,
        blocksize=blocksize,
    )
    stream.start()
    audio_queue.stream = stream  # type: ignore[attr-defined]
    return audio_queue


def _capture_microphone_audio(
    timeout_seconds: float,
    silence_timeout: float = _SILENCE_TIMEOUT,
    min_seconds: float = 0.4,
) -> bytes:
    timeout_seconds = max(timeout_seconds, 0.5)
    silence_timeout = max(0.4, silence_timeout)
    min_seconds = max(0.2, min_seconds)

    audio_queue = _create_stream_queue()
    stream = getattr(audio_queue, "stream")
    buffer = bytearray()
    deadline = time.time() + timeout_seconds
    speech_started = False
    last_voice_time = 0.0

    try:
        while time.time() < deadline:
            try:
                chunk = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            buffer.extend(chunk)
            if _chunk_has_audio(chunk):
                speech_started = True
                last_voice_time = time.time()
            elif speech_started and (time.time() - last_voice_time) >= silence_timeout:
                break

        min_bytes = int(min_seconds * _SAMPLERATE) * 2
        if len(buffer) < min_bytes and time.time() < deadline:
            # Pad with additional audio to avoid overly short clips
            while len(buffer) < min_bytes and time.time() < deadline:
                try:
                    buffer.extend(audio_queue.get(timeout=0.2))
                except queue.Empty:
                    break
    finally:
        stream.stop()
        stream.close()

    return bytes(buffer)


def _capture_follow_up_audio(
    wait_seconds: float,
    listen_seconds: float,
    silence_timeout: float = _SILENCE_TIMEOUT,
) -> bytes:
    wait_seconds = max(wait_seconds, 0.5)
    listen_seconds = max(listen_seconds, 0.5)
    silence_timeout = max(0.3, silence_timeout)

    audio_queue = _create_stream_queue()
    stream = getattr(audio_queue, "stream")
    buffer = bytearray()
    wait_deadline = time.time() + wait_seconds
    overall_deadline = wait_deadline + listen_seconds
    speech_started = False
    last_voice_time = 0.0

    try:
        while True:
            active_deadline = overall_deadline if speech_started else wait_deadline
            if time.time() > active_deadline:
                break

            try:
                chunk = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not chunk:
                continue

            if not speech_started:
                if _chunk_has_audio(chunk):
                    speech_started = True
                    last_voice_time = time.time()
                    buffer.extend(chunk)
                continue

            buffer.extend(chunk)
            if _chunk_has_audio(chunk):
                last_voice_time = time.time()
            elif time.time() - last_voice_time >= silence_timeout:
                break

        min_bytes = int(0.25 * _SAMPLERATE) * 2
        if len(buffer) < min_bytes:
            return b""
        return bytes(buffer)
    finally:
        stream.stop()
        stream.close()


def listen_once(timeout_seconds: float = 10.0) -> str:
    """Capture audio for up to timeout_seconds and return recognized text."""
    engine = _ensure_engine()
    pcm_bytes = _capture_microphone_audio(timeout_seconds=timeout_seconds)
    if not pcm_bytes:
        return ""
    return engine.transcribe_bytes(pcm_bytes)


def listen_follow_up(wait_seconds: float, max_listen_seconds: Optional[float] = None) -> str:
    """Listen briefly for a follow-up utterance without requiring a wake word."""
    wait_seconds = max(0.0, wait_seconds)
    if wait_seconds <= 0:
        return ""

    engine = _ensure_engine()
    listen_budget = max_listen_seconds if max_listen_seconds is not None else getattr(config, "MAX_LISTEN_SECONDS", 10.0)
    pcm_bytes = _capture_follow_up_audio(wait_seconds=wait_seconds, listen_seconds=listen_budget)
    if not pcm_bytes:
        return ""
    return engine.transcribe_bytes(pcm_bytes)


def create_interrupt_recognizer() -> Optional[WhisperSTTEngine]:
    """Retained for compatibility with callers that expect a recognizer object."""
    try:
        return _ensure_engine()
    except Exception:
        return None


def listen_for_interrupt(
    recognizer,  # Unused but kept for backwards compatibility
    interrupt_phrases: List[str],
    timeout_seconds: float = 0.5,
) -> bool:
    """Listen briefly for interrupt commands. Returns True if detected."""
    _ = recognizer  # Preserve signature compatibility without relying on Vosk internals
    normalized = _normalize_phrases(interrupt_phrases)
    if not normalized:
        return False

    try:
        pcm_bytes = _capture_microphone_audio(timeout_seconds=timeout_seconds, silence_timeout=0.4, min_seconds=0.25)
    except Exception:
        return False

    if not pcm_bytes:
        return False

    transcript = _ensure_engine().transcribe_bytes(pcm_bytes)
    return _contains_interrupt_phrase(transcript, normalized)


class VoiceInterruptDetector:
    """Persistent microphone stream for low-latency interruption detection."""

    def __init__(self, interrupt_phrases: List[str], blocksize: int = 2048) -> None:
        normalized = _normalize_phrases(interrupt_phrases)
        if not normalized:
            raise ValueError("No interrupt phrases provided.")

        self._engine = _ensure_engine()
        self._phrases = normalized
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._window_seconds = max(blocksize / _SAMPLERATE, 0.2) * 3
        self._max_buffer_seconds = 2.0

        def callback(indata, frames, time_info, status):  # pragma: no cover - hardware callback
            if status:
                pass
            self._queue.put(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=_SAMPLERATE,
            channels=1,
            dtype="int16",
            callback=callback,
            device=config.MIC_DEVICE_INDEX,
            blocksize=blocksize,
            latency="low",
        )
        self._stream.start()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._drain_queue()

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def listen_continuous(
        self,
        stop_event: Optional[threading.Event] = None,
        poll_timeout: float = 0.05,
        idle_reset_seconds: float = 1.5,
    ) -> bool:
        """Continuously monitor the stream until interrupted or stop_event is set."""
        poll_timeout = max(0.02, poll_timeout)
        idle_reset_seconds = max(0.3, idle_reset_seconds)
        buffer = bytearray()
        window_bytes = max(1, int(self._window_seconds * _SAMPLERATE) * 2)
        max_bytes = max(window_bytes, int(self._max_buffer_seconds * _SAMPLERATE) * 2)
        last_audio = time.time()

        try:
            while True:
                if stop_event and stop_event.is_set():
                    return False

                try:
                    chunk = self._queue.get(timeout=poll_timeout)
                except queue.Empty:
                    if time.time() - last_audio > idle_reset_seconds:
                        buffer.clear()
                        last_audio = time.time()
                    continue

                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    del buffer[:-max_bytes]

                if _chunk_has_audio(chunk):
                    last_audio = time.time()

                if len(buffer) < window_bytes:
                    continue

                if not _chunk_has_audio(buffer):
                    buffer.clear()
                    continue

                transcript = self._engine.transcribe_bytes(bytes(buffer))
                buffer.clear()
                if _contains_interrupt_phrase(transcript, self._phrases):
                    return True
        finally:
            self._drain_queue()


if __name__ == "__main__":  # pragma: no cover - manual smoke test helper
    import argparse

    parser = argparse.ArgumentParser(description="Manual Whisper STT test harness")
    parser.add_argument("--file", help="Path to an audio file to transcribe", default="")
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to capture from microphone")
    args = parser.parse_args()

    init_recognizer()
    engine = _ensure_engine()

    if args.file:
        result = engine.transcribe_file(args.file)
        print(f"Transcription ({args.file}): {result}")
    else:
        print("Speak now...")
        text = listen_once(timeout_seconds=args.timeout)
        if text:
            print(f"Heard: {text}")
        else:
            print("No speech recognized.")
