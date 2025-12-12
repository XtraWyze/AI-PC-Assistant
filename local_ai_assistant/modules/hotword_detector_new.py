"""Integrated hotword detection coordinator using openWakeWord engine.

This module coordinates the hotword engine, microphone stream, and state machine
to provide a complete wake word detection system with two-stage activation.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from modules.audio.hotword_engine import HotwordEngine, create_engine_from_config
from modules.audio.mic_stream import MicrophoneStream, create_stream_from_config
from modules.audio.wake_state import WakeState, WakeStateMachine, create_state_machine_from_config
from modules import stt_whisper
from utils.logger import log as default_logger


def listen_for_hotword_new(
    config_module,
    logger=default_logger,
    timeout_seconds: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """Listen for hotword using openWakeWord with two-stage activation.
    
    This is the new hotword detection entry point that replaces the legacy
    Whisper-based detection. It uses:
    1. openWakeWord for keyword spotting (KWS)
    2. VAD gating to reduce false positives
    3. Optional Whisper confirmation for high confidence
    
    Args:
        config_module: Configuration module with hotword settings.
        logger: Logging function.
        timeout_seconds: Optional timeout for detection (None = wait indefinitely).
        stop_event: Optional event to signal early termination.
    
    Returns:
        True if hotword was confirmed, False otherwise.
    """
    # Check if new engine is enabled
    engine_type = getattr(config_module, "HOTWORD_ENGINE", "openwakeword").lower()
    if engine_type != "openwakeword":
        logger("openWakeWord engine not enabled in config. Using legacy detection.")
        return False
    
    # Initialize components
    try:
        hotword_engine = create_engine_from_config(config_module, logger=logger)
        mic_stream = create_stream_from_config(config_module, logger=logger)
        state_machine = create_state_machine_from_config(config_module, logger=logger)
    except Exception as exc:
        logger(f"Failed to initialize hotword components: {exc}")
        return False
    
    logger("Listening for hotword (openWakeWord)...")
    
    start_time = time.time()
    detected = False
    
    # Rate-limited logging for wake scores
    last_score_log_time = 0.0
    score_log_interval = 1.0  # seconds
    debug_audio = getattr(config_module, "DEBUG_HOTWORD_AUDIO", False)
    
    try:
        # Start audio stream
        mic_stream.start()
        
        # Main detection loop
        while True:
            # Check timeout
            if timeout_seconds is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    logger("Hotword detection timeout reached.")
                    break
            
            # Check stop event
            if stop_event is not None and stop_event.is_set():
                logger("Hotword detection stopped by event.")
                break
            
            # Read audio frame (with VAD gating)
            frame = mic_stream.read_frame(timeout=0.1)
            if frame is None:
                continue
            
            # Buffer audio for potential confirmation
            state_machine.buffer_audio_frame(frame)
            
            # Convert int16 to float32 for hotword engine
            frame_float = frame.astype(np.float32) / 32768.0
            
            # Process frame through hotword engine
            score, triggered = hotword_engine.process_frame(frame_float)
            
            # Rate-limited wake score logging
            current_time = time.time()
            if debug_audio and current_time - last_score_log_time >= score_log_interval:
                last_score_log_time = current_time
                scores_dict = hotword_engine.get_last_scores()
                logger(f"[WAKE] scores={scores_dict} max={score:.3f} threshold={hotword_engine.threshold:.3f}")
            
            if triggered:
                # Check if we should proceed to confirmation
                has_vad = True  # Frame already passed VAD in mic_stream
                threshold = hotword_engine.threshold
                
                should_confirm, rejection_reason = state_machine.handle_hotword_trigger(
                    score=score,
                    threshold=threshold,
                    has_vad=has_vad,
                )
                
                if rejection_reason:
                    logger(f"Hotword trigger rejected: {rejection_reason}")
                    continue
                
                if not should_confirm:
                    continue
                
                # If Whisper confirmation is disabled, we're done
                if not state_machine.confirm_with_whisper:
                    detected = True
                    break
                
                # Collect audio for confirmation
                logger("Collecting audio for Whisper confirmation...")
                
                # Get pre-trigger buffer
                buffered_audio = state_machine.get_buffered_audio()
                
                # Record post-trigger audio
                post_trigger_frames = []
                post_start = time.time()
                post_duration = state_machine.post_trigger_record_s
                
                while time.time() - post_start < post_duration:
                    post_frame = mic_stream.read_frame(timeout=0.05)
                    if post_frame is not None:
                        post_trigger_frames.append(post_frame)
                
                # Combine buffered and post-trigger audio
                if post_trigger_frames:
                    post_audio = np.concatenate(post_trigger_frames)
                    if buffered_audio is not None:
                        confirmation_audio = np.concatenate([buffered_audio, post_audio])
                    else:
                        confirmation_audio = post_audio
                else:
                    confirmation_audio = buffered_audio
                
                # Transcribe with Whisper
                if confirmation_audio is not None and len(confirmation_audio) > 0:
                    try:
                        # Convert to float32 in range [-1, 1] for Whisper
                        audio_float = confirmation_audio.astype(np.float32) / 32768.0
                        
                        # Use Whisper to transcribe
                        # We need to pass audio to stt_vosk or directly to Whisper
                        # For now, use a simple approach - save to temporary buffer
                        # and use existing STT infrastructure
                        
                        # Get expected phrases
                        expected_phrases = getattr(config_module, "HOTWORD_KEYWORDS", ["wyzer"])
                        all_phrases = list(expected_phrases)
                        all_phrases.extend(getattr(config_module, "HOTWORD_ALIASES", []))
                        
                        # Transcribe confirmation audio using Whisper
                        # This is a simplified version - ideally integrate with stt_vosk
                        transcript = _transcribe_audio_chunk(audio_float, config_module, logger)
                        
                        # Check if transcript confirms the hotword
                        if state_machine.confirm_with_transcript(transcript, all_phrases):
                            detected = True
                            break
                        else:
                            # Confirmation failed - reset and continue
                            state_machine.reset_to_idle()
                            hotword_engine.reset()
                    
                    except Exception as exc:
                        logger(f"Whisper confirmation failed: {exc}")
                        state_machine.reset_to_idle()
                else:
                    logger("No audio collected for confirmation.")
                    state_machine.reset_to_idle()
    
    finally:
        # Clean up
        mic_stream.stop()
        hotword_engine.close()
        
        # Log statistics
        stream_stats = mic_stream.get_stats()
        rejection_stats = state_machine.get_rejection_stats()
        logger(f"Stream stats: {stream_stats}")
        logger(f"Rejection stats: {rejection_stats}")
    
    return detected


def _transcribe_audio_chunk(audio_float: np.ndarray, config_module, logger) -> str:
    """Transcribe an audio chunk using Whisper for hotword confirmation.
    
    Args:
        audio_float: Audio as float32 numpy array in range [-1, 1].
        config_module: Configuration module.
        logger: Logging function.
    
    Returns:
        Transcribed text string, or empty string if unavailable/failed.
    """
    try:
        # Convert float32 to int16 for transcribe_pcm16
        audio_i16 = (audio_float * 32767).astype(np.int16)
        
        # Use the new transcribe_pcm16 API from stt_whisper with hotword_confirm mode
        transcript = stt_whisper.transcribe_pcm16(audio_i16, sample_rate=16000, mode="hotword_confirm")
        
        logger(f"[CONFIRM] transcript=\"{transcript}\"")
        
        # Check if transcript matches confirmation phrases
        confirm_phrases = getattr(config_module, "HOTWORD_CONFIRM_PHRASES", 
                                   ["hey jarvis", "jarvis", "hey wyzer", "wyzer"])
        fail_open = getattr(config_module, "HOTWORD_CONFIRM_FAIL_OPEN", True)
        
        if not transcript:
            if fail_open:
                logger("[CONFIRM] Transcript empty; accepting wake (fail-open enabled)")
                return "<fail-open>"  # Signal to accept wake despite empty transcript
            else:
                logger("[CONFIRM] Transcript empty; rejecting wake")
                return ""
        
        # Case-insensitive contains match
        transcript_lower = transcript.lower()
        for phrase in confirm_phrases:
            if phrase.lower() in transcript_lower:
                logger(f"[CONFIRM] Matched phrase: '{phrase}'")
                return transcript
        
        logger(f"[CONFIRM] No matching phrase in transcript")
        return ""
    
    except Exception as exc:
        logger(f"[CONFIRM] Transcription error: {exc}")
        fail_open = getattr(config_module, "HOTWORD_CONFIRM_FAIL_OPEN", True)
        if fail_open:
            logger("[CONFIRM] Error occurred; accepting wake (fail-open enabled)")
            return "<fail-open>"
        return ""


# Global state machine for tracking wake state across the application
_GLOBAL_STATE_MACHINE: Optional[WakeStateMachine] = None
_STATE_LOCK = threading.Lock()


def get_global_state_machine(config_module=None, logger=default_logger) -> Optional[WakeStateMachine]:
    """Get or create the global wake state machine.
    
    Args:
        config_module: Configuration module (required for first initialization).
        logger: Logging function.
    
    Returns:
        WakeStateMachine instance, or None if not initialized.
    """
    global _GLOBAL_STATE_MACHINE
    
    with _STATE_LOCK:
        if _GLOBAL_STATE_MACHINE is None and config_module is not None:
            try:
                _GLOBAL_STATE_MACHINE = create_state_machine_from_config(config_module, logger=logger)
            except Exception as exc:
                logger(f"Failed to create global state machine: {exc}")
                return None
        
        return _GLOBAL_STATE_MACHINE


def should_skip_voice_typing(config_module=None, logger=default_logger) -> bool:
    """Check if voice typing should be skipped due to recent wake confirmation.
    
    This prevents voice typing from stealing commands when the assistant
    is actively processing a query or was recently woken.
    
    Args:
        config_module: Configuration module.
        logger: Logging function.
    
    Returns:
        True if voice typing should be skipped, False otherwise.
    """
    state_machine = get_global_state_machine(config_module, logger)
    if state_machine is None:
        return False
    
    return state_machine.should_skip_voice_typing()
