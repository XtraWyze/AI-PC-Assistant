"""Helpers for launching child processes that outlive the assistant."""
from __future__ import annotations

import os
import subprocess
from typing import Sequence

# Windows creation flag fallbacks (defined manually for type-checkers/Unix)
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


Command = Sequence[str | os.PathLike[str]]


def _windows_creation_flags() -> int:
    if os.name != "nt":
        return 0
    detached = getattr(subprocess, "DETACHED_PROCESS", _DETACHED_PROCESS)
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", _CREATE_NEW_PROCESS_GROUP)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW)
    return detached | new_group | no_window


def launch_detached(command: Command, *, cwd: str | os.PathLike[str] | None = None) -> subprocess.Popen[bytes]:
    """Start *command* so the child stays up even if the console closes."""
    creationflags = _windows_creation_flags()
    normalized = [str(part) for part in command]
    return subprocess.Popen(  # noqa: S603 - user-local commands only
        normalized,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=os.name != "nt",
    )
