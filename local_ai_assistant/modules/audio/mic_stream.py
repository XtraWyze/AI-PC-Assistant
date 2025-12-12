"""Microphone audio stream with VAD gating for hotword detection.

Captures audio from the default input device on Windows and applies
Voice Activity Detection (VAD) plus noise gating to reduce false positives.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Iterator, Optional

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    try:
        import webrtcvad
    except ImportError:
        webrtcvad = None  # type: ignore
else:
    try:
        import webrtcvad
    except ImportError:
        webrtcvad = None  # type: ignore

from utils.logger import log


class MicrophoneStream:
    """Streams audio from microphone with optional VAD gating.
    
    Captures 16kHz mono audio in configurable frame sizes (default 20ms).
    Applies noise gate and VAD to filter out non-speech audio, reducing
    false hotword triggers.
    """

    SAMPLE_RATE = 16000  # Required by openWakeWord and webrtcvad
    FRAME_DURATION_MS = 20  # Standard VAD frame size (10, 20, or 30ms)
    CHANNELS = 1  # Mono audio
    DTYPE = np.int16  # Required by webrtcvad
    
    def __init__(
        self,
        vad_enabled: bool = True,
        vad_aggressiveness: int = 2,
        noise_gate_enabled: bool = True,
        noise_gate_rms_min: float = 0.0015,
        noise_gate_multiplier: float = 2.5,
        device_index: Optional[int] = None,
        debug_audio: bool = False,
        logger=log,
    ):
        """Initialize the microphone stream.
        
        Args:
            vad_enabled: Enable Voice Activity Detection gating.
            vad_aggressiveness: VAD sensitivity (0-3, higher = more aggressive).
            noise_gate_enabled: Enable adaptive noise gate.
            noise_gate_rms_min: Minimum RMS threshold for noise gate.
            noise_gate_multiplier: Multiplier for adaptive noise floor.
            device_index: Sounddevice input device index (None = default).
            debug_audio: Enable detailed audio debug logging.
            logger: Logging function.
        """
        self.logger = logger
        self.vad_enabled = vad_enabled
        self.vad_aggressiveness = vad_aggressiveness
        self.noise_gate_enabled = noise_gate_enabled
        self.noise_gate_rms_min = noise_gate_rms_min
        self.noise_gate_multiplier = noise_gate_multiplier
        self.device_index = device_index
        self.debug_audio = debug_audio
        
        # Calculate frame size in samples
        self.frame_samples = int(self.SAMPLE_RATE * self.FRAME_DURATION_MS / 1000)
        self.frame_bytes = self.frame_samples * 2  # 16-bit = 2 bytes per sample
        
        # Initialize VAD if enabled
        self._vad = None
        if self.vad_enabled:
            if webrtcvad is None:
                self.logger("webrtcvad not installed. VAD gating disabled.")
                self.vad_enabled = False
            else:
                try:
                    self._vad = webrtcvad.Vad(self.vad_aggressiveness)
                    self.logger(f"VAD initialized with aggressiveness={self.vad_aggressiveness}")
                except Exception as exc:
                    self.logger(f"Failed to initialize VAD: {exc}")
                    self.vad_enabled = False
        
        # Stream state
        self._stream: Optional[sd.InputStream] = None
        self._queue: queue.Queue[Optional[np.ndarray]] = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Adaptive noise floor (rolling buffer of RMS values during non-speech)
        # ~2 seconds at 50 frames/sec = 100 samples
        self._noise_floor_buffer: deque[float] = deque(maxlen=100)
        self._noise_floor = noise_gate_rms_min
        
        # Rate-limited logging
        self._last_rms_log_time = 0.0
        self._rms_log_interval = 1.0  # seconds
        
        # Statistics for debugging
        self.stats = {
            "frames_processed": 0,
            "frames_passed": 0,
            "frames_blocked_noise": 0,
            "frames_blocked_vad": 0,
        }
    
    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Callback for sounddevice stream - queues audio data."""
        if status:
            self.logger(f"Audio callback status: {status}")
        
        # Copy audio data to avoid issues with callback buffer reuse
        if indata is not None and len(indata) > 0:
            # indata is float32 in range [-1, 1], convert to int16
            audio_int16 = (indata[:, 0] * 32767).astype(np.int16)
            self._queue.put(audio_int16.copy())
    
    def _compute_rms(self, audio_frame: np.ndarray) -> float:
        """Compute RMS of audio frame (float32 in range [-1, 1]).
        
        Returns:
            RMS value.
        """
        # Convert to float32 in range [-1, 1]
        if audio_frame.dtype == np.int16:
            audio_float = audio_frame.astype(np.float32) / 32768.0
        else:
            audio_float = audio_frame.astype(np.float32)
        
        return float(np.sqrt(np.mean(audio_float ** 2)))
    
    def _check_noise_gate(self, audio_frame: np.ndarray, rms: float, vad_speech: bool) -> bool:
        """Check if audio frame passes the adaptive noise gate.
        
        Args:
            audio_frame: Audio frame as numpy array.
            rms: Pre-computed RMS value.
            vad_speech: Whether VAD detected speech.
        
        Returns:
            True if frame passes (has sufficient energy or VAD detected speech), False otherwise.
        """
        if not self.noise_gate_enabled:
            return True
        
        # If VAD says speech, bypass noise gate to avoid blocking real speech
        if vad_speech:
            return True
        
        # Compute adaptive threshold
        threshold = max(self.noise_gate_rms_min, self._noise_floor * self.noise_gate_multiplier)
        
        # Update noise floor with this sample if below threshold (likely background noise)
        if rms < threshold:
            self._noise_floor_buffer.append(rms)
            if self._noise_floor_buffer:
                self._noise_floor = float(np.median(list(self._noise_floor_buffer)))
        
        return rms >= threshold
    
    def _check_vad(self, audio_frame: np.ndarray) -> bool:
        """Check if audio frame contains speech according to VAD.
        
        Args:
            audio_frame: Audio data as int16 numpy array.
        
        Returns:
            True if speech detected, False otherwise.
        """
        if not self.vad_enabled or self._vad is None:
            return True
        
        try:
            # Convert to bytes for webrtcvad
            audio_bytes = audio_frame.tobytes()
            # VAD expects exact frame sizes (10, 20, or 30ms at 8/16/32/48 kHz)
            is_speech = self._vad.is_speech(audio_bytes, self.SAMPLE_RATE)
            return is_speech
        except Exception as exc:
            self.logger(f"VAD error: {exc}")
            return True  # Pass through on error
    
    def start(self) -> None:
        """Start the audio stream."""
        if self._running:
            self.logger("Microphone stream already running.")
            return
        
        try:
            # Open audio input stream
            self._stream = sd.InputStream(
                device=self.device_index,
                channels=self.CHANNELS,
                samplerate=self.SAMPLE_RATE,
                dtype=np.float32,  # sounddevice uses float32 internally
                blocksize=self.frame_samples,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._running = True
            self.logger(f"Microphone stream started: {self.SAMPLE_RATE}Hz, {self.FRAME_DURATION_MS}ms frames")
        except Exception as exc:
            raise RuntimeError(f"Failed to start microphone stream: {exc}") from exc
    
    def stop(self) -> None:
        """Stop the audio stream."""
        if not self._running:
            return
        
        self._running = False
        
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                self.logger(f"Error stopping stream: {exc}")
            finally:
                self._stream = None
        
        # Clear the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        
        self.logger("Microphone stream stopped.")
    
    def read_frame(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Read a single audio frame, applying noise gate and VAD.
        
        Args:
            timeout: Maximum time to wait for a frame (seconds).
        
        Returns:
            Audio frame as int16 numpy array if available and passes gates,
            None if no frame available or frame blocked by gates.
        """
        if not self._running:
            return None
        
        try:
            audio_frame = self._queue.get(timeout=timeout)
            if audio_frame is None:
                return None
            
            self.stats["frames_processed"] += 1
            
            # Compute RMS
            rms = self._compute_rms(audio_frame)
            
            # Rate-limited RMS logging
            current_time = time.time()
            if self.debug_audio and current_time - self._last_rms_log_time >= self._rms_log_interval:
                self._last_rms_log_time = current_time
                threshold = max(self.noise_gate_rms_min, self._noise_floor * self.noise_gate_multiplier)
                self.logger(f"[AUDIO] rms={rms:.4f} noise_floor={self._noise_floor:.4f} threshold={threshold:.4f}")
            
            # Check VAD first to know if speech is present
            vad_speech = self._check_vad(audio_frame)
            
            # Apply noise gate (VAD can bypass it)
            if not self._check_noise_gate(audio_frame, rms, vad_speech):
                # Only count as noise-blocked if VAD also said no speech
                if not vad_speech:
                    self.stats["frames_blocked_noise"] += 1
                    if self.debug_audio:
                        self.logger(f"[AUDIO] Frame blocked by noise gate (rms={rms:.4f})")
                return None
            
            # Apply VAD (already computed above)
            if not vad_speech:
                self.stats["frames_blocked_vad"] += 1
                if self.debug_audio:
                    self.logger(f"[AUDIO] Frame blocked by VAD (rms={rms:.4f})")
                return None
            
            # Frame passed all gates
            self.stats["frames_passed"] += 1
            if self.debug_audio:
                self.logger(f"[AUDIO] Frame passed (rms={rms:.4f})")
            
            return audio_frame
            
        except queue.Empty:
            return None
    
    def read_frames(self, timeout: Optional[float] = None) -> Iterator[np.ndarray]:
        """Continuously read frames until stopped.
        
        Args:
            timeout: Optional timeout for the entire operation (seconds).
        
        Yields:
            Audio frames as int16 numpy arrays that pass noise gate and VAD.
        """
        start_time = time.time()
        
        while self._running:
            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    break
                remaining = timeout - elapsed
                frame_timeout = min(0.1, remaining)
            else:
                frame_timeout = 0.1
            
            frame = self.read_frame(timeout=frame_timeout)
            if frame is not None:
                yield frame
    
    def get_stats(self) -> dict:
        """Return stream statistics."""
        total = max(1, self.stats["frames_processed"])
        return {
            **self.stats,
            "pass_rate": self.stats["frames_passed"] / total,
            "noise_block_rate": self.stats["frames_blocked_noise"] / total,
            "vad_block_rate": self.stats["frames_blocked_vad"] / total,
        }
    
    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self.stats = {
            "frames_processed": 0,
            "frames_passed": 0,
            "frames_blocked_noise": 0,
            "frames_blocked_vad": 0,
        }
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


def create_stream_from_config(config_module, logger=log) -> MicrophoneStream:
    """Factory function to create a MicrophoneStream from config settings.
    
    Args:
        config_module: Configuration module with VAD_* and MIC_* settings.
        logger: Logging function.
    
    Returns:
        Initialized MicrophoneStream instance.
    """
    vad_enabled = bool(getattr(config_module, "VAD_ENABLED", True))
    vad_aggressiveness = int(getattr(config_module, "VAD_AGGRESSIVENESS", 2))
    noise_gate_enabled = bool(getattr(config_module, "NOISE_GATE_ENABLED", True))
    noise_gate_rms_min = float(getattr(config_module, "NOISE_GATE_RMS_MIN", 0.0015))
    noise_gate_multiplier = float(getattr(config_module, "NOISE_GATE_MULTIPLIER", 2.5))
    device_index = getattr(config_module, "MIC_DEVICE_INDEX", None)
    debug_audio = bool(getattr(config_module, "DEBUG_HOTWORD_AUDIO", False))
    
    return MicrophoneStream(
        vad_enabled=vad_enabled,
        vad_aggressiveness=vad_aggressiveness,
        noise_gate_enabled=noise_gate_enabled,
        noise_gate_rms_min=noise_gate_rms_min,
        noise_gate_multiplier=noise_gate_multiplier,
        device_index=device_index,
        debug_audio=debug_audio,
        logger=logger,
    )
