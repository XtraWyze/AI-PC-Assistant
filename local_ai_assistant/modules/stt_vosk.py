"""Offline speech-to-text pipeline using Vosk."""
from __future__ import annotations

import os
import queue
import time
from typing import Optional

import simplejson as json
import sounddevice as sd
from vosk import KaldiRecognizer, Model

import config
from utils.logger import log

_SAMPLERATE = 16_000
_MODEL: Optional[Model] = None
_RECOGNIZER: Optional[KaldiRecognizer] = None


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
