"""Tkinter GUI launcher for the Wyzer Local Modular AI Assistant."""
from __future__ import annotations

import importlib
import inspect
import io
import json
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

import tkinter as tk
from tkinter import ttk

import config
from assistant.orchestrator import Orchestrator
from modules import (
    app_registry,
    audio_control,
    commands_toolkit,
    conversation_manager,
    file_indexer,
    file_search,
    gamebar_recorder,
    llm_engine,
    memory_manager,
    voice_typing,
    window_control,
)
from modules import hotword_detector, stt_vosk, tts_engine
from modules.tools import (
    get_location,
    get_time_date,
    get_weather,
    open_file_location,
    open_path,
    open_website,
    web_access,
)


class ConsoleRedirect(io.TextIOBase):
    """Mirror stdout/stderr into the GUI console while preserving originals."""

    def __init__(self, append_fn: Callable[[str], None], original: Optional[io.TextIOBase]) -> None:
        self.append_fn = append_fn
        self.original = original

    def write(self, message: str) -> int:  # type: ignore[override]
        if message and not message.isspace():
            self.append_fn(message)
        if self.original is not None:
            self.original.write(message)
        return len(message)

    def flush(self) -> None:  # type: ignore[override]
        if self.original is not None:
            self.original.flush()


class ScrollableFrame(ttk.Frame):
    """Reusable scrollable frame based on a canvas+window pair."""

    def __init__(self, master: tk.Widget, *, height: int = 200, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height, bg="#202225", bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            "<Configure>",
            lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)


class WyzerGUI(tk.Tk):
    """Main Tkinter window hosting the Wyzer assistant controls."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Wyzer Assistant Console")
        self.geometry("1200x720")
        self.minsize(960, 640)
        self.configure(bg="#1b1d23")
        self._configure_style()

        base_dir = Path(__file__).resolve().parent.parent
        self.modules_dir = base_dir / "modules"
        self.tools_manifest = base_dir / "tools" / "tools_manifest.json"

        self.orchestrator = Orchestrator()
        self.orchestrator.set_system_prompt(getattr(config, "SYSTEM_PREAMBLE", None))
        self.orchestrator.load_tools()
        self.conversation_state = self.orchestrator.reset_conversation()

        self.tool_buttons: Dict[str, ttk.Button] = {}
        self.feature_buttons: Dict[str, ttk.Button] = {}
        self.tts_ready = False
        self.hotword_thread: Optional[threading.Thread] = None
        self.hotword_stop_event: Optional[threading.Event] = None

        self._build_layout()
        self._redirect_console_output()
        self.load_tools()
        self.load_features()

    # ------------------------------------------------------------------
    # Layout + styling
    # ------------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TFrame",
            background="#1b1d23",
        )
        style.configure(
            "TLabel",
            background="#1b1d23",
            foreground="#f1f3f5",
            font=("Segoe UI", 11),
        )
        style.configure(
            "TButton",
            background="#2f3136",
            foreground="#f1f3f5",
            font=("Segoe UI", 10),
            padding=6,
        )
        style.map(
            "TButton",
            background=[("active", "#3b3d43")],
        )
        style.configure(
            "Header.TLabel",
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "Console.TFrame",
            background="#111217",
        )

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.controls_frame = ttk.Frame(self)
        self.controls_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self._build_controls()

        content_frame = ttk.Frame(self)
        content_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=2)
        content_frame.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(content_frame)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_panel.rowconfigure(1, weight=1)
        left_panel.rowconfigure(3, weight=1)

        tools_header = ttk.Label(left_panel, text="Tools", style="Header.TLabel")
        tools_header.grid(row=0, column=0, sticky="w")
        self.tools_frame = ScrollableFrame(left_panel, height=240)
        self.tools_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 12))

        features_header = ttk.Label(left_panel, text="Features", style="Header.TLabel")
        features_header.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.features_frame = ScrollableFrame(left_panel, height=240)
        self.features_frame.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

        console_container = ttk.Frame(content_frame, style="Console.TFrame")
        console_container.grid(row=0, column=1, sticky="nsew")
        console_container.rowconfigure(0, weight=1)
        console_container.columnconfigure(0, weight=1)

        console_header = ttk.Label(console_container, text="Console", style="Header.TLabel")
        console_header.grid(row=0, column=0, sticky="w", padx=6, pady=(4, 2))
        self.console_text = tk.Text(
            console_container,
            bg="#111217",
            fg="#f8f9fa",
            insertbackground="#f8f9fa",
            highlightthickness=0,
            borderwidth=0,
            wrap="word",
            font=("Consolas", 11),
        )
        self.console_text.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.console_text.configure(state=tk.DISABLED)

        console_scroll = ttk.Scrollbar(console_container, orient=tk.VERTICAL, command=self.console_text.yview)
        console_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 6))
        self.console_text.configure(yscrollcommand=console_scroll.set)

        input_frame = ttk.Frame(self)
        input_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 12))
        input_frame.columnconfigure(0, weight=1)

        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(input_frame, textvariable=self.command_var)
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", self.run_command)
        send_button = ttk.Button(input_frame, text="Send", command=self.run_command)
        send_button.grid(row=0, column=1)

    def _build_controls(self) -> None:
        buttons = [
            ("Toggle Hotword", self.toggle_hotword),
            ("Test TTS", self.test_tts),
            ("Test STT", self.test_stt),
            ("Refresh Tools", self.load_tools),
            ("Refresh Features", self.load_features),
        ]
        for idx, (label, handler) in enumerate(buttons):
            btn = ttk.Button(self.controls_frame, text=label, command=handler)
            btn.grid(row=0, column=idx, padx=(0, 8))
            self.controls_frame.columnconfigure(idx, weight=1)

    def _redirect_console_output(self) -> None:
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = ConsoleRedirect(self.append_console, self._original_stdout)
        sys.stderr = ConsoleRedirect(self.append_console, self._original_stderr)

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------
    def append_console(self, text: str) -> None:
        self.console_text.configure(state=tk.NORMAL)
        to_insert = text if text.endswith("\n") else f"{text}\n"
        self.console_text.insert(tk.END, to_insert)
        self.console_text.see(tk.END)
        self.console_text.configure(state=tk.DISABLED)

    def _async_append(self, text: str) -> None:
        self.after(0, lambda: self.append_console(text))

    def load_tools(self) -> None:
        self.orchestrator.load_tools()
        for child in self.tools_frame.inner.winfo_children():
            child.destroy()
        self.tool_buttons.clear()
        registry = self.orchestrator.tools_registry
        if not registry:
            ttk.Label(self.tools_frame.inner, text="No tools available.").pack(anchor="w", pady=4)
            return
        for name in sorted(registry.keys()):
            description = registry[name].get("description", "")
            btn = ttk.Button(
                self.tools_frame.inner,
                text=name,
                command=lambda tool_name=name: self.call_tool(tool_name),
            )
            btn.pack(fill=tk.X, expand=True, pady=2)
            if description:
                ttk.Label(self.tools_frame.inner, text=description, font=("Segoe UI", 9)).pack(
                    anchor="w", padx=4, pady=(0, 4)
                )
            self.tool_buttons[name] = btn

    def load_features(self) -> None:
        for child in self.features_frame.inner.winfo_children():
            child.destroy()
        self.feature_buttons.clear()
        module_names = self._discover_feature_modules()
        if not module_names:
            ttk.Label(self.features_frame.inner, text="No modules found.").pack(anchor="w", pady=4)
            return
        for module_name in module_names:
            btn = ttk.Button(
                self.features_frame.inner,
                text=module_name,
                command=lambda mod=module_name: self.show_feature_info(mod),
            )
            btn.pack(fill=tk.X, expand=True, pady=2)
            self.feature_buttons[module_name] = btn

    def run_command(self, event: Optional[tk.Event] = None) -> None:
        user_text = self.command_var.get().strip()
        if not user_text:
            return
        self.command_var.set("")
        self.append_console(f"You: {user_text}")
        worker = threading.Thread(target=self._chat_worker, args=(user_text,), daemon=True)
        worker.start()

    def _chat_worker(self, text: str) -> None:
        try:
            message = self.orchestrator.route(text, self.conversation_state)
            content = message.get("content") if isinstance(message, dict) else str(message)
            self._async_append(f"Wyzer: {content}")
        except Exception as exc:
            self._async_append(f"Error: {exc}")

    def call_tool(self, name: str) -> None:
        def worker() -> None:
            try:
                self._async_append(f"Running tool: {name}")
                result = self.orchestrator.run_tool(name, {})
                serialized = json.dumps(result, indent=2, default=str)
                self._async_append(f"Result: {serialized}")
            except Exception as exc:
                self._async_append(f"Tool '{name}' failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def show_feature_info(self, module_name: str) -> None:
        def worker() -> None:
            try:
                module = importlib.import_module(module_name)
                doc = inspect.getdoc(module) or "No documentation provided."
                self._async_append(f"{module_name}: {doc}")
            except Exception as exc:
                self._async_append(f"Unable to load {module_name}: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def toggle_hotword(self) -> None:
        if self.hotword_thread and self.hotword_thread.is_alive():
            if self.hotword_stop_event:
                self.hotword_stop_event.set()
            self._async_append("Stopping hotword listener...")
            return

        self.hotword_stop_event = threading.Event()
        self.hotword_thread = threading.Thread(target=self._hotword_worker, daemon=True)
        self.hotword_thread.start()
        self._async_append("Hotword listener started.")

    def _hotword_worker(self) -> None:
        if not self.hotword_stop_event:
            return
        try:
            detected = hotword_detector.listen_for_hotword(stop_event=self.hotword_stop_event)
            message = "Hotword detected!" if detected else "Hotword listener stopped."
        except Exception as exc:
            message = f"Hotword listener error: {exc}"
        self._async_append(message)
        self.hotword_thread = None
        self.hotword_stop_event = None

    def test_tts(self) -> None:
        def worker() -> None:
            try:
                if not self.tts_ready:
                    tts_engine.init_tts()
                    self.tts_ready = True
                tts_engine.speak("Wyzer Online")
                self._async_append("TTS playback finished.")
            except Exception as exc:
                self._async_append(f"TTS test failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def test_stt(self) -> None:
        def worker() -> None:
            try:
                transcript = stt_vosk.listen_once(timeout_seconds=3.0)
                spoken = transcript or "No speech captured."
                self._async_append(f"STT: {spoken}")
            except Exception as exc:
                self._async_append(f"STT test failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Feature discovery helpers
    # ------------------------------------------------------------------
    def _discover_feature_modules(self) -> List[str]:
        if not self.modules_dir.exists():
            return []
        modules: List[str] = []
        for path in self.modules_dir.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(self.modules_dir.parent)
            dotted = ".".join(rel.with_suffix("").parts)
            modules.append(dotted)
        return sorted(set(modules))


def launch() -> None:
    """Entry point used by python -m gui.wyzer_gui."""
    app = WyzerGUI()
    app.mainloop()


if __name__ == "__main__":
    launch()
