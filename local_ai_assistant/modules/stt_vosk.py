"""Offline speech-to-text pipeline using Vosk."""
from __future__ import annotations

import os
import queue
import time
import threading
from typing import List, Optional

import simplejson as json
import sounddevice as sd
from vosk import KaldiRecognizer, Model

import config
from utils.logger import log

_SAMPLERATE = 16_000
_MODEL: Optional[Model] = None
_RECOGNIZER: Optional[KaldiRecognizer] = None


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


# Reminder: download a Vosk model (e.g., "vosk-model-en-us-0.22") and place its
# extracted folder inside config.VOSK_MODEL_PATH. The folder should contain
# "conf", "am", "graph", etc.

def init_recognizer() -> None:
    """Load the Vosk model and prepare the recognizer."""
    global _MODEL, _RECOGNIZER
    model_path = config.VOSK_MODEL_PATH
    if not os.path.isdir(model_path):
        raise FileNotFoundError(
            f"Vosk model not found at '{model_path}'. Download a model from https://alphacephei.com/vosk/models "
            "and place it there."
        )
    _MODEL = Model(model_path)
    _RECOGNIZER = KaldiRecognizer(_MODEL, _SAMPLERATE)


def _create_stream_queue() -> queue.Queue[bytes]:
    audio_queue: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):  # pragma: no cover - hardware callback
        if status:
            log(f"sounddevice status: {status}")
        audio_queue.put(bytes(indata))

    sd.default.samplerate = _SAMPLERATE
    sd.default.channels = 1
    sd.default.dtype = "int16"
    if config.MIC_DEVICE_INDEX is not None:
        sd.default.device = (config.MIC_DEVICE_INDEX, None)

    stream = sd.RawInputStream(callback=callback)
    stream.start()
    audio_queue.stream = stream  # type: ignore[attr-defined]
    return audio_queue


def listen_once(timeout_seconds: float = 10.0) -> str:
    """Capture audio for up to timeout_seconds and return recognized text."""
    if _RECOGNIZER is None:
        log("Recognizer not initialized. Call init_recognizer() first.")
        return ""

    audio_queue = _create_stream_queue()
    stream = getattr(audio_queue, "stream")

    deadline = time.time() + timeout_seconds
    transcript = ""
    try:
        while time.time() < deadline:
            try:
                data = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if _RECOGNIZER.AcceptWaveform(data):
                result = json.loads(_RECOGNIZER.Result())
                transcript = result.get("text", "")
                break
        if not transcript:
            final = json.loads(_RECOGNIZER.FinalResult())
            transcript = final.get("text", "")
    finally:
        stream.stop()
        stream.close()

    return transcript.strip()


def create_interrupt_recognizer() -> Optional[KaldiRecognizer]:
    """Create a separate recognizer instance for interrupt detection."""
    global _MODEL
    if _MODEL is None:
        model_path = config.VOSK_MODEL_PATH
        if not os.path.isdir(model_path):
            return None
        _MODEL = Model(model_path)
    return KaldiRecognizer(_MODEL, _SAMPLERATE)


def listen_for_interrupt(recognizer: KaldiRecognizer, interrupt_phrases: list, timeout_seconds: float = 0.5) -> bool:
    """Listen briefly for interrupt commands. Returns True if detected."""
    normalized = _normalize_phrases(interrupt_phrases)
    audio_queue: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):  # pragma: no cover
        if status:
            # Silently ignore status messages during interrupt detection
            pass
        audio_queue.put(bytes(indata))

    # Configure for simultaneous playback and recording
    try:
        stream = sd.RawInputStream(
            samplerate=_SAMPLERATE,
            channels=1,
            dtype='int16',
            callback=callback,
            device=config.MIC_DEVICE_INDEX,
            blocksize=4096  # Larger buffer for better stability
        )
        stream.start()
    except Exception as e:
        # Can't open stream - probably in use
        return False
    
    deadline = time.time() + timeout_seconds
    detected = False
    
    try:
        while time.time() < deadline and not detected:
            try:
                data = audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            
            try:
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    transcript = result.get("text", "")
                    if _contains_interrupt_phrase(transcript, normalized):
                        detected = True
                        break
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "")
                    if _contains_interrupt_phrase(partial, normalized):
                        detected = True
                        break
            except Exception:
                # Ignore recognition errors
                pass
        
        # Check partial result if nothing detected yet
        if not detected:
            try:
                final = json.loads(recognizer.FinalResult())
                transcript = final.get("text", "")
                if _contains_interrupt_phrase(transcript, normalized):
                    detected = True
            except Exception:
                pass
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
    
    return detected


class VoiceInterruptDetector:
    """Persistent microphone stream for low-latency interruption detection."""

    def __init__(self, interrupt_phrases: list[str], blocksize: int = 2048) -> None:
        normalized = _normalize_phrases(interrupt_phrases)
        if not normalized:
            raise ValueError("No interrupt phrases provided.")

        recognizer = create_interrupt_recognizer()
        if recognizer is None:
            raise RuntimeError("Vosk model not initialized; call init_recognizer() first.")

        self._phrases = normalized
        self._recognizer = recognizer
        self._queue: "queue.Queue[bytes]" = queue.Queue()

        def callback(indata, frames, time_info, status):  # pragma: no cover - hardware callback
            if status:
                # Avoid log spam here; interrupts run continuously.
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

    # Internal helpers --------------------------------------------------
    def _process_chunk(self, data: bytes) -> bool:
        try:
            if self._recognizer.AcceptWaveform(data):
                result = json.loads(self._recognizer.Result())
                transcript = result.get("text", "")
            else:
                partial = json.loads(self._recognizer.PartialResult())
                transcript = partial.get("partial", "")
        except Exception:
            return False

        return _contains_interrupt_phrase(transcript, self._phrases)

    def _process_final(self) -> bool:
        try:
            final = json.loads(self._recognizer.FinalResult())
            transcript = final.get("text", "")
        except Exception:
            return False
        return _contains_interrupt_phrase(transcript, self._phrases)

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
        poll_timeout = max(0.01, poll_timeout)
        idle_reset_seconds = max(0.1, idle_reset_seconds)
        detected = False
        last_audio = time.time()

        try:
            while not detected:
                if stop_event and stop_event.is_set():
                    break

                try:
                    data = self._queue.get(timeout=poll_timeout)
                except queue.Empty:
                    if time.time() - last_audio > idle_reset_seconds:
                        self._recognizer.Reset()
                        last_audio = time.time()
                    continue

                last_audio = time.time()
                detected = self._process_chunk(data)
        finally:
            self._recognizer.Reset()
            self._drain_queue()

        return detected
