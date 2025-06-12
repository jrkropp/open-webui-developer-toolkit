"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
funding_url: https://github.com/jrkropp/open-webui-developer-toolkit
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
required_open_webui_version: 0.6.3
version: 0.8.6
license: MIT
requirements: orjson
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 1. Imports
# ─────────────────────────────────────────────────────────────────────────────
# Standard library, third-party, and Open WebUI imports
# Standard library imports
import asyncio
import datetime
import inspect
from io import StringIO
import json
import logging
import os
import re
import sys
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Literal, Optional, Union

# Third-party imports
import aiohttp
import orjson
from fastapi import Request
from pydantic import BaseModel, Field, model_validator

# Open WebUI internals
from open_webui.models.chats import Chats, ChatModel
from open_webui.models.models import ModelForm, Models
from open_webui.utils.misc import get_message_list, get_system_message

# ─────────────────────────────────────────────────────────────────────────────
# 2. Constants & Global Configuration
# ─────────────────────────────────────────────────────────────────────────────
# Feature flags and other module level constants
FEATURE_SUPPORT = {
    "web_search_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"}, # OpenAI's built-in web search tool.
    "image_gen_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o3-pro"}, # OpenAI's built-in image generation tool.
    "function_calling": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o4-mini", "o3-mini", "o3-pro"}, # OpenAI's native function calling support.
    "reasoning": {"o3", "o4-mini", "o3-mini","o3-pro"}, # OpenAI's reasoning models.
    "reasoning_summary": {"o3", "o4-mini", "o4-mini-high", "o3-mini", "o3-mini-high", "o3-pro"}, # OpenAI's reasoning summary feature.  May require OpenAI org verification before use.
}

# Invisible zero-width characters used for encoding item identifiers
ZERO, ONE = "\u200b", "\u200c"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Data Models
# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models for validating request and response payloads
class CompletionsBody(BaseModel):
    """
    Represents the body of a completions request to OpenAI completions API.
    """
    model: str
    stream: bool = False
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict[str, Any]]] = None                            # tools to use for function calling
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None     # reasoning effort for o-series models
    parallel_tool_calls: Optional[bool] = None                              # allow parallel tool execution
    user: Optional[str] = None                                              # user ID for the request.  Recommended to improve caching hits.
    seed: Optional[int] = None                                              # deterministic sampling
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None

    class Config:
        extra = "allow"

    @model_validator(mode='after')
    def normalize_model(cls, values: "CompletionsBody") -> "CompletionsBody":
        """Sanitize the ``model`` field after validation.

        The helper removes the ``openai_responses.`` prefix and converts
        pseudo-model IDs (e.g. ``o4-mini-high``) into their base model while
        recording the requested reasoning effort.
        """
        # Strip prefix if present
        values.model = values.model.removeprefix("openai_responses.")

        # Handle pseudo-models (e.g., o4-mini-high → o4-mini, effort=high)
        if values.model in {"o3-mini-high", "o4-mini-high"}:
            values.model = values.model.replace("-high", "")
            values.reasoning_effort = "high"

        return values

class ResponsesBody(BaseModel):
    """
    Represents the body of a responses request to OpenAI Responses API.
    """
    # Required parameters
    model: str
    input: Union[str, List[Dict[str, Any]]] # plain text, or rich array

    # Optional parameters
    instructions: Optional[str] = ""              # system / developer prompt
    stream: bool = False                          # SSE chunking
    store: Optional[bool] = False                  # persist response on OpenAI side
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_output_tokens: Optional[int] = None
    truncation: Optional[Literal["auto", "disabled"]] = None
    reasoning: Optional[Dict[str, Any]] = None    # {"effort":"high", ...}
    parallel_tool_calls: Optional[bool] = True
    user: Optional[str] = None                # user ID for the request.  Recommended to improve caching hits.
    tool_choice: Optional[Literal["none", "auto", "required"]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    include: Optional[List[str]] = None           # extra output keys

    class Config:
        extra = "allow"

    @staticmethod
    def transform_tools(
        tools: list[dict] | dict[str, Any],
        strict: bool = False,
    ) -> list[dict]:
        """
        Normalize tool definitions from Open WebUI (`__tools__`) or OpenAI Completions API (`body["tools"]` when native mode is enabled) formats into the OpenAI Responses API schema.

        Parameters
        ----------
        tools : dict[str, Any] | list[dict]
            Tool definitions in either:
            - **Internal dict format**(`__tools__`): `{tool_name: {"spec": {...}, ...}}`
            - **Completions API format** (`body["tools"]`): `[{"type": "function", "function": {...}}, ...]`

        strict : bool, default=False
            If `True`, applies OpenAI strict schema enforcement:
            - Sets `additionalProperties=False`
            - Marks all fields as required
            - Allows `"null"` explicitly for optional fields

        Returns
        -------
        list[dict]
            Tools formatted per OpenAI Responses API.
        """
        if not tools:
            return []

        def normalize_tool(tool: dict) -> dict:
            if "function" in tool:
                flattened = {"type": "function"}
                flattened.update(tool["function"])
                return flattened
            if "spec" in tool:
                spec = tool["spec"] or {}
                return {
                    "type": "function",
                    "name": spec.get("name", ""),
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters", {}),
                }
            return tool

        def apply_strict(schema: dict) -> dict:
            params = schema.get("parameters", {})
            properties = params.get("properties", {})
            required_fields = set(params.get("required", []))

            for prop, definition in properties.items():
                if prop not in required_fields:
                    f_type = definition.get("type")
                    if isinstance(f_type, list):
                        if "null" not in f_type:
                            definition["type"].append("null")
                    elif f_type is not None:
                        definition["type"] = [f_type, "null"]

            params["required"] = list(properties.keys())
            params["additionalProperties"] = False
            schema["parameters"] = params
            schema["strict"] = True
            return schema

        tools_iter = tools.values() if isinstance(tools, dict) else tools
        result = [normalize_tool(t) for t in tools_iter]

        if strict:
            result = [apply_strict(t) for t in result]

        return result

    @staticmethod
    def transform_messages(
        completions_messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Translate completion-style messages into Responses input.

        System messages are omitted because the ``instructions`` field carries
        that information.  Each remaining message is wrapped in the structure
        expected by the Responses API.
        """
        responses_input = []
        for msg in completions_messages:
            role = msg.get("role", "assistant")
            if role == "system":
                continue  # Skip system messages since they're in instructions
            responses_input.append({
                "type": "message",
                "role": role,
                "content": [
                    # Add text content as input_text (if user) or output_text (if assistant)
                    *([{
                        "type": "input_text" if role == "user" else "output_text",
                        "text": msg.get("content", "")
                    }] if msg.get("content", "") else []),
                    # Add each image as its own entry
                    *([{
                        "type": "input_image" if role == "user" else "output_image",
                        "image_url": file["url"] # Url or base64 encoded image data
                    } for file in msg.get("files", []) if file.get("type") == "image" and file.get("url")])
                ],
            })
        return responses_input

    @staticmethod
    def from_completions(
        completions: "CompletionsBody",
        **extras: Any
    ) -> "ResponsesBody":
        """Create a :class:`ResponsesBody` from a :class:`CompletionsBody`.

        Parameters that share the same meaning are copied directly while any
        additional keyword arguments are forwarded verbatim.  The helper also
        extracts the system prompt, flattens tools and converts the message
        history to the format required by the Responses API.
        """
        system_message = get_system_message(completions.messages)

        return ResponsesBody(
            model=completions.model,
            stream=completions.stream,
            temperature=completions.temperature,
            top_p=completions.top_p,
            instructions=system_message.get("content", "") if system_message else "",
            input=ResponsesBody.transform_messages(completions.messages),
            **({"tools": ResponsesBody.transform_tools(completions.tools)} if completions.tools else {}),
            **({"user":  completions.user} if getattr(completions, "user", None) else {}),
            **({"reasoning": {"effort": completions.reasoning_effort}} if completions.reasoning_effort else {}),
            **{k: v for k, v in extras.items() if v is not None}
        )

# ─────────────────────────────────────────────────────────────────────────────
# 4. Main Controller: Pipe
# ─────────────────────────────────────────────────────────────────────────────
# Primary interface implementing the Responses manifold
class Pipe:
    # 4.1 Configuration Schemas
    class Valves(BaseModel):
        BASE_URL: str = Field(
            default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )
        API_KEY: str = Field(
            default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )
        MODEL_ID: str = Field(
            default="gpt-4.1, gpt-4o",
            description="Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. Supports the pseudo models 'o3-mini-high' and 'o4-mini-high', which map to 'o3-mini' and 'o4-mini' with reasoning effort forced to high.",
        )
        ENABLE_REASONING_SUMMARY: Literal["auto", "concise", "detailed", None] = Field(
            default=None,
            description="Reasoning summary style for o-series models (supported by: o3, o4-mini). Ignored for others. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
        )
        ENABLE_WEB_SEARCH: bool = Field(
            default=False,
            description="Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini).  Note this adds the tool to each call which may slow down responses. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
        )
        SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH=True.",
        )
        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
        )
        TRUNCATION: Literal["auto", "disabled"] = Field(
            default="auto",
            description="Truncation strategy for model responses. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
        )
        MAX_TOOL_CALL_LOOPS: int = Field(
            default=5,
            description="Maximum number of tool calls the model can make in a single request. This is a hard stop safety limit to prevent infinite loops. Defaults to 5.",
        )
        PERSIST_TOOL_RESULTS: bool = Field(
            default=True,
            description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
        )
        ANONYMIZE_USER_ID: bool = Field(
            default=True,
            description="Use anonymous user identifiers (UUID) instead of user email addresses in OpenAI API requests. Passing consistent user identifiers improves cache efficiency. Enabled by default for enhanced privacy.",
        ),
        LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
            default=os.getenv("GLOBAL_LOG_LEVEL", "INFO").upper(),
            description="Select logging level.  Recommend INFO or WARNING for production use. DEBUG is useful for development and debugging.",
        )
    
    class UserValves(BaseModel):
        """Per-user valve overrides."""
        LOG_LEVEL: Literal[
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"
        ] = Field(
            default="INHERIT",
            description="Select logging level. 'INHERIT' uses the pipe default.",
        )

    # 4.2 Constructor and Entry Points
    def __init__(self):
        self.type = "manifold"
        self.id = "openai_responses" # Unique ID for this manifold
        self.valves = self.Valves()  # Note: valve values are not accessible in __init__. Access from pipes() or pipe() methods.
        self.session: aiohttp.ClientSession | None = None
        self.logger = SessionLogger.get_logger(__name__)

    async def pipes(self):
        model_ids = [model_id.strip() for model_id in self.valves.MODEL_ID.split(",") if model_id.strip()]
        return [{"id": model_id, "name": f"OpenAI: {model_id}"} for model_id in model_ids]

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: Optional[dict[str, Any]] = None,
        __task_body__: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None] | str | None:
        """Process a user request and return either a stream or final text.

        When ``body['stream']`` is ``True`` the method yields deltas from
        ``_multi_turn_streaming``.  Otherwise it falls back to
        ``_multi_turn_non_streaming`` and returns the aggregated response.
        """
        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        full_model_id = __metadata__.get("model", {}).get("id", "") # Full model ID, e.g. "openai_responses.gpt-4o"
        user_identifier = __user__["id"] if valves.ANONYMIZE_USER_ID else __user__["email"] # User identifier for OpenAI API requests (required for cache routing). Defaults to user ID, or email if anonymization is disabled.  

        # Set up session logger with session_id and log level
        SessionLogger.session_id.set(__metadata__.get("session_id", None))
        SessionLogger.log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        # Transform request body (Completions API -> Responses API). Populates with default values.
        completions_body = CompletionsBody.model_validate(body)
        responses_body = ResponsesBody.from_completions(
            completions_body,
            truncation=valves.TRUNCATION,
            user=user_identifier,
        )  # supports passing custom params (e.g., truncation) which are injected into ResponsesBody

        # Detect if task model (generate title, generate tags, etc.), handle it separately
        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self._handle_task(responses_body.model_dump(), valves) # Placeholder for task handling logic
        
        # Log instructions
        # self.logger.info("Instructions: %s", responses_body.instructions)

        # Override input, if chat_id and message_id are provided.
        # Uses specialized helper which rebuilds input history and injects previously persisted OpenAI responses output items (e.g. function_call, encrypted reasoning tokens, etc.) into the input history.
        if __metadata__.get("chat_id") and __metadata__.get("message_id"):
            responses_body.input = build_responses_history_by_chat_id_and_message_id(
                __metadata__.get("chat_id"),
                __metadata__.get("message_id"),
                model_id=full_model_id,
            )
            # self.logger.debug("Built input history for ResponsesBody: %s", json.dumps(responses_body.input, indent=2, ensure_ascii=False))

        # Override tools, if __tools__ provided
        if __tools__:
            responses_body.tools = ResponsesBody.transform_tools(__tools__, strict=True) # __tools__ is always provided if one or more tools are enabled in the UI (unlike body["tools"] which is only present when function calling is enabled)
            # self.logger.debug("Transformed tools: %s", json.dumps(responses_body.tools, indent=2, ensure_ascii=False))

        # Add web_search tool, if supported and enabled
        if responses_body.model in FEATURE_SUPPORT["web_search_tool"] and valves.ENABLE_WEB_SEARCH:
            responses_body.tools = responses_body.tools or []
            responses_body.tools.append({
                "type": "web_search",
                "search_context_size": valves.SEARCH_CONTEXT_SIZE,
            })

        # If Open WebUI native function calling is disabled, update model metadata if supported
        if __tools__ and __metadata__.get("function_calling", None) != "native":
            if responses_body.model in FEATURE_SUPPORT["function_calling"]:
                # Model supports function calling, enable it
                await self._emit_notification(__event_emitter__, content=f"Enabling native function calling for model: {responses_body.model}. Please re-run your query.", level="info")
                patch_model_param_field(full_model_id, "function_calling", "native")
            elif responses_body.model not in FEATURE_SUPPORT["function_calling"]:
                # Model does not support function calling, warn the user and exit early
                await self._emit_error(
                    __event_emitter__,
                    f"Tools are not supported by the selected model: {responses_body.model}. "
                    f"Please disable tools or choose a model that supports tool use (e.g. {', '.join(FEATURE_SUPPORT['function_calling'])}).",
                )
                return  # Exit early if function calling is not supported
            
        # Enable reasoning summary, if supported and enabled
        if responses_body.model in FEATURE_SUPPORT["reasoning_summary"] and valves.ENABLE_REASONING_SUMMARY:
            responses_body.reasoning = responses_body.reasoning or {}
            responses_body.reasoning["summary"] = valves.ENABLE_REASONING_SUMMARY

        # Enable persistence of encrypted reasoning tokens, if supported and store=False
        # TODO make this configurable via valves since some orgs might not be approved for encrypted content
        # Note storing encrypted contents is only supported when store = False
        if responses_body.model in FEATURE_SUPPORT["reasoning"] and responses_body.store is False:
            responses_body.include = responses_body.include or []
            responses_body.include.append("reasoning.encrypted_content")

        # Log the transformed request body
        self.logger.debug("Transformed ResponsesBody: %s", json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
            
        # Send to OpenAI Responses API
        if responses_body.stream:
            # Return async generator for partial text
            return self._multi_turn_streaming(responses_body, valves, __event_emitter__, __metadata__, __tools__)
        else:
            # Return final text (non-streaming)
            return await self._multi_turn_non_streaming(responses_body, valves, __event_emitter__, __metadata__, __tools__)

    # 4.3 Core Multi-Turn Handlers
    async def _multi_turn_streaming(
        self,
        body: ResponsesBody,                                        # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_TOOL_CALL_LOOPS, API_KEY, etc.
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]], # Function to emit events to the front-end UI
        metadata: Dict[str, Any] = {},                              # Metadata for the request (e.g., session_id, chat_id)
        tools: Optional[Dict[str, Dict[str, Any]]] = None,          # Optional tools dictionary for function calls
    ) -> AsyncGenerator[str, None]:
        """Stream a conversation loop, handling tools and reasoning events.

        The generator yields partial text deltas as they arrive from the
        Responses API.  Each iteration checks for function calls, executes them
        if present and then continues until a final answer is produced or the
        maximum number of tool-call loops is reached.
        """

        reasoning_map: Dict[int, str] = {}
        total_usage: Dict[str, Any] = {}
        collected_items: List[dict] = []  # For storing function_call, function_call_output, etc.



        tools = tools or {}
        final_output = StringIO()

        self.logger.debug(
            "Entering _multi_turn_streaming with up to %d loops",
            valves.MAX_TOOL_CALL_LOOPS,
        )

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
                final_response_data: dict[str, Any] | None = None
                reasoning_map.clear()
                self.logger.debug(
                    "Starting loop %d of %d", loop_idx + 1, valves.MAX_TOOL_CALL_LOOPS
                )
                async for event in self._call_llm_sse(body.model_dump(exclude_none=True), api_key=valves.API_KEY, base_url=valves.BASE_URL):
                    event_type = event.get("type")

                    # Partial text output
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            #yield delta  # Yield partial text to Open WebUI
                            final_output.write(delta)  # Accumulate in final_output
                            yield delta

                        continue # continue to next event

                    # Partial reasoning summary output
                    elif event_type == "response.reasoning_summary_text.delta":
                        idx = event.get("summary_index", 0)
                        delta = event.get("delta", "")
                        if delta:
                            # 1) Accumulate for this summary_index
                            reasoning_map[idx] = reasoning_map.get(idx, "") + delta

                            # 2) Merge all blocks (sorted), separated by ---
                            all_text = "\n\n --- \n\n".join(reasoning_map[i] for i in sorted(reasoning_map))

                            # 3) Extract latest title, else fallback to 'Thinking...'
                            matches = re.findall(r"\*\*(.+?)\*\*", all_text, flags=re.DOTALL)
                            latest_title = matches[-1].strip() if matches else "Thinking..."

                            # 4) Build a minimal snippet (omit type="reasoning")
                            snippet = (
                                f"<details type=\"{__name__}.reasoning\" done=\"false\">\n"
                                f"<summary>🧠{latest_title}</summary>\n"
                                f"{all_text}\n"
                                "</details>"
                            )
                            if event_emitter:
                                await event_emitter(
                                    {"type": "chat:completion", "data": {"content": snippet}}
                                )

                            # 5) Emit to the front end
                            yield "" # Yield an empty string to release the event loop for responsiveness

                        continue

                    # Output item added (e.g., tool call started, reasoning started, etc..)
                    elif event_type == "response.output_item.added":
                        item = event.get("item", {})
                        item_type = item.get("type", "")

                        self.logger.debug("output_item.added event received: %s", json.dumps(item, indent=2, ensure_ascii=False))

                        msg: str | None = None
                        if item_type == "web_search_call":
                            msg = "🔍 Searching the web..."
                        elif item_type == "function_call":
                            msg = f"🛠️ Running {item.get('name', 'a tool')}..."
                        elif item_type == "file_search_call":
                            msg = "📂 Searching files..."
                        elif item_type == "image_generation_call":
                            msg = "🎨 Generating image..."
                        elif item_type == "local_shell_call":
                            msg = "💻 Executing command..."

                        if msg:
                            await self._emit_status(event_emitter, msg, done=False, hidden=False)
                        
                        continue  # continue to next event

                    # Output item done (e.g., tool call finished, reasoning done, etc.)
                    elif event_type == "response.output_item.done":
                        item = event.get("item", {})
                        item_type = item.get("type", "")

                        msg: str | None = None
                        if item_type == "web_search_call":
                            msg = "🔎 Done searching."
                        elif item_type == "function_call":
                            msg = "🛠️ Tool finished."
                        elif item_type == "file_search_call":
                            msg = "📂 File search complete."
                        elif item_type == "image_generation_call":
                            msg = "🎨 Image ready."
                        elif item_type == "local_shell_call":
                            msg = "💻 Command complete."

                        if msg:
                            await self._emit_status(event_emitter, msg, done=True, hidden=False)

                        if item_type == "reasoning":
                            # Merge all partial reasoning so far
                            all_text = "\n\n --- \n\n".join(reasoning_map[i] for i in sorted(reasoning_map))

                            if all_text:
                                all_text += "\n\n --- \n\n"

                                final_snippet = (
                                    f'<details type=\"{__name__}.reasoning\" done="true">\n'
                                    f"<summary>Done thinking!</summary>\n"
                                    f"{all_text}\n"
                                    "</details>"
                                )
                                yield final_snippet  # Yield an empty string to release the event loop for responsiveness
                            else:
                                await self._emit_status(event_emitter, "Done thinking!", done=True, hidden=False)

                            reasoning_map.clear()

                        continue  # continue to next event

                    # Response completed event
                    elif event_type == "response.completed":
                        self.logger.debug("Response completed event received.")
                        final_response_data = event.get("response", {})
                        yield ""
                        break # Exit the streaming loop to process the final response
                
                if final_response_data is None:
                    self.logger.error("Streaming ended without a final response.")
                    break

                # Capture the final output items
                collected_items.extend(final_response_data.get("output", []))
                usage = final_response_data.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in final_response_data["output"] if i["type"] == "function_call"
                    )
                    update_usage_totals(total_usage, usage)

                body.input.extend(final_response_data.get("output", []))

                # Run function calls if present
                calls = [i for i in final_response_data.get("output", []) if i["type"] == "function_call"]
                if calls:
                    function_call_outputs = await self._execute_function_calls(calls, tools)
                    collected_items.extend(function_call_outputs) # Store function call outputs to be persisted in DB later
                    body.input.extend(function_call_outputs) # Append to input for next iteration
                else:
                    self.logger.debug("No pending function calls. Exiting loop.")
                    break # LLM response is complete, no further tool calls

        except Exception as e:
            await self._emit_error(
                event_emitter,
                e,
                show_error_message=True,
                show_error_log_citation=True,
                done=True,
            )
            return
        

        finally:
            self.logger.debug("Exiting _multi_turn_streaming loop.")
            # Final cleanup: close the aiohttp session if it was created

            if total_usage:
                # Emit final usage stats if available
                await self._emit_completion(event_emitter, usage=total_usage, done=False) # OpenWebUI sends it's own completion event, so we set done=False here to avoid double completion events

            # If PERSIST_TOOL_RESULTS is enabled, append all collected items (function_call, function_call_output, web_search, image_generation, etc.) to the chat message history
            if valves.PERSIST_TOOL_RESULTS and collected_items:
                db_items = [item for item in collected_items if item.get("type") != "message"]
                if db_items:
                    add_openai_response_items_to_chat_by_id_and_message_id(
                        metadata.get("chat_id"),
                        metadata.get("message_id"),
                        db_items,
                        metadata.get("model").get("id"),
                    ) 

            # If valves is DEBUG or user_valves is set to something other than "INHERIT"
            if valves.LOG_LEVEL == "DEBUG":
                if event_emitter:
                    logs = SessionLogger.logs.get(SessionLogger.session_id.get(), [])
                    if logs:
                        await self._emit_citation(
                            event_emitter,
                            "\n".join(logs),
                            f"{valves.LOG_LEVEL.capitalize()} Logs",
                        )

            # Clear logs after emitting
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)

    async def _multi_turn_non_streaming(
        self,
        body: ResponsesBody,                                       # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_TOOL_CALL_LOOPS, API_KEY, etc.
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]], # Function to emit events to the front-end UI
        metadata: Dict[str, Any] = {},                              # Metadata for the request (e.g., session_id, chat_id)
        tools: Optional[Dict[str, Dict[str, Any]]] = None,          # Optional tools dictionary for function calls
    ) -> str:
        """Multi-turn conversation loop using blocking requests.

        Each iteration performs a standard POST request rather than streaming
        SSE chunks.  The returned JSON is parsed, optional tool calls are
        executed and the final text is accumulated before being returned.
        """

        tools = tools or {}
        final_output = StringIO()
        total_usage: Dict[str, Any] = {}
        collected_items: List[dict] = []

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
                response = await self._call_llm_non_stream(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                )

                items = response.get("output", [])
                collected_items.extend(items)

                # append text from any message blocks
                for item in items:
                    if item.get("type") != "message":
                        continue
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            final_output.write(content.get("text", ""))

                usage = response.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in items if i.get("type") == "function_call"
                    )
                    update_usage_totals(total_usage, usage)

                body.input.extend(items)

                # Run tools if requested
                calls = [i for i in items if i.get("type") == "function_call"]
                if calls:
                    fn_outputs = await self._execute_function_calls(calls, tools)
                    collected_items.extend(fn_outputs)
                    body.input.extend(fn_outputs)
                else:
                    break

        except Exception as e:  # pragma: no cover - network errors
            await self._emit_error(
                event_emitter,
                e,
                show_error_message=True,
                show_error_log_citation=True,
                done=True,
            )
            return ""
        finally:
            if total_usage:
                await self._emit_completion(event_emitter, usage=total_usage, done=True)

            # Clear logs
            logs_by_msg_id.clear()
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)

        return final_output.getvalue()
    
    # 4.4 Task Model Handling
    async def _handle_task(
        self,
        body: Dict[str, Any],
        valves: Pipe.Valves
    ) -> Dict[str, Any]:
        """Process a task model request via the Responses API.

        Task models (e.g. generating a chat title or tags) return their
        information as standard Responses output.  This helper performs a single
        non-streaming call and extracts the plain text from the response items.
        """

        task_body = {
            "model": body.get("model"),
            "instructions": body.get("instructions", ""),
            "input": body.get("input", ""),
            "stream": False,
        }

        response = await self._call_llm_non_stream(
            task_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )

        text_parts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_parts.append(content.get("text", ""))

        message = "".join(text_parts)

        return message
      
    # 4.5 LLM HTTP Request Helpers
    async def _call_llm_sse(
        self,
        request_body: dict[str, Any],
        api_key: str,
        base_url: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE events from the Responses endpoint as soon as they arrive.

        This low-level helper is tuned for minimal latency when streaming large
        responses.  It decodes each ``data:`` line and yields the parsed JSON
        payload immediately.
        """
        # Get or create aiohttp session (aiohttp is used for performance).
        self.session = await self._get_or_create_aiohttp_session()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"

        buf = bytearray()
        orjson_loads = orjson.loads  # Cached reference for speed
        async with self.session.post(url, json=request_body, headers=headers) as resp:
            resp.raise_for_status()

            async for chunk in resp.content.iter_chunked(4096):
                buf.extend(chunk)
                start_idx = 0
                # Process all complete lines in the buffer
                while True:
                    newline_idx = buf.find(b"\n", start_idx)
                    if newline_idx == -1:
                        break
                    
                    line = buf[start_idx:newline_idx].strip()
                    start_idx = newline_idx + 1

                    # Skip empty lines, comment lines, or anything not starting with "data:"
                    if (not line or line.startswith(b":") or not line.startswith(b"data:")):
                        continue

                    data_part = line[5:].strip()
                    if data_part == b"[DONE]":
                        return  # End of SSE stream
                    
                    # Yield JSON-decoded data
                    yield orjson_loads(data_part)

                # Remove processed data from the buffer
                if start_idx > 0:
                    del buf[:start_idx]

    async def _call_llm_non_stream(
        self,
        request_params: dict[str, Any],
        api_key: str,
        base_url: str,
    ) -> Dict[str, Any]:
        """Send a blocking request to the Responses API and return the JSON payload."""
        # Get or create aiohttp session (aiohttp is used for performance).
        self.session = await self._get_or_create_aiohttp_session()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"

        async with self.session.post(url, json=request_params, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def _get_or_create_aiohttp_session(self) -> aiohttp.ClientSession:
        """Return a cached ``aiohttp.ClientSession`` instance.

        The session is created with connection pooling and sensible timeouts on
        first use and is then reused for the lifetime of the process.
        """
        # Reuse existing session if available and open
        if self.session is not None and not self.session.closed:
            self.logger.debug("Reusing existing aiohttp.ClientSession")
            return self.session

        self.logger.debug("Creating new aiohttp.ClientSession")

        # Configure TCP connector for connection pooling and DNS caching
        connector = aiohttp.TCPConnector(
            limit=50,  # Max total simultaneous connections
            limit_per_host=10,  # Max connections per host
            keepalive_timeout=75,  # Seconds to keep idle sockets open
            ttl_dns_cache=300,  # DNS cache time-to-live in seconds
        )

        # Set reasonable timeouts for connection and socket operations
        timeout = aiohttp.ClientTimeout(
            connect=30,  # Max seconds to establish connection
            sock_connect=30,  # Max seconds for socket connect
            sock_read=3600,  # Max seconds for reading from socket (1 hour)
        )

        # Use orjson for fast JSON serialization
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            json_serialize=lambda obj: orjson.dumps(obj).decode(),
        )

        return session
    
    # 4.6 Tool Execution Logic
    @staticmethod
    async def _execute_function_calls(
        calls: list[dict],                      # raw call-items from the LLM
        tools: dict[str, dict[str, Any]],       # name → {callable, …}
    ) -> list[dict]:
        """Execute one or more tool calls and return their outputs.

        Each call specification is looked up in the ``tools`` mapping by name
        and executed concurrently.  The returned list contains synthetic
        ``function_call_output`` items suitable for feeding back into the LLM.
        """
        def _make_task(call):
            tool_cfg = tools.get(call["name"])
            if not tool_cfg:                                 # tool missing
                return asyncio.sleep(0, result="Tool not found")

            fn = tool_cfg["callable"]
            args = orjson.loads(call["arguments"])

            if inspect.iscoroutinefunction(fn):              # async tool
                return fn(**args)
            else:                                            # sync tool
                return asyncio.to_thread(fn, **args)

        tasks   = [_make_task(call) for call in calls]       # ← fire & forget
        results = await asyncio.gather(*tasks)               # ← runs in parallel

        return [
            {
                "type":   "function_call_output",
                "call_id": call["call_id"],
                "output":  str(result),
            }
            for call, result in zip(calls, results)
        ]

    # 4.7 Emitters (Front-end communication)
    async def _emit_error(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]],
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        show_error_log_citation: bool = False,
        done: bool = False,
    ) -> None:
        """Log an error and optionally surface it to the UI.

        When ``show_error_log_citation`` is true the function also emits the
        collected debug logs as a citation block so users can inspect what went
        wrong.
        """
        error_message = str(error_obj)  # If it's an exception, convert to string
        self.logger.error("Error: %s", error_message)

        if show_error_message and event_emitter:
            await event_emitter(
                {
                    "type": "chat:completion",
                    "data": {
                        "error": {"message": error_message},
                        "done": done,
                    },
                }
            )

            # 2) Optionally emit the citation with logs
            if show_error_log_citation:
                session_id = SessionLogger.session_id.get()
                logs = SessionLogger.logs.get(session_id, [])
                if logs:
                    await self._emit_citation(
                        event_emitter,
                        "\n".join(logs),
                        "Error Logs",
                    )
                else:
                    self.logger.warning(
                        "No debug logs found for session_id %s", session_id
                    )

    async def _emit_citation(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        document: str | list[str],
        source_name: str,
    ) -> None:
        """Send a citation block to the UI if an emitter is available.

        ``document`` may be either a single string or a list of strings.  The
        function normalizes this input and emits a ``citation`` event containing
        the text and its source metadata.
        """
        if event_emitter is None:
            return

        if isinstance(document, list):
            doc_text = "\n".join(document)
        else:
            doc_text = document

        await event_emitter(
            {
                "type": "citation",
                "data": {
                    "document": [doc_text],
                    "metadata": [
                        {
                            "date_accessed": datetime.datetime.now().isoformat(),
                            "source": source_name,
                        }
                    ],
                    "source": {"name": source_name},
                },
            }
        )

    async def _emit_completion(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        content: str | None = "",                       # always included (may be "").  UI will stall if you leave it out.
        title:   str | None = None,                     # optional title.
        usage:   dict[str, Any] | None = None,          # optional usage block
        done:    bool = True,                           # True → final frame
    ) -> None:
        """Emit a ``chat:completion`` event if an emitter is present.

        The ``done`` flag indicates whether this is the final frame for the
        request.  When ``usage`` information is provided it is forwarded as part
        of the event data.
        """
        if event_emitter is None:
            return

        # Note: Open WebUI emits a final "chat:completion" event after the stream ends, which overwrites any previously emitted completion events' content and title in the UI.
        await event_emitter(
            {
                "type": "chat:completion",
                "data": {
                    "done": done,
                    "content": content,
                    **({"title": title} if title is not None else {}),
                    **({"usage": usage} if usage is not None else {}),
                }
            }
        )

    async def _emit_status(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
    ) -> None:
        """Emit a short status update to the UI.

        ``hidden`` allows emitting a transient update that is not shown in the
        conversation transcript.
        """
        if event_emitter is None:
            return
        
        await event_emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done, "hidden": hidden},
            }
        )

    async def _emit_notification(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        """Emit a toast-style notification to the UI.

        The ``level`` argument controls the styling of the notification banner.
        """
        if event_emitter is None:
            return

        await event_emitter(
            {"type": "notification", "data": {"type": level, "content": content}}
        )

    # 4.8 Internal Static Helpers
    def _merge_valves(self, global_valves, user_valves) -> "Pipe.Valves":
        """Merge user-level valves into the global defaults.

        Any field set to ``"INHERIT"`` (case-insensitive) is ignored so the
        corresponding global value is preserved.
        """
        if not user_valves:
            return global_valves

        # Merge: update only fields not set to "INHERIT"
        update = {
            k: v
            for k, v in user_valves.model_dump().items()
            if v is not None and str(v).lower() != "inherit"
        }
        return global_valves.model_copy(update=update)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Utility Classes (Shared utilities)
# ─────────────────────────────────────────────────────────────────────────────
# Support classes used across the pipe implementation
class SessionLogger:
    session_id = ContextVar("session_id", default=None)
    log_level = ContextVar("log_level", default=logging.INFO)
    logs = defaultdict(lambda: deque(maxlen=1000))

    @classmethod
    def get_logger(cls, name=__name__):
        """Return a logger wired to the current ``SessionLogger`` context."""
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Single combined filter
        def filter(record):
            record.session_id = cls.session_id.get()
            return record.levelno >= cls.log_level.get()

        logger.addFilter(filter)

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s"))
        logger.addHandler(console)

        # Memory handler
        mem = logging.Handler()
        mem.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        mem.emit = lambda r: cls.logs[r.session_id].append(mem.format(r)) if r.session_id else None
        logger.addHandler(mem)

        return logger

# In-memory store for debug logs keyed by message ID
logs_by_msg_id: dict[str, list[str]] = defaultdict(list)
# Context variable tracking the current message being processed
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
    
# ─────────────────────────────────────────────────────────────────────────────
# 6. Framework Integration Helpers (Open WebUI DB operations)
# ─────────────────────────────────────────────────────────────────────────────
# Utility functions that interface with Open WebUI's data models
def add_openai_response_items_to_chat_by_id_and_message_id(
    chat_id: str,
    message_id: str,
    items: List[Dict[str, Any]],
    model_id: str,
) -> Optional[ChatModel]:
    """
    Helper to persist OpenAI responses safely in Open WebUI DB without impacting other
    chat data. This allows us to store function call traces, tool outputs, and other
    special items related to messages in a structured way, enabling easy retrieval
    and reconstruction of conversations with additional context.

    Schema Overview
    ---------------
    Inside each chat document (`chat_model.chat`), we store an `openai_responses_pipe` structure:

        {
        "openai_responses_pipe": {
            "__v": 2,                           # version

            "messages": {
            "<message_id>": {
                "model": "o4-mini",          # stamped once – avoids per-item duplication
                "timestamp": 1719922512,    # unix-seconds the root message arrived

                "items": [ /* raw output items in arrival order */ ]
            }
            },
        }
        }

    When users or the system perform a function call (or any special action)
    related to a message, we append these "response items" to
    `openai_responses_pipe.messages[<message_id>]`. Later, when reconstructing
    the conversation, these items can be inserted above the respective message
    that triggered them. This allows for easy referencing of function calls,
    their outputs, or any other extra JSON data in the final conversation flow.
    """
    if not items:
        return Chats.get_chat_by_id(chat_id)  # nothing to add

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return None

    pipe_root = chat_model.chat.setdefault("openai_responses_pipe", {"__v": 2})
    messages_dict = pipe_root.setdefault("messages", {})

    bucket = messages_dict.setdefault(
        message_id,
        {
            "model": model_id,
            "timestamp": int(datetime.datetime.utcnow().timestamp()),
            "items": [],
        },
    )
    bucket.setdefault("model", model_id)
    bucket.setdefault("timestamp", int(datetime.datetime.utcnow().timestamp()))
    bucket.setdefault("items", [])
    bucket["items"].extend(items)

    return Chats.update_chat_by_id(chat_id, chat_model.chat)

def build_responses_history_by_chat_id_and_message_id(
    chat_id: str,
    message_id: Optional[str] = None,
    *,
    model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Reconstructs a chain of messages up to `message_id` (or the currentId)
    and inserts any items from `openai_responses_pipe.messages[<msg-id>]`
    before the corresponding message.

    Returns a list of items the OpenAI Responses API expects:
      [
        {"type": "function_call", ...},
        {"type": "message", "role": "assistant", "content": [...]},
        ...
      ]
    """
    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return [] # No previous history found, return empty history

    chat_data = chat_model.chat
    if not message_id:
        message_id = chat_data.get("history", {}).get("currentId")

    messages_dict = chat_data.get("history", {}).get("messages", {})
    pipe_messages = chat_data.get("openai_responses_pipe", {}).get("messages", {})

    # Walk through the full chain of messages in order
    message_chain = get_message_list(messages_dict, message_id)

    # Filter out the current [empty] assistant response.
    if message_chain and message_chain[-1]["role"] == "assistant":
        message_chain = message_chain[:-1]

    # Build one flat timeline of all events
    timeline = []

    # Regex to strip <details> from assistant messages
    DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", flags=re.S | re.I)

    for msg in message_chain:
        msg_timestamp = msg.get("timestamp", 0)
        role = msg.get("role", "assistant")
        content_text = (msg.get("content") or "")

        # Remove <details> blocks (reasoning summaries, etc..) for assistant
        if role == "assistant":
            content_text = DETAILS_RE.sub("", content_text).strip()

        # Add the structured message to the timeline
        timeline.append({
            "timestamp": msg_timestamp,  # Temporary field used for sorting; removed later
            "type": "message",           # Explicitly denote this timeline entry as a message event (recommended by OpenAI docs)
            "role": role,                # Indicates the sender's role: "user" or "assistant"
            "content": [
                # Add text content (if non-empty)
                *(
                    [{"type": "input_text" if role == "user" else "output_text", "text": content_text}]
                    if content_text else []
                ),

                # Add image(s) if type='image' and url is present.  Url may be a URL or base64-encoded data.
                *(
                    [
                        {
                            "type": "input_image" if role == "user" else "output_image",
                            "image_url": file["url"], # URL or base64-encoded data
                        }
                        for file in msg.get("files", [])
                        if file.get("type") == "image" and file.get("url")
                    ]
                ),
            ]
        })

        # Also add any pipe items (extras) linked to this message
        extras_bucket = pipe_messages.get(msg["id"], {})
        extras = extras_bucket.get("items", [])
        for extra in extras:
            timeline.append({
                "timestamp": extra.get("timestamp", msg_timestamp),
                **extra  # all fields from the pipe item
            })

    # Sort everything by timestamp so history matches reality
    timeline.sort(key=lambda event: event["timestamp"])

    # Remove 'timestamp' key before returning to API (for cleanliness)
    return [
        {k: v for k, v in event.items() if k != "timestamp"}
        for event in timeline
    ]

# ─────────────────────────────────────────────────────────────────────────────
# 7. General-Purpose Utility Functions (Data transforms & patches)
# ─────────────────────────────────────────────────────────────────────────────
# Helper functions shared by multiple parts of the pipe
def update_usage_totals(total, new):
    """Recursively merge nested usage statistics."""
    for k, v in new.items():
        if isinstance(v, dict):
            total[k] = update_usage_totals(total.get(k, {}), v)
        elif isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        else:
            # Skip or explicitly set non-numeric values
            total[k] = v if v is not None else total.get(k, 0)
    return total

def patch_model_param_field(model_id: str, field: str, value: Any):
    """Update a model's parameter field if it differs from ``value``."""
    model = Models.get_model_by_id(model_id)
    if not model:
        return

    form_data = model.model_dump()
    form_data["params"] = dict(model.params or {})
    if form_data["params"].get(field) == value:
        return

    form_data["params"][field] = value

    form = ModelForm(**form_data)
    Models.update_model_by_id(model_id, form)

def remove_details_tags_by_type(text: str, removal_types: list[str]) -> str:
    """Strip ``<details>`` blocks matching the specified ``type`` values.

    Example::

        remove_details_tags_by_type("Hello <details type='reasoning'>stuff</details>", ["reasoning"])
        # -> "Hello "
    """
    # Safely escape the types in case they have special regex chars
    pattern_types = "|".join(map(re.escape, removal_types))
    # Example pattern: <details type="reasoning">...</details>
    pattern = rf'<details\b[^>]*\btype=["\'](?:{pattern_types})["\'][^>]*>.*?</details>'
    return re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)



#####################

# Helper utilities for persistent item ID encoding/decoding

# Pre-compiled regex for performance
ENCODED_ID_PATTERN = re.compile(f"[{ZERO}{ONE}]+")  # e.g., ZERO="\u200b", ONE="\u200c"

def encode_id(item_id: str) -> str:
    """Encode a plain identifier into zero-width characters."""
    bits = "".join(f"{ord(ch):08b}" for ch in item_id)
    return "".join(ZERO if bit == "0" else ONE for bit in bits)


def decode_id(encoded: str) -> str:
    """Decode a zero-width encoded identifier back to text."""
    bits = "".join("0" if ch == ZERO else "1" for ch in encoded if ch in (ZERO, ONE))
    chars = [chr(int(bits[i : i + 8], 2)) for i in range(0, len(bits), 8)]
    return "".join(chars)

def is_encoded(content: str) -> bool:
    """Quickly checks if the content contains encoded IDs."""
    return bool(ENCODED_ID_PATTERN.search(content))

def extract_encoded_ids(content: str) -> List[str]:
    """Extracts and decodes all encoded IDs found within content."""
    return [decode_id(match) for match in ENCODED_ID_PATTERN.findall(content)]

def split_content_by_encoded_ids(content: str) -> List[Dict[str, str]]:
    """Splits content into an ordered list of text and encoded ID segments."""
    segments = []
    parts = re.split(f"({ENCODED_ID_PATTERN.pattern})", content)

    for part in parts:
        if not part:
            continue
        if ENCODED_ID_PATTERN.fullmatch(part):
            segments.append({"type": "encoded_id", "id": decode_id(part)})
        else:
            segments.append({"type": "text", "text": part})

    return segments

def fetch_items_by_ids(chat_id: str, item_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch persisted item payloads by ID from the chat database."""
    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return {}

    items_store = chat_model.chat.get("openai_responses_pipe", {}).get("items", {})
    lookup: Dict[str, Dict[str, Any]] = {}
    for item_id in item_ids:
        item = items_store.get(item_id)
        if item:
            lookup[item_id] = item.get("payload", {})
    return lookup

def build_openai_input(body_messages: List[Dict[str, str]], chat_id: str) -> List[Dict[str, Any]]:
    """
    Constructs an OpenAI-compatible input array from provided body_messages, resolving encoded IDs
    to persisted items as needed. Efficiently minimizes database operations.
    """
    openai_input = []

    # First pass: Determine all needed item IDs for a single database query
    required_item_ids = set()
    for message in body_messages:
        if message["role"] == "assistant" and is_encoded(message["content"]):
            required_item_ids.update(extract_encoded_ids(message["content"]))

    # Single DB call if there are any IDs to fetch
    items_lookup = fetch_items_by_ids(chat_id, list(required_item_ids)) if required_item_ids else {}

    # Second pass: Construct final OpenAI input, maintaining correct order
    for message in body_messages:
        role = message["role"]
        content = message["content"]

        if role == "user":
            openai_input.append({
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": content}]
            })
            continue  # No further processing for user messages

        # Assistant messages with potential encoded IDs
        if is_encoded(content):
            segments = split_content_by_encoded_ids(content)

            for segment in segments:
                if segment["type"] == "encoded_id":
                    item_id = segment["id"]
                    item = items_lookup.get(item_id)
                    if item:
                        openai_input.append(item)
                    else:
                        logging.getLogger(__name__).warning(
                            "Missing persisted item for ID: %s", item_id
                        )
                elif segment["type"] == "text":
                    text = segment["text"].strip()
                    if text:
                        openai_input.append({
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text}]
                        })
        else:
            # Simple assistant messages without encoded IDs
            openai_input.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}]
            })

    return openai_input
