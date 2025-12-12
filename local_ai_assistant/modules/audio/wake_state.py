"""Wake state machine for two-stage hotword activation with Whisper confirmation.

Implements a state machine that transitions through:
IDLE_HOTWORD -> CONFIRMING -> LISTENING_QUERY -> PROCESSING -> back to IDLE_HOTWORD

Prevents false triggers by confirming hotwords with Whisper STT and enforces
cooldown periods to avoid repeated triggers.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from enum import Enum, auto
from typing import Callable, Optional

import numpy as np

from utils.logger import log


class WakeState(Enum):
    """States for the wake detection state machine."""
    IDLE_HOTWORD = auto()      # Listening for hotword (KWS only)
    CONFIRMING = auto()         # Buffering audio for Whisper confirmation
    LISTENING_QUERY = auto()    # Recording user query after confirmed wake
    PROCESSING = auto()         # Processing the query (assistant active)
    DICTATION = auto()          # Voice typing mode (no assistant involvement)


class WakeStateMachine:
    """Manages wake detection states and transitions.
    
    Implements two-stage activation:
    1. Keyword spotting (KWS) detects hotword
    2. Whisper confirms the transcript contains the wake phrase
    
    Only after confirmation does the system enter LISTENING_QUERY state.
    """

    def __init__(
        self,
        confirm_with_whisper: bool = True,
        confirm_timeout_s: float = 2.5,
        cooldown_s: float = 3.0,
        recent_window_s: float = 8.0,
        pre_trigger_buffer_s: float = 1.2,
        post_trigger_record_s: float = 0.8,
        sample_rate: int = 16000,
        logger=log,
    ):
        """Initialize the wake state machine.
        
        Args:
            confirm_with_whisper: Enable Whisper confirmation after KWS trigger.
            confirm_timeout_s: Max time to wait for confirmation audio.
            cooldown_s: Cooldown period after confirmed trigger.
            recent_window_s: Window for tracking recent wake confirmations.
            pre_trigger_buffer_s: Seconds of audio to buffer before trigger.
            post_trigger_record_s: Seconds to record after trigger.
            sample_rate: Audio sample rate (Hz).
            logger: Logging function.
        """
        self.logger = logger
        self.confirm_with_whisper = confirm_with_whisper
        self.confirm_timeout_s = confirm_timeout_s
        self.cooldown_s = cooldown_s
        self.recent_window_s = recent_window_s
        self.pre_trigger_buffer_s = pre_trigger_buffer_s
        self.post_trigger_record_s = post_trigger_record_s
        self.sample_rate = sample_rate
        
        # State tracking
        self._state = WakeState.IDLE_HOTWORD
        self._state_lock = threading.Lock()
        self._last_confirmed_time: Optional[float] = None
        self._cooldown_until: Optional[float] = None
        
        # Audio buffer for confirmation (circular buffer)
        buffer_samples = int(pre_trigger_buffer_s * sample_rate)
        self._audio_buffer: deque[np.ndarray] = deque(maxlen=buffer_samples // 320)  # ~20ms frames
        
        # Rejection tracking
        self.rejection_reasons: dict[str, int] = {
            "no_vad": 0,
            "below_threshold": 0,
            "cooldown_active": 0,
            "confirm_failed": 0,
            "confirm_timeout": 0,
        }
    
    @property
    def state(self) -> WakeState:
        """Get the current state."""
        with self._state_lock:
            return self._state
    
    def set_state(self, new_state: WakeState) -> None:
        """Set a new state with logging."""
        with self._state_lock:
            if self._state != new_state:
                self.logger(f"State transition: {self._state.name} -> {new_state.name}")
                self._state = new_state
    
    def is_in_cooldown(self) -> bool:
        """Check if we're currently in cooldown period."""
        if self._cooldown_until is None:
            return False
        return time.time() < self._cooldown_until
    
    def was_recently_confirmed(self) -> bool:
        """Check if wake was confirmed within the recent window."""
        if self._last_confirmed_time is None:
            return False
        elapsed = time.time() - self._last_confirmed_time
        return elapsed < self.recent_window_s
    
    def should_skip_voice_typing(self) -> bool:
        """Check if voice typing should be blocked (assistant has priority).
        
        Returns:
            True if voice typing should be skipped because:
            - State is LISTENING_QUERY or PROCESSING (query in progress)
            - Wake was recently confirmed (within recent window)
        """
        current_state = self.state
        if current_state in (WakeState.LISTENING_QUERY, WakeState.PROCESSING):
            return True
        return self.was_recently_confirmed()
    
    def buffer_audio_frame(self, frame: np.ndarray) -> None:
        """Add an audio frame to the pre-trigger buffer.
        
        Args:
            frame: Audio frame as numpy array.
        """
        self._audio_buffer.append(frame.copy())
    
    def get_buffered_audio(self) -> Optional[np.ndarray]:
        """Get buffered audio from before the trigger.
        
        Returns:
            Concatenated audio buffer as numpy array, or None if empty.
        """
        if not self._audio_buffer:
            return None
        return np.concatenate(list(self._audio_buffer))
    
    def clear_buffer(self) -> None:
        """Clear the audio buffer."""
        self._audio_buffer.clear()
    
    def handle_hotword_trigger(
        self,
        score: float,
        threshold: float,
        has_vad: bool,
    ) -> tuple[bool, Optional[str]]:
        """Handle a hotword trigger from the KWS engine.
        
        Args:
            score: Confidence score from hotword engine.
            threshold: Detection threshold.
            has_vad: Whether VAD detected speech in the frame.
        
        Returns:
            Tuple of (should_confirm, rejection_reason):
            - should_confirm: True if we should proceed to confirmation
            - rejection_reason: String reason if rejected, None otherwise
        """
        # Check rejection conditions
        if not has_vad:
            self.rejection_reasons["no_vad"] += 1
            return False, "no_vad"
        
        if score < threshold:
            self.rejection_reasons["below_threshold"] += 1
            return False, "below_threshold"
        
        if self.is_in_cooldown():
            self.rejection_reasons["cooldown_active"] += 1
            return False, "cooldown_active"
        
        # Trigger accepted - proceed to confirmation if enabled
        self.logger(f"Hotword trigger accepted (score={score:.3f})")
        
        if not self.confirm_with_whisper:
            # No confirmation needed - directly mark as confirmed
            self._mark_confirmed()
            return True, None
        
        # Transition to CONFIRMING state
        self.set_state(WakeState.CONFIRMING)
        return True, None
    
    def confirm_with_transcript(
        self,
        transcript: str,
        expected_phrases: list[str],
    ) -> bool:
        """Confirm hotword trigger by checking Whisper transcript.
        
        Args:
            transcript: Whisper transcription of buffered audio.
            expected_phrases: List of expected wake phrases (case-insensitive).
        
        Returns:
            True if transcript contains an expected phrase, False otherwise.
        """
        normalized_transcript = transcript.lower().strip()
        
        if not normalized_transcript:
            self.logger("Confirmation failed: empty transcript")
            self.rejection_reasons["confirm_failed"] += 1
            self.set_state(WakeState.IDLE_HOTWORD)
            return False
        
        # Check if any expected phrase is in the transcript
        for phrase in expected_phrases:
            normalized_phrase = phrase.lower().strip()
            if normalized_phrase in normalized_transcript:
                self.logger(f"Confirmation successful: '{phrase}' found in '{transcript}'")
                self._mark_confirmed()
                return True
        
        # No match found
        self.logger(f"Confirmation failed: no match in '{transcript}'")
        self.rejection_reasons["confirm_failed"] += 1
        self.set_state(WakeState.IDLE_HOTWORD)
        return False
    
    def _mark_confirmed(self) -> None:
        """Mark wake as confirmed and set cooldown."""
        now = time.time()
        self._last_confirmed_time = now
        self._cooldown_until = now + self.cooldown_s
        self.set_state(WakeState.LISTENING_QUERY)
        self.logger(f"Wake confirmed. Cooldown active for {self.cooldown_s}s")
    
    def start_query_listening(self) -> None:
        """Transition to LISTENING_QUERY state."""
        self.set_state(WakeState.LISTENING_QUERY)
    
    def start_processing(self) -> None:
        """Transition to PROCESSING state."""
        self.set_state(WakeState.PROCESSING)
    
    def start_dictation(self) -> None:
        """Transition to DICTATION state."""
        self.set_state(WakeState.DICTATION)
    
    def reset_to_idle(self) -> None:
        """Reset to IDLE_HOTWORD state."""
        self.set_state(WakeState.IDLE_HOTWORD)
        self.clear_buffer()
    
    def get_rejection_stats(self) -> dict[str, int]:
        """Get statistics on rejection reasons."""
        return self.rejection_reasons.copy()
    
    def reset_rejection_stats(self) -> None:
        """Reset rejection statistics."""
        for key in self.rejection_reasons:
            self.rejection_reasons[key] = 0


def create_state_machine_from_config(config_module, logger=log) -> WakeStateMachine:
    """Factory function to create a WakeStateMachine from config settings.
    
    Args:
        config_module: Configuration module with HOTWORD_* settings.
        logger: Logging function.
    
    Returns:
        Initialized WakeStateMachine instance.
    """
    confirm_whisper = bool(getattr(config_module, "HOTWORD_CONFIRM_WHISPER", True))
    confirm_timeout = float(getattr(config_module, "HOTWORD_CONFIRM_TIMEOUT_S", 2.5))
    cooldown = float(getattr(config_module, "HOTWORD_COOLDOWN_S", 3.0))
    recent_window = float(getattr(config_module, "HOTWORD_RECENT_WINDOW_S", 8.0))
    
    return WakeStateMachine(
        confirm_with_whisper=confirm_whisper,
        confirm_timeout_s=confirm_timeout,
        cooldown_s=cooldown,
        recent_window_s=recent_window,
        logger=logger,
    )
