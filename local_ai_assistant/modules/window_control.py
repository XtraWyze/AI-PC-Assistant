"""Window and application management helpers for the assistant."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:  # pragma: no cover - Windows-only dependency handling
    import win32con
    import win32gui
    import win32api
    import win32process
except ImportError:  # pragma: no cover - handled gracefully at runtime
    win32con = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    win32api = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import psutil
except ImportError:  # pragma: no cover - handled gracefully at runtime
    psutil = None  # type: ignore[assignment]

from utils.logger import log
from utils.processes import launch_detached

APP_ALIASES: Dict[str, List[str]] = {
    "discord": ["discord", "discord.exe"],
    "steam": ["steam", "steam.exe"],
    "chrome": ["chrome", "google chrome", "chrome.exe"],
    "spotify": ["spotify", "spotify.exe"],
    "notepad": ["notepad", "notepad.exe"],
}

APP_LAUNCH_MAP: Dict[str, str] = {
    "discord": r"C:\\Users\\Public\\Desktop\\Discord.lnk",
    "steam": r"C:\\Program Files (x86)\\Steam\\Steam.exe",
    "chrome": r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "spotify": r"C:\\Users\\Public\\Desktop\\Spotify.lnk",
}

MOVE_ACTIONS = {"move", "move_window", "move_to_monitor"}
ACTIONS = {"focus", "switch", "bring_up", "minimize", "maximize", "restore", *MOVE_ACTIONS}


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str
    exe_path: str


@dataclass
class MonitorInfo:
    index: int
    handle: int
    rect: Tuple[int, int, int, int]
    is_primary: bool


def normalize_app_name(name: Optional[str]) -> str:
    if not name:
        return ""
    cleaned = " ".join(name.strip().lower().split())
    return cleaned


def _dependencies_ready() -> Tuple[bool, str]:
    missing: List[str] = []
    if win32gui is None or win32con is None or win32process is None or win32api is None:
        missing.append("pywin32")
    if psutil is None:
        missing.append("psutil")
    if missing:
        parts = ", ".join(missing)
        return False, f"Window control requires {parts}. Please install missing dependencies."
    return True, ""


def _resolve_aliases(target_app: str) -> List[str]:
    if not target_app:
        return []
    aliases = APP_ALIASES.get(target_app, [])
    extras = [target_app]
    if target_app.endswith(".exe"):
        extras.append(target_app[:-4])
    return list(dict.fromkeys([alias.lower() for alias in aliases + extras if alias]))


def _enum_windows() -> List[WindowInfo]:
    items: List[WindowInfo] = []
    if win32gui is None:
        return items

    def _callback(hwnd, _param):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        rect = win32gui.GetWindowRect(hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width <= 0 or height <= 0:
            return True
        _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        exe_path = ""
        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                process_name = (proc.name() or "").lower()
                exe_path = proc.exe() or ""
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        items.append(WindowInfo(hwnd=hwnd, title=title, pid=pid, process_name=process_name, exe_path=exe_path.lower()))
        return True

    win32gui.EnumWindows(_callback, None)
    return items


def _list_monitors() -> List[MonitorInfo]:
    monitors: List[MonitorInfo] = []
    if win32api is None or win32con is None:
        return monitors

    try:
        raw_monitors = win32api.EnumDisplayMonitors()
    except Exception as exc:  # pragma: no cover - OS-specific behavior
        log(f"EnumDisplayMonitors failed: {exc}")
        return monitors

    for idx, (handle, _hdc, rect) in enumerate(raw_monitors, start=1):
        try:
            info = win32api.GetMonitorInfo(handle)
        except Exception as exc:  # pragma: no cover - OS-specific behavior
            log(f"GetMonitorInfo failed for monitor {idx}: {exc}")
            info = {"Monitor": rect, "Flags": 0}
        bounds = info.get("Monitor", rect)
        is_primary = bool(info.get("Flags", 0) & win32con.MONITORINFOF_PRIMARY)
        monitors.append(MonitorInfo(index=idx, handle=handle, rect=bounds, is_primary=is_primary))

    monitors.sort(key=lambda mon: (mon.rect[0], mon.rect[1]))
    for idx, mon in enumerate(monitors, start=1):
        mon.index = idx
    return monitors


def _monitor_label(monitor: MonitorInfo) -> str:
    if monitor.is_primary:
        return "primary monitor"
    return f"monitor {monitor.index}"


def _monitor_for_window(hwnd: int, monitors: List[MonitorInfo]) -> Optional[MonitorInfo]:
    if win32api is None or win32con is None:
        return None
    handle = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    for monitor in monitors:
        if monitor.handle == handle:
            return monitor
    return None


def _parse_monitor_hint(hint: Optional[str]) -> str:
    if not hint:
        return ""
    cleaned = normalize_app_name(hint)
    if cleaned.startswith("monitor"):
        cleaned = cleaned.replace("monitor", "").strip()
    return cleaned


def _select_monitor(
    monitors: List[MonitorInfo],
    hint: Optional[str],
    current_monitor: Optional[MonitorInfo],
) -> Optional[MonitorInfo]:
    if not monitors:
        return None
    parsed = _parse_monitor_hint(hint)
    if not parsed and current_monitor and len(monitors) > 1:
        parsed = "next"
    if not parsed and current_monitor:
        return current_monitor
    if parsed in {"current", "same"} and current_monitor:
        return current_monitor
    if parsed in {"primary", "main"}:
        for monitor in monitors:
            if monitor.is_primary:
                return monitor
        return monitors[0]
    number_match = re.search(r"(\d+)", parsed)
    if number_match:
        index = int(number_match.group(1))
        if 1 <= index <= len(monitors):
            return monitors[index - 1]
    if parsed in {"next", "right"} and current_monitor:
        idx = monitors.index(current_monitor)
        return monitors[(idx + 1) % len(monitors)]
    if parsed in {"prev", "previous", "left", "other"} and current_monitor:
        idx = monitors.index(current_monitor)
        return monitors[(idx - 1) % len(monitors)]
    if not parsed:
        return monitors[0]
    for monitor in monitors:
        if parsed in _monitor_label(monitor):
            return monitor
    return None


def _move_window_to_monitor(hwnd: int, monitor_hint: Optional[str]) -> Tuple[bool, str]:
    if win32gui is None or win32con is None:
        return False, "pywin32 is required for monitor control."
    monitors = _list_monitors()
    if not monitors:
        return False, "Unable to enumerate monitors."
    current_monitor = _monitor_for_window(hwnd, monitors)
    target_monitor = _select_monitor(monitors, monitor_hint, current_monitor)
    if not target_monitor:
        return False, "Unable to determine the requested monitor."
    if current_monitor and current_monitor.handle == target_monitor.handle:
        return True, f"Already on { _monitor_label(target_monitor) }."

    rect = win32gui.GetWindowRect(hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    monitor_left, monitor_top, monitor_right, monitor_bottom = target_monitor.rect
    available_width = monitor_right - monitor_left
    available_height = monitor_bottom - monitor_top
    new_width = min(width, available_width)
    new_height = min(height, available_height)
    offset_x = max(0, (available_width - new_width) // 2)
    offset_y = max(0, (available_height - new_height) // 2)
    new_left = monitor_left + offset_x
    new_top = monitor_top + offset_y

    try:
        win32gui.MoveWindow(hwnd, new_left, new_top, new_width, new_height, True)
        focus_window(hwnd)
    except Exception as exc:  # pragma: no cover - OS-specific behavior
        return False, f"Unable to move window: {exc}"
    label = _monitor_label(target_monitor)
    return True, f"Moved to {label}."


def _window_from_hwnd(hwnd: int) -> Optional[WindowInfo]:
    if hwnd == 0 or win32gui is None:
        return None
    title = win32gui.GetWindowText(hwnd).strip()
    if not title:
        title = "(untitled)"
    _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = ""
    exe_path = ""
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            process_name = (proc.name() or "").lower()
            exe_path = proc.exe() or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return WindowInfo(hwnd=hwnd, title=title, pid=pid, process_name=process_name, exe_path=exe_path.lower())


def find_matching_windows(target_app: Optional[str]) -> List[WindowInfo]:
    if win32gui is None:
        return []
    if not target_app:
        hwnd = win32gui.GetForegroundWindow()
        info = _window_from_hwnd(hwnd)
        return [info] if info else []

    alias_list = _resolve_aliases(normalize_app_name(target_app))
    if not alias_list:
        alias_list = [normalize_app_name(target_app)]
    windows = _enum_windows()
    matches: List[WindowInfo] = []
    for window in windows:
        title = window.title.lower()
        exe_name = os.path.basename(window.exe_path).lower()
        for alias in alias_list:
            if not alias:
                continue
            if alias in title or alias == window.process_name or alias in exe_name:
                matches.append(window)
                break
    return matches


def focus_window(hwnd: int) -> bool:
    if win32gui is None or win32con is None:
        return False
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:  # pragma: no cover - OS-specific behavior
        log(f"Focus failed: {exc}")
        return False


def minimize_window(hwnd: int) -> bool:
    if win32gui is None or win32con is None:
        return False
    return win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE) != 0


def maximize_window(hwnd: int) -> bool:
    if win32gui is None or win32con is None:
        return False
    return win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE) != 0


def restore_window(hwnd: int) -> bool:
    if win32gui is None or win32con is None:
        return False
    return win32gui.ShowWindow(hwnd, win32con.SW_RESTORE) != 0


def _launch_app(target_app: str) -> Tuple[bool, str]:
    path = APP_LAUNCH_MAP.get(target_app)
    if not path:
        return False, f"No launch path configured for '{target_app}'."
    expanded = os.path.expandvars(path)
    if not os.path.exists(expanded):
        return False, f"Configured launch path does not exist: {expanded}"
    try:
        if expanded.lower().endswith(".lnk"):
            os.startfile(expanded)  # type: ignore[attr-defined]
        else:
            launch_detached([expanded])
        return True, f"Launching {target_app.title()}..."
    except OSError as exc:
        return False, f"Failed to launch {target_app}: {exc}"


def _format_window_label(window: WindowInfo, fallback: str) -> str:
    if window.title and window.title.lower() != "(untitled)":
        return window.title
    if window.process_name:
        return window.process_name
    return fallback


def handle_window_control(
    action: str,
    target_app: Optional[str] = None,
    monitor: Optional[str] = None,
) -> Dict[str, object]:
    normalized_action = normalize_app_name(action)
    if normalized_action not in ACTIONS:
        return {"success": False, "message": f"Unsupported action '{action}'."}

    ready, message = _dependencies_ready()
    if not ready:
        return {"success": False, "message": message}

    target_key = normalize_app_name(target_app)
    windows = find_matching_windows(target_key if target_key else None)
    label = target_key or "current window"

    if normalized_action in {"focus", "switch", "bring_up"}:
        if windows:
            window = windows[0]
            if focus_window(window.hwnd):
                name = _format_window_label(window, label)
                return {"success": True, "message": f"Brought {name} to the front."}
            return {"success": False, "message": f"Unable to focus {label}."}
        if target_key:
            launched, launch_message = _launch_app(target_key)
            return {"success": launched, "message": launch_message}
        return {"success": False, "message": "No active window found."}

    if not windows:
        return {"success": False, "message": f"No matching window found for '{label}'."}

    window = windows[0]
    name = _format_window_label(window, label)
    if normalized_action in MOVE_ACTIONS:
        success, move_message = _move_window_to_monitor(window.hwnd, monitor)
        return {"success": success, "message": move_message}
    if normalized_action == "minimize":
        if minimize_window(window.hwnd):
            return {"success": True, "message": f"Minimized {name}."}
        return {"success": False, "message": f"Failed to minimize {name}."}
    if normalized_action == "maximize":
        if maximize_window(window.hwnd):
            return {"success": True, "message": f"Maximized {name}."}
        return {"success": False, "message": f"Failed to maximize {name}."}
    if normalized_action == "restore":
        if restore_window(window.hwnd):
            return {"success": True, "message": f"Restored {name}."}
        return {"success": False, "message": f"Failed to restore {name}."}

    return {"success": False, "message": f"Action '{action}' is not implemented."}
