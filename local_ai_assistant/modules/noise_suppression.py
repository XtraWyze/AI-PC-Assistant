"""Noise suppression module for audio preprocessing."""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import noisereduce as nr
    _NOISEREDUCE_AVAILABLE = True
except ImportError:
    _NOISEREDUCE_AVAILABLE = False

import config
from utils.logger import log


class NoiseSuppressionFilter:
    """Applies noise reduction to audio signals."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        stationary: bool = True,
        prop_decrease: float = 1.0,
        logger=log,
    ):
        """
        Initialize noise suppression filter.
        
        Args:
            sample_rate: Audio sample rate in Hz
            stationary: If True, assumes stationary noise (more aggressive)
            prop_decrease: Proportion of noise to reduce (0.0-1.0, default 1.0)
            logger: Logger function
        """
        self.sample_rate = sample_rate
        self.stationary = stationary
        self.prop_decrease = prop_decrease
        self.logger = logger
        self.enabled = _NOISEREDUCE_AVAILABLE and getattr(config, "NOISE_SUPPRESSION_ENABLED", True)
        
        if not _NOISEREDUCE_AVAILABLE:
            self.logger("noisereduce not available; noise suppression will be disabled.")
        elif not self.enabled:
            self.logger("Noise suppression is disabled in config.")
    
    def reduce_noise(
        self,
        audio: np.ndarray,
        noise_profile: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Apply noise reduction to audio signal.
        
        Args:
            audio: Input audio as float32 numpy array
            noise_profile: Optional noise profile for non-stationary noise reduction
            
        Returns:
            Noise-reduced audio as float32 numpy array
        """
        if not self.enabled or not _NOISEREDUCE_AVAILABLE:
            return audio
        
        if audio is None or audio.size == 0:
            return audio
        
        try:
            # Ensure audio is float32
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)
            
            # Apply noise reduction
            reduced = nr.reduce_noise(
                y=audio,
                sr=self.sample_rate,
                stationary=self.stationary,
                prop_decrease=self.prop_decrease,
                y_noise=noise_profile,
            )
            
            return reduced.astype(np.float32)
            
        except Exception as exc:
            self.logger(f"Noise suppression failed: {exc}")
            return audio
    
    def reduce_noise_from_bytes(
        self,
        pcm_bytes: bytes,
        noise_profile: Optional[np.ndarray] = None,
    ) -> bytes:
        """
        Apply noise reduction to PCM audio bytes (int16).
        
        Args:
            pcm_bytes: Input audio as PCM bytes (int16)
            noise_profile: Optional noise profile for non-stationary noise reduction
            
        Returns:
            Noise-reduced audio as PCM bytes (int16)
        """
        if not self.enabled or not _NOISEREDUCE_AVAILABLE:
            return pcm_bytes
        
        if not pcm_bytes:
            return pcm_bytes
        
        try:
            # Convert to float32
            samples = np.frombuffer(pcm_bytes, dtype=np.int16)
            if samples.size == 0:
                return pcm_bytes
            
            float_audio = samples.astype(np.float32) / 32768.0
            
            # Apply noise reduction
            reduced = self.reduce_noise(float_audio, noise_profile)
            
            # Convert back to int16
            int_audio = (reduced * 32768.0).clip(-32768, 32767).astype(np.int16)
            
            return int_audio.tobytes()
            
        except Exception as exc:
            self.logger(f"Noise suppression failed: {exc}")
            return pcm_bytes


# Singleton instance
_NOISE_FILTER: Optional[NoiseSuppressionFilter] = None


def get_noise_filter(sample_rate: int = 16000) -> NoiseSuppressionFilter:
    """Get or create the singleton noise suppression filter."""
    global _NOISE_FILTER
    if _NOISE_FILTER is None:
        stationary = getattr(config, "NOISE_SUPPRESSION_STATIONARY", True)
        prop_decrease = float(getattr(config, "NOISE_SUPPRESSION_STRENGTH", 1.0))
        _NOISE_FILTER = NoiseSuppressionFilter(
            sample_rate=sample_rate,
            stationary=stationary,
            prop_decrease=prop_decrease,
        )
    return _NOISE_FILTER


def reset_noise_filter():
    """Reset the singleton noise suppression filter."""
    global _NOISE_FILTER
    _NOISE_FILTER = None
