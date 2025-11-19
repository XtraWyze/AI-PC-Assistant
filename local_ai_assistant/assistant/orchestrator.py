"""Central orchestration layer for routing between the LLM and local tools."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import config
from modules import llm_engine, voice_typing
from modules.tools.open_file_location import run_tool as open_file_location
from modules.tools.open_path import run_tool as open_path
from modules.tools.open_website import open_website
from utils.logger import log

ToolCallable = Callable[..., Any]
Message = Dict[str, Any]
ToolSchema = Dict[str, Any]

STATIC_TOOL_BINDINGS: Dict[str, ToolCallable] = {
    "open_website": open_website,
    "open_path": open_path,
    "open_file_location": open_file_location,
}

WEATHER_COORDINATE_TOOLS = {
    "get_weather",
    "get_sunrise_sunset",
    "get_forecast",
    "get_air_quality",
    "get_environment_overview",
}


class Orchestrator:
    """Coordinates LLM calls, tool execution, and conversation state."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        tools_manifest_path: Optional[str] = None,
        llm_client: Any = None,
    ) -> None:
        self.model_name = model_name or getattr(config, "LLM_MODEL", "llama3")
        self.ollama_base_url = (ollama_base_url or getattr(config, "OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        base_dir = Path(__file__).resolve().parent.parent
        default_manifest = base_dir / "tools" / "tools_manifest.json"
        manifest_path = Path(tools_manifest_path).expanduser() if tools_manifest_path else default_manifest
        self.tools_manifest_path = manifest_path if manifest_path.is_absolute() else (base_dir / manifest_path)
        self.llm_client = llm_client or llm_engine
        self.enable_tools = bool(getattr(config, "ENABLE_LLM_TOOLS", True))
        self.tools_registry: Dict[str, Dict[str, Any]] = {}
        self._tool_schemas: List[ToolSchema] = []
        self.system_prompt: Optional[str] = None

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------
    def load_tools(self) -> None:
        """Load tool metadata + callables from the manifest file."""
        self.tools_registry.clear()
        self._tool_schemas.clear()

        if not self.enable_tools:
            log("LLM tool-calling disabled via config.ENABLE_LLM_TOOLS=False.")
            return

        try:
            manifest_data = json.loads(self.tools_manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log(f"Tool manifest not found at {self.tools_manifest_path}.")
            return
        except json.JSONDecodeError as exc:
            log(f"Tool manifest is invalid JSON: {exc}.")
            return

        if not isinstance(manifest_data, list):
            log("Tool manifest must be a list of tool definitions.")
            return

        for entry in manifest_data:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            module_path = entry.get("module")
            function_name = entry.get("function")
            description = entry.get("description", "")
            parameters = entry.get("parameters") or {"type": "object", "properties": {}}
            if not (name and module_path and function_name):
                log(f"Skipping malformed tool entry: {entry}")
                continue
            manual_binding = STATIC_TOOL_BINDINGS.get(name)
            if manual_binding:
                func = manual_binding
            else:
                try:
                    module = importlib.import_module(module_path)
                    func = getattr(module, function_name)
                except (ImportError, AttributeError) as exc:
                    log(f"Unable to import tool '{name}' ({module_path}.{function_name}): {exc}")
                    continue

            self.tools_registry[name] = {
                "callable": func,
                "schema": parameters,
                "description": description,
            }
            self._tool_schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )

        log(f"Loaded {len(self.tools_registry)} tool(s) from manifest.")

    def get_tool_schemas(self) -> List[ToolSchema]:
        """Return tool descriptors formatted for Ollama's tool-calling API."""
        if not self.enable_tools:
            return []
        return list(self._tool_schemas)

    def _tool_payload(self) -> Optional[List[ToolSchema]]:
        """Return tools list or None depending on feature flag and availability."""
        schemas = self.get_tool_schemas()
        return schemas or None

    def _handle_voice_typing_intent(self, cleaned: str) -> Optional[Message]:
        """Intercept simple voice-typing toggle intents before hitting the LLM."""
        if not getattr(config, "ENABLE_VOICE_TYPING", False):
            return None

        normalized = cleaned.strip().lower()
        if not normalized:
            return None

        enable_phrases = {
            "enable voice typing",
            "start typing mode",
            "start typing",
            "start dictation",
        }
        disable_phrases = {
            "disable voice typing",
            "stop typing mode",
            "stop typing",
            "cancel dictation",
        }

        if normalized in enable_phrases:
            success = voice_typing.enable_voice_typing()
            message = "Voice typing enabled." if success else "Voice typing is unavailable right now."
            return {"role": "assistant", "content": message}

        if normalized in disable_phrases:
            changed = voice_typing.disable_voice_typing()
            message = "Voice typing disabled." if changed else "Voice typing was already off."
            return {"role": "assistant", "content": message}

        return None

    # ------------------------------------------------------------------
    # LLM + routing
    # ------------------------------------------------------------------
    def call_llm(self, messages: List[Message], tools: Optional[List[ToolSchema]] = None) -> Dict[str, Any]:
        """Proxy a chat completion request through the configured LLM client."""
        if not messages:
            raise ValueError("At least one message is required for call_llm().")
        payload_tools = tools or None
        return self.llm_client.chat(  # type: ignore[no-untyped-call]
            messages=messages,
            tools=payload_tools,
            model=self.model_name,
            base_url=self.ollama_base_url,
            stream=False,
        )

    def run_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Safely execute a registered tool and return a structured payload."""
        record = self.tools_registry.get(tool_name)
        if not record:
            return {"status": "error", "error": f"Unknown tool '{tool_name}'."}
        func: ToolCallable = record["callable"]
        payload = dict(arguments or {})
        if tool_name in WEATHER_COORDINATE_TOOLS:
            payload = self._ensure_weather_coordinates(payload)
        try:
            result = func(**payload)
            return {"status": "success", "result": result}
        except Exception as exc:  # pragma: no cover - tool safety net
            log(f"Tool '{tool_name}' failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def _ensure_weather_coordinates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-fetch coordinates when the LLM omits them for environment tools."""
        def _is_missing(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str) and not value.strip():
                return True
            return False

        lat_missing = _is_missing(arguments.get("lat"))
        lon_missing = _is_missing(arguments.get("lon"))
        if not (lat_missing or lon_missing):
            return arguments

        location = self._call_location_tool_internal()
        if not location:
            return arguments

        if lat_missing and location.get("lat") is not None:
            arguments["lat"] = location.get("lat")
        if lon_missing and location.get("lon") is not None:
            arguments["lon"] = location.get("lon")
        return arguments

    def _call_location_tool_internal(self) -> Optional[Dict[str, Any]]:
        """Invoke the get_location tool without surfacing a visible tool call."""
        record = self.tools_registry.get("get_location")
        if not record:
            log("get_weather requested coordinates but get_location is unavailable.")
            return None
        func: ToolCallable = record["callable"]
        try:
            result = func()
        except Exception as exc:  # pragma: no cover - tool safety net
            log(f"Internal get_location call failed: {exc}")
            return None
        if isinstance(result, dict):
            return result
        log("get_location returned a non-dict payload; ignoring result.")
        return None

    def route(
        self,
        user_message: str,
        conversation_state: List[Message],
        assistant_directive: Optional[str] = None,
    ) -> Message:
        """Entry point used by the assistant loop to process a user turn."""
        cleaned = (user_message or "").strip()
        if not cleaned:
            raise ValueError("route() requires non-empty user input.")

        conversation_state.append({"role": "user", "content": cleaned})
        intercepted = self._handle_voice_typing_intent(cleaned)
        if intercepted:
            conversation_state.append(intercepted)
            return intercepted
        response = self._invoke_llm_with_directive(conversation_state, assistant_directive)
        message = self._handle_llm_response(response, conversation_state, assistant_directive)
        conversation_state.append(message)
        return message

    def stream_route(
        self,
        user_message: str,
        conversation_state: List[Message],
        assistant_directive: Optional[str] = None,
        *,
        on_text_chunk: Optional[Callable[[str], Optional[bool]]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[Message, bool]:
        """Process a user turn while streaming assistant text chunks."""
        cleaned = (user_message or "").strip()
        if not cleaned:
            raise ValueError("stream_route() requires non-empty user input.")

        conversation_state.append({"role": "user", "content": cleaned})
        intercepted = self._handle_voice_typing_intent(cleaned)
        if intercepted:
            conversation_state.append(intercepted)
            return intercepted, False
        response = self._invoke_llm_streaming(
            conversation_state,
            assistant_directive,
            on_text_chunk,
            should_stop,
        )
        message, follow_up = self._handle_llm_response(
            response,
            conversation_state,
            assistant_directive,
            return_follow_up_flag=True,
        )
        conversation_state.append(message)
        return message, follow_up

    # ------------------------------------------------------------------
    # Conversation helpers
    # ------------------------------------------------------------------
    def set_system_prompt(self, prompt: Optional[str]) -> None:
        """Remember a default system prompt for freshly reset conversations."""
        self.system_prompt = prompt.strip() if prompt else None

    def reset_conversation(self) -> List[Message]:
        """Return a new conversation list seeded with the saved system prompt."""
        base: List[Message] = []
        if self.system_prompt:
            base.append({"role": "system", "content": self.system_prompt})
        return base

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _invoke_llm_with_directive(
        self,
        conversation_state: List[Message],
        assistant_directive: Optional[str],
    ) -> Dict[str, Any]:
        working_messages = list(conversation_state)
        if assistant_directive:
            working_messages.append({"role": "system", "content": assistant_directive})

        try:
            return self.call_llm(working_messages, tools=self._tool_payload())
        except Exception as exc:
            error_msg = (
                "LLM backend unavailable. Ensure Ollama is running and reachable. "
                f"Details: {exc}"
            )
            log(error_msg)
            return {
                "message": {
                    "role": "assistant",
                    "content": error_msg,
                }
            }

    def _invoke_llm_streaming(
        self,
        conversation_state: List[Message],
        assistant_directive: Optional[str],
        on_text_chunk: Optional[Callable[[str], Optional[bool]]],
        should_stop: Optional[Callable[[], bool]],
    ) -> Dict[str, Any]:
        working_messages = list(conversation_state)
        if assistant_directive:
            working_messages.append({"role": "system", "content": assistant_directive})

        aggregated: List[str] = []
        latest_response: Optional[Dict[str, Any]] = None
        saw_chunk = False
        stream = self.llm_client.chat_stream(  # type: ignore[no-untyped-call]
            messages=working_messages,
            tools=self._tool_payload(),
            model=self.model_name,
            base_url=self.ollama_base_url,
        )

        try:
            for packet in stream:
                latest_response = packet
                if packet.get("error"):
                    log(packet["error"])
                    break

                chunk = self._extract_stream_chunk(packet)
                if chunk:
                    saw_chunk = True
                    aggregated.append(chunk)
                    if on_text_chunk:
                        continue_stream = on_text_chunk(chunk)
                        if continue_stream is False:
                            break

                if should_stop and should_stop():
                    break

                if packet.get("done"):
                    break
        finally:
            try:
                stream.close()  # type: ignore[attr-defined]
            except Exception:
                pass

        combined = "".join(aggregated).strip()
        if not combined and not saw_chunk:
            return self._invoke_llm_with_directive(conversation_state, assistant_directive)

        base_response = latest_response or {
            "message": {
                "role": "assistant",
                "content": combined,
            }
        }
        normalized = self._extract_message(base_response)
        if combined:
            normalized["content"] = combined
        return {"message": normalized}

    @staticmethod
    def _extract_stream_chunk(packet: Dict[str, Any]) -> str:
        message_block = packet.get("message")
        if isinstance(message_block, dict):
            content = message_block.get("content")
            normalized = Orchestrator._normalize_content(content)
            if normalized:
                return normalized
        delta_block = packet.get("delta")
        if isinstance(delta_block, dict):
            content = delta_block.get("content")
            normalized = Orchestrator._normalize_content(content)
            if normalized:
                return normalized
        response_field = packet.get("response")
        if response_field:
            normalized = Orchestrator._normalize_content(response_field)
            if normalized:
                return normalized
        return ""

    def _handle_llm_response(
        self,
        response: Dict[str, Any],
        conversation_state: List[Message],
        assistant_directive: Optional[str],
        *,
        return_follow_up_flag: bool = False,
    ) -> Union[Message, Tuple[Message, bool]]:
        message = self._extract_message(response)
        tool_calls = self._extract_tool_calls(message)
        if not tool_calls:
            if return_follow_up_flag:
                return message, False
            return message

        for call in tool_calls:
            name = call.get("name")
            arguments = call.get("arguments", {})
            result = self.run_tool(name or "", arguments)
            conversation_state.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        follow_up = self._invoke_llm_with_directive(conversation_state, assistant_directive)
        final_message = self._extract_message(follow_up)
        if return_follow_up_flag:
            return final_message, True
        return final_message

    @staticmethod
    def _extract_message(response: Dict[str, Any]) -> Message:
        message = response.get("message")
        if isinstance(message, dict):
            normalized = {
                "role": message.get("role", "assistant"),
                "content": Orchestrator._normalize_content(message.get("content")),
            }
            if message.get("tool_calls"):
                normalized["tool_calls"] = message.get("tool_calls")
            return normalized
        # Fallback to minimal error message
        return {
            "role": "assistant",
            "content": "(No response from model.)",
        }

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: List[str] = []
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    value = chunk.get("text")
                    if value:
                        pieces.append(str(value))
                elif isinstance(chunk, str):
                    pieces.append(chunk)
            return "\n".join(pieces)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _extract_tool_calls(message: Message) -> List[Dict[str, Any]]:
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            parsed: List[Dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function_block = call.get("function", {})
                name = function_block.get("name")
                arguments = Orchestrator._decode_arguments(function_block.get("arguments"))
                parsed.append({"name": name, "arguments": arguments})
            return parsed
        return []

    @staticmethod
    def _decode_arguments(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            if not payload.strip():
                return {}
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {"_raw": payload}
        return {}
