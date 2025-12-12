"""Offline hotword detection using openWakeWord.

This module provides keyword spotting (KWS) using openWakeWord for local,
offline wake word detection. It processes 16kHz mono audio frames and
outputs confidence scores plus triggered events when thresholds are met.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import numpy as np

if TYPE_CHECKING:
    try:
        from openwakeword.model import Model as OpenWakeWordModel
    except ImportError:
        OpenWakeWordModel = None  # type: ignore
else:
    try:
        from openwakeword.model import Model as OpenWakeWordModel
    except ImportError:
        OpenWakeWordModel = None  # type: ignore

from utils.logger import log


class HotwordEngine:
    """Lightweight keyword spotting engine using openWakeWord.
    
    Processes 16kHz mono audio frames and returns hotword detection scores.
    Supports built-in models and custom model paths for trained keywords.
    """

    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        custom_model_paths: Optional[List[str]] = None,
        threshold: float = 0.80,
        debounce_frames: int = 4,
        logger=log,
    ):
        """Initialize the hotword detection engine.
        
        Args:
            keywords: List of keyword names to load (e.g., ["alexa", "hey_jarvis"]).
                     If None or empty, loads all available built-in models.
            custom_model_paths: List of paths to custom .tflite/.onnx model files.
            threshold: Confidence threshold (0.0-1.0) for triggering detection.
            debounce_frames: Number of consecutive frames above threshold required.
            logger: Logging function to use for messages.
        """
        self.logger = logger
        self.threshold = threshold
        self.debounce_frames = debounce_frames
        self._model = None
        self._consecutive_count = 0
        self._last_scores: dict[str, float] = {}
        
        # Rate-limited debug logging
        self._last_audio_debug_time = 0.0
        self._audio_debug_interval = 1.0  # seconds
        
        # Pending buffer for 80ms chunk accumulation (1280 samples at 16kHz)
        self._chunk_size = 1280  # 80ms * 16000 Hz
        self._pending_buffer = np.array([], dtype=np.int16)
        
        if OpenWakeWordModel is None:
            raise ImportError(
                "openWakeWord is not installed. Install it with: pip install openwakeword"
            )
        
        # Initialize the model
        try:
            # Determine which models to load
            if custom_model_paths:
                # Load custom models
                self.logger(f"Loading custom hotword models: {custom_model_paths}")
                self._model = OpenWakeWordModel(wakeword_models=custom_model_paths)
            elif keywords:
                # Load specific built-in keywords
                # openWakeWord uses specific model names; map common names
                model_names = self._map_keyword_names(keywords)
                self.logger(f"Loading built-in hotword models: {model_names}")
                self._model = OpenWakeWordModel(wakeword_models=model_names)
            else:
                # Load all available built-in models
                self.logger("Loading all available built-in hotword models")
                self._model = OpenWakeWordModel()
            
            # Get list of loaded models
            loaded = list(self._model.models.keys()) if hasattr(self._model, 'models') else []
            self.logger(f"Hotword engine initialized with models: {loaded}")
            
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize openWakeWord: {exc}") from exc
    
    def _map_keyword_names(self, keywords: List[str]) -> List[str]:
        """Map user-friendly keyword names to openWakeWord model names.
        
        openWakeWord built-in models use canonical names with spaces:
        - alexa
        - hey jarvis
        - hey mycroft
        - hey rhasspy
        - timer
        - weather
        
        For "wyzer", "hey wyzer", or "computer", we'll use the closest available model
        (hey jarvis or hey mycroft) as placeholders.
        """
        mapping = {
            "wyzer": "hey jarvis",  # Placeholder until custom model available
            "hey wyzer": "hey jarvis",
            "hey wizer": "hey jarvis",
            "computer": "hey jarvis",  # Map "computer" to hey jarvis
            "alexa": "alexa",
            "hey jarvis": "hey jarvis",
            "jarvis": "hey jarvis",
            "hey mycroft": "hey mycroft",
            "mycroft": "hey mycroft",
            "hey rhasspy": "hey rhasspy",
            "rhasspy": "hey rhasspy",
            "timer": "timer",
            "weather": "weather",
        }
        
        model_names = []
        for keyword in keywords:
            normalized = keyword.lower().strip()
            model_name = mapping.get(normalized, normalized)
            model_names.append(model_name)
            if normalized in ("wyzer", "hey wyzer", "hey wizer", "computer"):
                self.logger(
                    f"Note: Using 'hey_jarvis' as placeholder for '{keyword}'. "
                    f"Add a custom '{keyword}' model via custom_model_paths for exact matching."
                )
        
        return model_names
    
    def process_frame(self, audio_frame: np.ndarray) -> tuple[float, bool]:
        """Process a single audio frame and return detection results.
        
        Accumulates incoming 20ms frames into 80ms chunks before calling predict().
        This follows openWakeWord's recommended streaming approach.
        
        Args:
            audio_frame: 16kHz mono audio as numpy array (typically 20ms = 320 samples).
        
        Returns:
            Tuple of (max_score, triggered):
                - max_score: Highest confidence score across all models (0.0-1.0)
                - triggered: True if debounced threshold is met
        """
        if self._model is None:
            return 0.0, False
        
        try:
            # Convert audio to int16 PCM format (openWakeWord expects int16, not float32)
            if audio_frame.dtype == np.float32:
                # Convert float32 [-1, 1] to int16 PCM
                audio_frame = np.clip(audio_frame, -1.0, 1.0)
                audio_frame = (audio_frame * 32767).astype(np.int16)
            elif audio_frame.dtype != np.int16:
                # Convert other types to int16
                audio_frame = audio_frame.astype(np.int16)
            
            # Ensure 1D contiguous array
            if audio_frame.ndim > 1:
                audio_frame = audio_frame.flatten()
            audio_frame = np.ascontiguousarray(audio_frame)
            
            # Append new frame to pending buffer
            self._pending_buffer = np.concatenate([self._pending_buffer, audio_frame])
            
            # Process complete 80ms chunks (1280 samples at 16kHz)
            max_score = 0.0
            triggered = False
            
            while len(self._pending_buffer) >= self._chunk_size:
                # Extract 80ms chunk
                chunk = self._pending_buffer[:self._chunk_size]
                self._pending_buffer = self._pending_buffer[self._chunk_size:]
                
                # Ensure chunk is contiguous
                chunk = np.ascontiguousarray(chunk)
                
                # Rate-limited debug logging
                import time
                current_time = time.time()
                if current_time - self._last_audio_debug_time >= self._audio_debug_interval:
                    self._last_audio_debug_time = current_time
                    self.logger(
                        f"[WAKE] chunk_ms=80 samples={len(chunk)} "
                        f"dtype={chunk.dtype} "
                        f"min={chunk.min()} max={chunk.max()}"
                    )
                
                # Predict on 80ms chunk - returns dict of model_name -> confidence score
                predictions = self._model.predict(chunk)
                
                # Get maximum score across all models
                if predictions:
                    self._last_scores = predictions
                    chunk_max = max(predictions.values())
                    max_score = max(max_score, chunk_max)
                    
                    # Rate-limited score logging
                    if current_time - self._last_audio_debug_time >= self._audio_debug_interval:
                        self.logger(f"[WAKE] scores={predictions} max={chunk_max:.3f}")
                
                # Debouncing logic on this chunk's result
                if chunk_max >= self.threshold:
                    self._consecutive_count += 1
                else:
                    self._consecutive_count = 0
                
                # Trigger if we've met the debounce requirement
                if self._consecutive_count >= self.debounce_frames:
                    triggered = True
                    self._consecutive_count = 0
            
            return max_score, triggered
            
        except Exception as exc:
            self.logger(f"Error processing audio frame: {exc}")
            return 0.0, False
    
    def reset(self) -> None:
        """Reset the internal state (debounce counter, etc.)."""
        self._consecutive_count = 0
        self._last_scores = {}
        # Clear pending buffer
        self._pending_buffer = np.array([], dtype=np.int16)
        if self._model is not None:
            try:
                # Reset model state if supported
                if hasattr(self._model, 'reset'):
                    self._model.reset()
            except Exception as exc:
                self.logger(f"Error resetting model state: {exc}")
    
    def get_last_scores(self) -> dict[str, float]:
        """Return the most recent prediction scores for all loaded models."""
        return self._last_scores.copy()
    
    def close(self) -> None:
        """Clean up resources."""
        self._model = None
        self._consecutive_count = 0
        self._last_scores = {}
        self._pending_buffer = np.array([], dtype=np.int16)


def create_engine_from_config(config_module, logger=log) -> HotwordEngine:
    """Factory function to create a HotwordEngine from config settings.
    
    Args:
        config_module: Configuration module with HOTWORD_* settings.
        logger: Logging function.
    
    Returns:
        Initialized HotwordEngine instance.
    """
    keywords = getattr(config_module, "HOTWORD_KEYWORDS", ["hey jarvis"])
    custom_paths = getattr(config_module, "HOTWORD_MODEL_PATHS", [])
    threshold = float(getattr(config_module, "HOTWORD_THRESHOLD", 0.80))
    debounce = int(getattr(config_module, "HOTWORD_DEBOUNCE_FRAMES", 4))
    
    return HotwordEngine(
        keywords=keywords,
        custom_model_paths=custom_paths if custom_paths else None,
        threshold=threshold,
        debounce_frames=debounce,
        logger=logger,
    )
