"""Local time and date helper for Wyzer's environment tools."""
from __future__ import annotations

from datetime import datetime
from typing import Dict


def get_time_date() -> Dict[str, str]:
    """Return the local time, ISO date, and weekday name."""
    current = datetime.now().astimezone()
    return {
        "time": current.strftime("%I:%M %p"),
        "date": current.strftime("%Y-%m-%d"),
        "weekday": current.strftime("%A"),
    }
