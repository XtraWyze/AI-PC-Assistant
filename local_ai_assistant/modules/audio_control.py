"""Utilities for adjusting per-application volume via Windows Core Audio."""
from __future__ import annotations

import difflib
from typing import Dict, List, Optional

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume


def _normalize_name(name: str) -> str:
    normalized = (name or "").strip().lower()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    return normalized


def get_app_sessions(clsctx: int = CLSCTX_ALL) -> Dict[str, ISimpleAudioVolume]:
    """Return mapping of normalized process name to an audio volume interface."""
    sessions: Dict[str, ISimpleAudioVolume] = {}
    for session in AudioUtilities.GetAllSessions():
        process = getattr(session, "Process", None)
        if process is None:
            continue
        try:
            process_name = process.name()
        except Exception:
            continue
        normalized = _normalize_name(process_name)
        if not normalized:
            continue
        control = getattr(session, "_ctl", None)
        if control is None:
            continue
        try:
            volume = control.QueryInterface(ISimpleAudioVolume)
        except Exception:
            continue
        sessions[normalized] = volume
    return sessions


def find_app_volume_target(app_query: str) -> Optional[ISimpleAudioVolume]:
    """Return the best matching app volume control for the provided name."""
    candidate = _normalize_name(app_query)
    if not candidate:
        return None
    sessions = get_app_sessions()
    if candidate in sessions:
        return sessions[candidate]
    matches: List[str] = difflib.get_close_matches(candidate, list(sessions.keys()), n=1, cutoff=0.6)
    if not matches:
        return None
    return sessions[matches[0]]


def set_app_volume(app_query: str, volume_percent: float) -> bool:
    """Set the volume of an app (0-100%)."""
    target = find_app_volume_target(app_query)
    if not target:
        return False
    clamped = max(0.0, min(100.0, float(volume_percent)))
    scalar = clamped / 100.0
    try:
        target.SetMasterVolume(scalar, None)
    except Exception:
        return False
    return True


def change_app_volume(app_query: str, delta_percent: float) -> bool:
    """Adjust the current volume of an app by *delta_percent*."""
    target = find_app_volume_target(app_query)
    if not target:
        return False
    try:
        current = float(target.GetMasterVolume()) * 100.0
    except Exception:
        return False
    new_value = max(0.0, min(100.0, current + float(delta_percent)))
    try:
        target.SetMasterVolume(new_value / 100.0, None)
    except Exception:
        return False
    return True


def mute_app(app_query: str, mute: bool = True) -> bool:
    """Mute or unmute the specified app."""
    target = find_app_volume_target(app_query)
    if not target:
        return False
    try:
        target.SetMute(1 if mute else 0, None)
    except Exception:
        return False
    return True
