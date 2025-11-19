"""Modern chatbox GUI for the Wyzer Local AI Assistant."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tkinter as tk
from tkinter import messagebox, ttk

import config
try:  # Slack imports when running the GUI standalone.
    from assistant.orchestrator import Orchestrator
except Exception as exc:  # pragma: no cover - fallback for partial installs
    Orchestrator = None  # type: ignore[assignment]
    _ORCHESTRATOR_IMPORT_ERROR = exc
else:
    _ORCHESTRATOR_IMPORT_ERROR = None

try:
    from modules import commands_toolkit, hotword_detector, stt_vosk, tts_engine
except Exception:  # pragma: no cover - optional runtime dependencies
    commands_toolkit = None  # type: ignore[assignment]
    hotword_detector = None  # type: ignore[assignment]
    stt_vosk = None  # type: ignore[assignment]
    tts_engine = None  # type: ignore[assignment]

try:
    from utils.logger import log as logger
except Exception:  # pragma: no cover - logger should always exist but guard for safety
    def logger(message: str) -> None:  # type: ignore[override]
        print(message)


class WyzerChatGUI(tk.Tk):
    """Light-themed, ChatGPT-style interface that talks to the orchestrator."""

    BG_COLOR = "#f4f6fb"
    PANEL_COLOR = "#ffffff"
    CHAT_BG = "#f8fafc"
    USER_BUBBLE = "#dbe8ff"
    ASSISTANT_BUBBLE = "#eef1f7"
    TEXT_COLOR = "#1f2233"
    MUTED_TEXT = "#6c7286"
    BORDER_COLOR = "#d6dbe8"
    ACCENT_COLOR = "#2563eb"
    STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "gui_state.json"

    def __init__(self) -> None:
        if Orchestrator is None:  # pragma: no cover - defensive guard
            raise RuntimeError(f"Unable to import Orchestrator: {_ORCHESTRATOR_IMPORT_ERROR}")

        super().__init__()
        self.title("Wyzer Chat")
        self.geometry("960x640")
        self.minsize(820, 520)
        self.configure(bg=self.BG_COLOR)

        self.style = ttk.Style(self)
        self._configure_theme()

        self.orchestrator = Orchestrator()
        self._configure_orchestrator()
        self.conversation_state = self._init_conversation_state()

        self.tts_ready = False
        self._tts_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._follow_up_token = 0
        self._hotword_paused_for_follow_up = False
        self._gui_state = self._load_gui_state()

        self.hotword_thread: Optional[threading.Thread] = None
        self.hotword_stop_event: Optional[threading.Event] = None

        self.hotword_var = tk.BooleanVar(value=bool(self._gui_state.get("hotword_enabled", False)))
        self.tts_var = tk.BooleanVar(value=bool(self._gui_state.get("tts_enabled", False)))
        self.hotword_var.trace_add("write", lambda *_: self._persist_gui_state())
        self.tts_var.trace_add("write", lambda *_: self._persist_gui_state())
        self.commands_enabled = bool(getattr(config, "ENABLE_COMMANDS", False)) and commands_toolkit is not None
        self.merge_command_responses = bool(getattr(config, "MERGE_COMMAND_RESPONSES", False))

        self.create_widgets()
        self.layout_widgets()
        self._bind_events()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, lambda: self.add_message("assistant", "Ready when you are."))
        self.after(400, self._initialize_toggles_from_state)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def create_widgets(self) -> None:
        """Instantiate widgets without placing them yet."""

        self.chat_container = tk.Frame(self, bg=self.CHAT_BG, bd=0, highlightthickness=0)
        self.chat_canvas = tk.Canvas(
            self.chat_container,
            bg=self.CHAT_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.chat_scrollbar = ttk.Scrollbar(self.chat_container, orient=tk.VERTICAL, command=self.chat_canvas.yview)
        self.chat_frame = tk.Frame(self.chat_canvas, bg=self.CHAT_BG)
        self.chat_canvas_window = self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_canvas.configure(yscrollcommand=self.chat_scrollbar.set)

        self.control_bar = tk.Frame(self, bg=self.BG_COLOR)
        self.mic_button = ttk.Button(self.control_bar, text="Mic", command=self.capture_speech_once)
        self.hotword_toggle = ttk.Checkbutton(
            self.control_bar,
            text="Hotword",
            variable=self.hotword_var,
            command=self.toggle_hotword,
            style="Wyzer.TCheckbutton",
        )
        self.tts_toggle = ttk.Checkbutton(
            self.control_bar,
            text="TTS",
            variable=self.tts_var,
            command=self.toggle_tts,
            style="Wyzer.TCheckbutton",
        )
        self.clear_button = ttk.Button(self.control_bar, text="Clear", command=self.clear_chat)

        self.input_bar = tk.Frame(self, bg=self.BG_COLOR)
        self.input_text = tk.Text(
            self.input_bar,
            height=3,
            wrap="word",
            bg=self.PANEL_COLOR,
            fg=self.TEXT_COLOR,
            insertbackground=self.TEXT_COLOR,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.BORDER_COLOR,
            highlightcolor=self.BORDER_COLOR,
            font=("Segoe UI", 11),
        )
        self.send_button = ttk.Button(
            self.input_bar,
            text="Send",
            command=self.send_message,
            style="Accent.TButton",
        )

    def layout_widgets(self) -> None:
        """Arrange widgets using grid/pack layouts."""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.chat_container.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.control_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        for index, widget in enumerate(
            [self.mic_button, self.hotword_toggle, self.tts_toggle, self.clear_button]
        ):
            widget.grid(row=0, column=index, padx=(0, 8))
            self.control_bar.columnconfigure(index, weight=0)
        self.control_bar.columnconfigure(len(self.control_bar.winfo_children()), weight=1)

        self.input_bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.input_bar.columnconfigure(0, weight=1)
        self.input_text.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.send_button.grid(row=0, column=1)

    def _bind_events(self) -> None:
        """Attach widget event bindings."""

        self.chat_frame.bind("<Configure>", self._on_frame_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)
        self.input_text.bind("<Return>", self._on_enter_pressed)
        self.input_text.bind("<Shift-Return>", self._on_shift_enter)

    def _configure_theme(self) -> None:
        """Set up ttk theme overrides for the light UI."""

        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        button_bg = "#e5e9f5"
        button_active = "#d5dbef"
        self.style.configure(
            "TButton",
            background=button_bg,
            foreground=self.TEXT_COLOR,
            font=("Segoe UI", 10),
            padding=8,
            borderwidth=0,
        )
        self.style.map("TButton", background=[("active", button_active)])

        self.style.configure(
            "Accent.TButton",
            background=self.ACCENT_COLOR,
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=8,
        )
        self.style.map("Accent.TButton", background=[("active", "#1e4ed8")])

        self.style.configure(
            "Wyzer.TCheckbutton",
            background=self.BG_COLOR,
            foreground=self.TEXT_COLOR,
            font=("Segoe UI", 10),
        )
        self.style.map(
            "Wyzer.TCheckbutton",
            background=[("active", self.BG_COLOR)],
            foreground=[("disabled", "#a0a5b8")],
        )

    def _configure_orchestrator(self) -> None:
        """Mirror CLI initialization so tools manifest + prompts are loaded."""

        system_prompt = getattr(config, "SYSTEM_PREAMBLE", None)
        if hasattr(self.orchestrator, "set_system_prompt"):
            try:
                self.orchestrator.set_system_prompt(system_prompt)  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(self.orchestrator, "load_tools"):
            try:
                self.orchestrator.load_tools()  # type: ignore[attr-defined]
            except Exception as exc:
                self.after(0, lambda: self.add_message("assistant", f"Tool load failed: {exc}"))


        # Theme gets applied separately so we keep GUI + CLI setup concerns divided.

    # ------------------------------------------------------------------
    # State persistence helpers
    # ------------------------------------------------------------------
    def _initialize_toggles_from_state(self) -> None:
        """Restore hotword/TTS toggles after the UI has mounted."""

        if self.tts_var.get():
            self.toggle_tts()
        if self.hotword_var.get():
            self.toggle_hotword()

    def _load_gui_state(self) -> dict[str, Any]:
        """Fetch saved GUI preferences from disk if available."""

        try:
            with self.STATE_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as exc:  # pragma: no cover - best-effort
            logger(f"Failed to load GUI state: {exc}")
            return {}

    def _persist_gui_state(self) -> None:
        """Write the current toggle state to disk."""

        state = {
            "hotword_enabled": bool(self.hotword_var.get()),
            "tts_enabled": bool(self.tts_var.get()),
        }
        try:
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self.STATE_FILE.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
        except Exception as exc:  # pragma: no cover - best-effort log only
            logger(f"Failed to save GUI state: {exc}")

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------
    def add_message(self, role: str, text: str) -> None:
        """Render a message bubble in the scrollable chat area."""

        clean_text = text.strip() if text else ""
        if not clean_text:
            clean_text = "(empty message)"

        is_user = role.lower() == "user"
        bubble_color = self.USER_BUBBLE if is_user else self.ASSISTANT_BUBBLE
        anchor = "e" if is_user else "w"

        container = tk.Frame(self.chat_frame, bg=self.CHAT_BG)
        container.pack(fill=tk.X, padx=12, pady=4)
        bubble = tk.Frame(
            container,
            bg=bubble_color,
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=10,
        )
        padding = (60, 0) if is_user else (0, 60)
        bubble.pack(anchor=anchor, padx=padding)

        message_label = tk.Label(
            bubble,
            text=clean_text,
            wraplength=680,
            justify="left",
            bg=bubble_color,
            fg=self.TEXT_COLOR,
            font=("Segoe UI", 11),
        )
        message_label.pack(anchor=anchor)

        timestamp = tk.Label(
            bubble,
            text=datetime.now().strftime("%H:%M"),
            bg=bubble_color,
            fg=self.MUTED_TEXT,
            font=("Segoe UI", 9),
        )
        timestamp.pack(anchor=anchor, pady=(4, 0))

        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def clear_chat(self) -> None:
        """Remove all chat bubbles from the canvas."""

        for child in self.chat_frame.winfo_children():
            child.destroy()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def send_message(self) -> None:
        """Collect user input, show the bubble, and call the orchestrator."""

        user_text = self._get_input_text()
        if not user_text:
            return

        self.add_message("user", user_text)
        self._set_input_text("")
        threading.Thread(target=self._process_user_message, args=(user_text,), daemon=True).start()

    def _process_user_message(self, user_text: str) -> None:
        """Worker thread that talks to the orchestrator and posts replies."""

        with self._send_lock:
            try:
                reply, already_rendered = self._handle_user_turn(user_text)
            except Exception as exc:  # pragma: no cover - safety net
                self._post_message("assistant", f"Error: {exc}")
                return
        if not already_rendered:
            self._post_message("assistant", reply)
        follow_up_enabled = self._is_follow_up_enabled()
        if self.tts_var.get():
            self.speak_text(reply, trigger_follow_up=follow_up_enabled)
        elif follow_up_enabled:
            self._start_follow_up_window()

    def _handle_user_turn(self, user_text: str) -> tuple[str, bool]:
        """Process commands (if enabled) before handing off to the orchestrator."""

        command_feedback: Optional[str] = None
        if self.commands_enabled and commands_toolkit is not None and commands_toolkit.is_command(user_text):
            try:
                result = commands_toolkit.handle_command(user_text, logger)
            except Exception as exc:
                result = f"Command failed: {exc}"
            if self.merge_command_responses:
                command_feedback = result
            else:
                self._post_message("assistant", result)
                return result, True
        reply = self._call_orchestrator(user_text, command_feedback)
        return reply, False

    def _call_orchestrator(self, user_text: str, command_feedback: Optional[str] = None) -> str:
        """Support both chat() and route()-style orchestrators."""

        response: Any
        directive = self._build_command_directive(command_feedback) if command_feedback else None
        if hasattr(self.orchestrator, "route"):
            response = self.orchestrator.route(  # type: ignore[attr-defined]
                user_text,
                self.conversation_state,
                assistant_directive=directive,
            )
        elif hasattr(self.orchestrator, "chat"):
            response = self.orchestrator.chat(user_text)  # type: ignore[attr-defined]
        else:  # pragma: no cover - future-proofing
            raise AttributeError("Orchestrator lacks chat() or route() method")
        return self._extract_response_text(response)

    def _build_command_directive(self, feedback: str) -> str:
        """Match the CLI guidance when merging command responses."""

        if not feedback:
            return ""
        return (
            "A trusted local automation command already executed in response to the latest user request. "
            f"Command result: {feedback}. In your reply, briefly acknowledge the action and continue helping the "
            "user without mentioning any separate subsystems."
        )

    def _extract_response_text(self, response: Any) -> str:
        """Normalize the orchestrator response into a printable string."""

        if response is None:
            return "(no response)"
        if isinstance(response, str):
            return response.strip() or "(no response)"
        if isinstance(response, dict):
            for key in ("content", "text", "message"):
                value = response.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return str(response)

    def _init_conversation_state(self) -> list[Any]:
        """Use reset_conversation() when available to seed the chat."""

        if hasattr(self.orchestrator, "reset_conversation"):
            try:
                return list(self.orchestrator.reset_conversation())  # type: ignore[call-arg]
            except Exception:
                return []
        return []

    # ------------------------------------------------------------------
    # Hotword + STT + TTS integrations
    # ------------------------------------------------------------------
    def toggle_hotword(self) -> None:
        """Start or stop the hotword listener thread."""

        if not self.hotword_var.get():
            self.stop_hotword_listener()
            return
        if not getattr(config, "USE_STT", False):
            messagebox.showwarning("Hotword", "Speech-to-text is disabled in config.")
            self.hotword_var.set(False)
            return
        if not self._start_hotword_listener():
            self.hotword_var.set(False)

    def _start_hotword_listener(self, announce: bool = True) -> bool:
        """Spin up the background hotword listener if possible."""

        if hotword_detector is None:
            messagebox.showwarning("Hotword", "Hotword detector module is unavailable.")
            return False
        if self.hotword_thread and self.hotword_thread.is_alive():
            return True
        self.hotword_stop_event = threading.Event()
        self.hotword_thread = threading.Thread(target=self._hotword_worker, daemon=True)
        self.hotword_thread.start()
        if announce:
            self.add_message("assistant", "Hotword listener enabled.")
        return True

    def stop_hotword_listener(self, announce: bool = True) -> None:
        """Signal the background hotword listener to exit."""

        if self.hotword_stop_event:
            self.hotword_stop_event.set()
        self.hotword_thread = None
        self.hotword_stop_event = None
        if announce:
            self.add_message("assistant", "Hotword listener disabled.")

    def _hotword_worker(self) -> None:
        """Block until the hotword fires or the user stops listening."""

        stop_event = self.hotword_stop_event
        assert stop_event is not None
        while not stop_event.is_set():
            try:
                detected = hotword_detector.listen_for_hotword(stop_event=stop_event)
            except Exception as exc:  # pragma: no cover - hardware specific
                self._post_message("assistant", f"Hotword error: {exc}")
                break
            if detected:
                self._on_hotword_detected()
                self.capture_speech_once(auto_send=True)
            else:
                continue
        should_disable = not self._hotword_paused_for_follow_up
        if should_disable:
            self.after(0, lambda: self.hotword_var.set(False))
        self.stop_hotword_listener(announce=should_disable)

    def capture_speech_once(self, auto_send: bool = False) -> None:
        """Trigger a one-shot STT capture and drop transcript into the input box."""

        if stt_vosk is None:
            messagebox.showwarning("STT", "Speech-to-text module is unavailable.")
            return

        def worker() -> None:
            self._post_message("assistant", "Listening...")
            try:
                transcript = stt_vosk.listen_once(timeout_seconds=10.0)
            except Exception as exc:  # pragma: no cover - hardware specific
                self._post_message("assistant", f"STT error: {exc}")
                return
            if not transcript:
                self._post_message("assistant", "Did not catch that.")
                return
            self._post_message("assistant", f"Heard: {transcript}")
            self.after(0, lambda: self._handle_captured_text(transcript, auto_send))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_captured_text(self, transcript: str, auto_send: bool) -> None:
        """Populate the input widget and optionally send immediately."""

        self._set_input_text(transcript)
        if auto_send:
            self.send_message()

    def toggle_tts(self) -> None:
        """Lazy-init TTS when enabling the toggle."""

        if not self.tts_var.get():
            return
        if tts_engine is None:
            messagebox.showwarning("TTS", "Text-to-speech module is unavailable.")
            self.tts_var.set(False)
            return
        with self._tts_lock:
            if self.tts_ready:
                return
            try:
                tts_engine.init_tts()
                self.tts_ready = True
            except Exception as exc:
                self.tts_var.set(False)
                messagebox.showerror("TTS", f"Unable to initialize TTS: {exc}")

    def speak_text(self, text: str, *, trigger_follow_up: bool = False) -> None:
        """Speak assistant replies asynchronously when TTS is enabled."""

        if not self.tts_var.get() or not text:
            return
        if tts_engine is None or not self.tts_ready:
            return

        def worker() -> None:
            try:
                tts_engine.speak(text)
            except Exception as exc:  # pragma: no cover - optional dependency
                self._post_message("assistant", f"TTS failed: {exc}")
            finally:
                if trigger_follow_up:
                    self.after(0, self._start_follow_up_window)

        threading.Thread(target=worker, daemon=True).start()

    def _is_follow_up_enabled(self) -> bool:
        if stt_vosk is None or not getattr(config, "USE_STT", False):
            return False
        window = float(getattr(config, "FOLLOW_UP_WINDOW_SECONDS", 0.0) or 0.0)
        return window > 0

    def _start_follow_up_window(self) -> None:
        """Open the brief no-hotword follow-up window after a reply."""

        if not self._is_follow_up_enabled():
            return
        window = float(getattr(config, "FOLLOW_UP_WINDOW_SECONDS", 0.0) or 0.0)
        listen_budget = float(getattr(config, "MAX_LISTEN_SECONDS", 10.0) or 10.0)
        resume_hotword = bool(
            self.hotword_var.get() and self.hotword_thread and self.hotword_thread.is_alive()
        )
        if resume_hotword:
            self._hotword_paused_for_follow_up = True
            self.stop_hotword_listener(announce=False)

        self._follow_up_token += 1
        token = self._follow_up_token

        def worker() -> None:
            try:
                transcript = stt_vosk.listen_follow_up(window, listen_budget)
            except Exception as exc:  # pragma: no cover - hardware/hotword specific
                self._post_message("assistant", f"Follow-up listener error: {exc}")
                transcript = ""
            finally:
                if resume_hotword:
                    try:
                        if self.hotword_var.get():
                            self._start_hotword_listener(announce=False)
                    finally:
                        self._hotword_paused_for_follow_up = False

            if token != self._follow_up_token:
                return

            cleaned = transcript.strip()
            if cleaned:
                self._post_message("assistant", f"Heard: {cleaned}")
                self.after(0, lambda: self._handle_captured_text(cleaned, auto_send=True))

        threading.Thread(target=worker, daemon=True).start()

    def _on_hotword_detected(self) -> None:
        """Provide audible + visual feedback when the wake word fires."""

        self._post_message("assistant", "Hotword detected. I'm here - go ahead.")
        if self.tts_var.get():
            self.speak_text("I'm here.", trigger_follow_up=False)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _get_input_text(self) -> str:
        return self.input_text.get("1.0", tk.END).strip()

    def _set_input_text(self, value: str) -> None:
        self.input_text.delete("1.0", tk.END)
        if value:
            self.input_text.insert(tk.END, value)

    def _on_enter_pressed(self, event: tk.Event) -> str:
        self.send_message()
        return "break"

    def _on_shift_enter(self, _event: tk.Event) -> str:
        self.input_text.insert(tk.INSERT, "\n")
        return "break"

    def _on_frame_configure(self, _event: tk.Event) -> None:
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.chat_canvas.itemconfig(self.chat_canvas_window, width=event.width)

    def _post_message(self, role: str, text: str) -> None:
        self.after(0, lambda: self.add_message(role, text))

    def on_close(self) -> None:
        """Ensure background threads exit cleanly before quitting."""

        if self.hotword_stop_event:
            self.hotword_stop_event.set()
        self.destroy()


if __name__ == "__main__":
    app = WyzerChatGUI()
    app.mainloop()
