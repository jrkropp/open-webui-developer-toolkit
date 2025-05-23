"""
title: OpenAI Responses API Pipeline
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
version: 1.6.19
license: MIT
requirements: httpx

------------------------------------------------------------------------------
🚀 CURRENT FEATURES
------------------------------------------------------------------------------
✅ o3/o4-mini o-series support (including visible <think> reasoning summaries)
✅ Image Input: Directly upload images into conversations.
✅ Built-in Web Search: Enabled via Pipe valve (powered by OpenAI web_search tool)
✅ Usage Stats: passthrough (to OpenWebUI GUI)
✅ Gateway Compatible: Supports LiteLLM and similar API gateways that support response API.
✅ Customizable logging: Set at a pipe or per-user level via Valves. If set to 'debug', adds citation for easy access.
✅ Optional injection of today's date and user context into the system prompt.
✅ Optimized Native Tool Calling:
   - True parallel tool calling support (i.e., gather multiple tool calls within a single turn and execute in parallel)
   - Live status updates showing running tools.
   - Tool outputs captured as citations for traceability & transparancy.
   - Persistent tool results (`function_call`/`function_call_output`) in conversation history (valve-controlled).
   - Automatically enables 'Native tool calling' in OpenWebUI model parm (if not set already).
   
------------------------------------------------------------------------------
🛠️ ROADMAP (PLANNED FEATURES)
------------------------------------------------------------------------------
⏳ Image Output: Direct generation of images using gpt-image-1 / dall-e-3 / dall-e-2
⏳ Document/File Input: Upload PDFs or other files directly as conversational context.
⏳ File Search Tool: Integration with OpenAI’s `file_search` feature.

------------------------------------------------------------------------------
🛠 CHANGE LOG
------------------------------------------------------------------------------
• 1.6.19: Added support for 'o3-mini-high' and 'o4-mini-high' model aliases.
• 1.6.18: Compatibility fixes for WebUI task models (optional chat_id and emitter).
• 1.6.17: Valves to inject the current date and user/device context into the system prompt.
• 1.6.16: Valve to control persisting tool results in chat history.
• 1.6.15: Added valve to toggle native tool calling; skips unsupported models; `reasoning_effort` now read directly from request body.
• 1.6.11: Disabled HTTP/2 to prevent stream stalls; optimized connection pooling.
• 1.6.10: Switched streaming from OpenAI SDK to direct HTTP via httpx; lightweight SSE parser added.
• 1.6.9: Updated dependency to `openai>=1.78.0`; introduced `UserValves` for per-user config overrides; enhanced logging.
• 1.6.8: Added granular `CUSTOM_LOG_LEVEL` control; refactored codebase for readability and maintenance.
────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Literal
import inspect

import httpx
from fastapi import Request
from open_webui.models.chats import Chats
from open_webui.models.models import Models, ModelForm, ModelParams
from open_webui.utils.misc import deep_update, get_message_list
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

EMOJI_LEVELS = {
    logging.DEBUG: "\U0001F50D",
    logging.INFO: "\u2139",
    logging.WARNING: "\u26A0",
    logging.ERROR: "\u274C",
    logging.CRITICAL: "\U0001F525",
}

# Feature support by model
WEB_SEARCH_MODELS = {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"}
REASONING_MODELS = {"o3", "o4-mini", "o3-mini"}
NATIVE_TOOL_UNSUPPORTED_MODELS = {"chatgpt-4o-latest", "codex-mini-latest"}
IMAGE_GEN_TOOL_SUPPORTED_MODELS = {"gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano" "gpt-4o", "gpt-4o-mini", "o3"} # https://platform.openai.com/docs/guides/image-generation?image-generation-model=gpt-image-1&api=responses&multi-turn=imageid#supported-models

# Precompiled regex for citation annotations
ANNOT_TITLE_RE = re.compile(r"title='([^']*)'")
ANNOT_URL_RE = re.compile(r"url='([^']*)'")


@dataclass(slots=True)
class ResponsesEvent:
    """Parsed SSE event."""

    type: str
    delta: str | None = None
    text: str | None = None
    item_id: str | None = None
    item: Any | None = None
    response: Any | None = None
    annotation: Any | None = None
    partial_image_index: int | None = None
    partial_image_b64: str | None = None


class _MemHandler(logging.Handler):
    """In-memory log handler for per-request debug capture."""

    def __init__(self, buf: list[str]) -> None:
        super().__init__(logging.DEBUG)
        self.buf = buf

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        msg = self.format(record)
        self.buf.append(msg)


class Pipe:
    """Pipeline to interact with the OpenAI Responses API."""
    class Valves(BaseModel):
        BASE_URL: str = Field(
            default="https://api.openai.com/v1",
            description=(
                "The base URL to use with the OpenAI SDK. Defaults to the official "
                "OpenAI API endpoint. Supports LiteLLM and other custom endpoints."
            ),
        )

        API_KEY: str = Field(
            default=os.getenv(
                "OPENAI_API_KEY", "sk-xxxxx"
            ).strip(),
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )

        MODEL_ID: str = Field(
            default="gpt-4.1",
            description=(
                "Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI."
                " Supports the pseudo models 'o3-mini-high' and 'o4-mini-high', which map"
                " to 'o3-mini' and 'o4-mini' with reasoning effort forced to high."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-model

        REASON_SUMMARY: Literal["auto", "concise", "detailed", None] = Field(
            default=None,
            description=(
                "Reasoning summary style for o-series models (supported by: o3, o4-mini). Ignored for others."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning

        ENABLE_NATIVE_TOOL_CALLING: bool = Field(
            default=True,
            description="Enable native tool calling for supported models.",
        )

        ENABLE_WEB_SEARCH: bool = Field(
            default=False,
            description=(
                "Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini)."
            ),
        )  # Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses

        PERSIST_TOOL_RESULTS: bool = Field(
            default=True,
            description=(
                "Persist tool call results across conversation turns. When disabled,"
                " tool results are not stored in the chat history."
            ),
        )

        SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description=(
                "Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH=True."
            ),
        )

        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description="Whether tool calls can be parallelized. Defaults to True if not set.",
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls

        # TODO Need to rename as it's not truely max tool calls.  It's max tool loops.  It can call an unlimited number of tools within a single loop.
        MAX_TOOL_CALLS: int = Field(
            default=5,
            description=(
                "Maximum number of tool calls the model can make in a single request. This is a hard stop safety limit to prevent infinite loops. Defaults to 5."
            ),
        )

        STORE_RESPONSE: bool = Field(
            default=False,
            description=(
                "Whether to store the generated model response (on OpenAI's side) for later debuging. Defaults to False."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-store

        CUSTOM_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
            default=os.getenv("GLOBAL_LOG_LEVEL", "INFO").upper(),
            description="Select logging level.",
        )

        INJECT_CURRENT_DATE: bool = Field(
            default=False,
            description=(
                "Append today's date to the system prompt. "
                "Example: `Today's date: Thursday, May 21, 2025`."
            ),
        )

        INJECT_USER_INFO: bool = Field(
            default=False,
            description=(
                "Append the user's name and email. "
                "Example: `user_info: Jane Doe <jane@example.com>`."
            ),
        )

        INJECT_BROWSER_INFO: bool = Field(
            default=False,
            description=(
                "Append browser details. "
                "Example: `browser_info: Desktop | Windows | Browser: Edge 136`."
            ),
        )

        INJECT_IP_INFO: bool = Field(
            default=False,
            description=(
                "Append IP information with location if available. "
                "Example: `ip_info: 207.194.4.18 - Waterloo, Ontario, Canada (Bell Canada)`."
            ),
        )

    class UserValves(BaseModel):
        CUSTOM_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"] = "INHERIT"
        ENABLE_NATIVE_TOOL_CALLING: Literal[True, False, "INHERIT"] = "INHERIT"
        PERSIST_TOOL_RESULTS: Literal[True, False, "INHERIT"] = "INHERIT"
        INJECT_CURRENT_DATE: Literal[True, False, "INHERIT"] = "INHERIT"
        INJECT_USER_INFO: Literal[True, False, "INHERIT"] = "INHERIT"
        INJECT_BROWSER_INFO: Literal[True, False, "INHERIT"] = "INHERIT"
        INJECT_IP_INFO: Literal[True, False, "INHERIT"] = "INHERIT"

    def __init__(self) -> None:
        """Initialize the pipeline and logging."""
        self.valves = self.Valves()
        self.log_name = "OpenAI Responses"
        self._client: httpx.AsyncClient | None = None
        self._transport: httpx.AsyncHTTPTransport | None = None
        self._client_lock = asyncio.Lock()

        self.log = logging.getLogger(self.log_name)
        self.log.propagate = False
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(emo)s %(levelname)-8s | %(name)-20s:%(lineno)-4d — %(message)s"))
        handler.addFilter(lambda r: setattr(r, "emo", EMOJI_LEVELS.get(r.levelno, "\u2753")) or True)
        self.log.handlers = [handler]
        self.log.setLevel(logging.INFO)
        self._ip_cache: dict[str, str] = {}
        self._ip_tasks: dict[str, asyncio.Task] = {}

    def pipes(self):
        """Return models exposed by this pipe."""
        models = [m.strip() for m in self.valves.MODEL_ID.split(',') if m.strip()]
        return [{"id": mid, "name": f"OpenAI: {mid}"} for mid in models]

    async def on_shutdown(self) -> None:
        """Clean up the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        if self._transport:
            await self._transport.aclose()
            self._transport = None

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: Dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]],  # unused
        __files__: list[dict[str, Any]],
        __metadata__: dict[str, Any],
        __tools__: dict[str, Any],
    ) -> AsyncIterator[str]:
        """
        Stream responses from OpenAI and handle tool calls.
        """
        start_ns = time.perf_counter_ns()
        last_status: list[tuple[str, bool] | None] = [None]
        debug_logs: list[str] = []
        mem_handler = _MemHandler(debug_logs)
        mem_handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        self.log.addHandler(mem_handler)
        if self.log.isEnabledFor(logging.DEBUG):
            self.log.debug(
                pretty_log_block(
                    sanitize_for_log(
                        {
                            "body": body,
                            "__user__": __user__,
                            "__files__": __files__,
                            "__metadata__": __metadata__,
                            "__tools__": __tools__,
                        }
                    ),
                    "pipe_call",
                )
            )
        valves = self._apply_user_overrides(__user__.get("valves"))

        if valves.ENABLE_NATIVE_TOOL_CALLING:
            await self._ensure_native_function_calling(__metadata__)

        chat_id = __metadata__.get("chat_id")
        message_id = __metadata__.get("message_id")

        self.log.info(
            'CHAT_MSG pipe="%s" model=%s user=%s chat=%s message=%s',
            self.log_name,
            body.get("model", valves.MODEL_ID),
            __user__.get("email", "anon"),
            chat_id,
            message_id,
        )

        client = await self.get_http_client()
        # TODO Consider setting the user system prompt (if specified) as a developer message rather than replacing the model system prompt.  Right now it get's the last instance of system message (user system prompt takes precidence)
        instructions = self._extract_instructions(body)

        if valves.INJECT_CURRENT_DATE:
            instructions += "\n\n" + self._get_current_date_suffix()

        injection_lines: list[str] = []
        if valves.INJECT_USER_INFO:
            injection_lines.append(self._get_user_info_suffix(__user__))
        if valves.INJECT_BROWSER_INFO:
            injection_lines.append(self._get_browser_info_suffix(__request__))
        if valves.INJECT_IP_INFO:
            injection_lines.append(self._get_ip_info_suffix(__request__))
        if injection_lines:
            note_parts = []
            if valves.INJECT_USER_INFO:
                note_parts.append("`user_info`")
            if valves.INJECT_BROWSER_INFO:
                note_parts.append("`browser_info`")
            if valves.INJECT_IP_INFO:
                note_parts.append("`ip_info`")
            note = "Note: " + ", ".join(note_parts) + " provided solely for AI contextual enrichment."
            injection_lines.append(note)
            instructions += "\n\n" + "\n".join(injection_lines)

        model = body.get("model", valves.MODEL_ID.split(",")[0])
        if "." in str(model):
            model = str(model).split(".", 1)[1]

        tools: list[dict[str, Any]] | None
        if model in NATIVE_TOOL_UNSUPPORTED_MODELS:
            tools = None
        else:
            tools = transform_tools_for_responses_api(body.get("tools", []))
            if valves.ENABLE_WEB_SEARCH and model in WEB_SEARCH_MODELS:
                tools.append(
                    {
                        "type": "web_search",
                        "search_context_size": valves.SEARCH_CONTEXT_SIZE,
                    }
                )

        if self.log.isEnabledFor(logging.DEBUG):
            self.log.debug(pretty_log_block(tools, "tools"))

        request_params = await prepare_payload(
            valves,
            body,
            instructions,
            tools,
            __user__.get("email"),
            chat_id=chat_id,
        )
        if self.log.isEnabledFor(logging.DEBUG):
            self.log.debug(
                pretty_log_block(
                    sanitize_for_log(request_params),
                    "prepared_request_params",
                )
            )
        usage_total: dict[str, Any] = {}
        last_response_id = None
        cleanup_ids: list[str] = []
        temp_input: list[dict[str, Any]] = []
        is_model_thinking = False

        for loop_count in range(1, valves.MAX_TOOL_CALLS + 1):
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("Loop iteration #%d", loop_count)
            if loop_count > 1:
                request_params.update(
                    {
                        "previous_response_id": last_response_id,
                        "input": temp_input,
                    }
                )
                temp_input = []
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug(
                    pretty_log_block(
                        sanitize_for_log(request_params.get("input", [])),
                        f"turn_input_{loop_count}",
                    )
                )
                self.log.debug(
                    pretty_log_block(
                        sanitize_for_log(request_params),
                        f"openai_request_params_{loop_count}",
                    )
                )

            try:
                pending_calls: list[SimpleNamespace] = []
                if self.log.isEnabledFor(logging.DEBUG):
                    self.log.debug("Starting response stream (loop #%d)", loop_count)

                if request_params.get("reasoning") and not is_model_thinking:
                    is_model_thinking = True
                    yield "<think>"

                async for event in stream_responses(
                    client,
                    valves.BASE_URL,
                    valves.API_KEY,
                    request_params,
                ):
                    et = event.type
                    if self.log.isEnabledFor(logging.DEBUG) and not et.endswith(".delta"):
                        self.log.debug("Event received: %s", et)

                    if et == "response.created":
                        if last_response_id:
                            cleanup_ids.append(last_response_id)
                        last_response_id = event.response.id
                        continue
                    if et in {"response.done", "response.failed", "response.incomplete", "error"}:
                        self.log.error("Stream ended with event: %s", et)
                        break
                    if et == "response.reasoning_summary_part.added":
                        # The <think> tag is emitted at stream start when
                        # reasoning is enabled. No action needed here.
                        continue
                    if et == "response.reasoning_summary_text.delta":
                        yield event.delta
                        continue
                    if et == "response.reasoning_summary_text.done":
                        yield "\n\n---\n\n"
                        continue
                    if et == "response.content_part.added":
                        if is_model_thinking:
                            is_model_thinking = False
                            yield "</think>\n"
                        continue
                    if et == "response.output_text.delta":
                        yield event.delta
                        continue
                    if et == "response.output_text.done":
                        # This delta marks the end of the current output block.
                        continue
                    if et in {
                        "response.image_generation_call.in_progress",
                        "response.image_generation_call.generating",
                    }:
                        await self._emit_status(
                            __event_emitter__,
                            "🖼️ Generating image...",
                            last_status,
                        )
                        continue
                    if et == "response.image_generation_call.partial_image":
                        if __event_emitter__ and event.partial_image_b64:
                            await __event_emitter__(
                                {
                                    "type": "files",
                                    "data": {
                                        "files": [
                                            {
                                                "type": "image",
                                                "url": f"data:image/png;base64,{event.partial_image_b64}",
                                            }
                                        ]
                                    },
                                }
                            )
                        continue
                    if et == "response.image_generation_call.completed":
                        await self._emit_status(
                            __event_emitter__,
                            "🖼️ Image generation completed",
                            last_status,
                            done=True,
                        )
                        continue
                    if et == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) == "function_call":
                            await self._emit_status(
                                __event_emitter__,
                                f"🔧 Running {item.name}...",
                                last_status,
                            )
                        elif getattr(item, "type", None) == "web_search_call":
                            await self._emit_status(
                                __event_emitter__,
                                "🔍 Searching the internet...",
                                last_status,
                            )
                        continue
                    if et == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) == "function_call":
                            pending_calls.append(item)
                            await self._emit_status(
                                __event_emitter__,
                                f"🔧 Running {item.name}...",
                                last_status,
                                done=True,
                            )
                        elif getattr(item, "type", None) == "web_search_call":
                            await self._emit_status(
                                __event_emitter__,
                                "🔍 Searching the internet...",
                                last_status,
                                done=True,
                            )
                        elif getattr(item, "type", None) == "image_generation_call":
                            if __event_emitter__ and getattr(item, "result", None):
                                await __event_emitter__(
                                    {
                                        "type": "files",
                                        "data": {
                                            "files": [
                                                {
                                                    "type": "image",
                                                    "url": f"data:image/png;base64,{item.result}",
                                                }
                                            ]
                                        },
                                    }
                                )
                            await self._emit_status(
                                __event_emitter__,
                                "🖼️ Image generation completed",
                                last_status,
                                done=True,
                            )
                        continue
                    if et == "response.output_text.annotation.added":
                        raw = str(getattr(event, "annotation", ""))
                        title_m = ANNOT_TITLE_RE.search(raw)
                        url_m = ANNOT_URL_RE.search(raw)
                        title = title_m.group(1) if title_m else "Unknown Title"
                        url = url_m.group(1) if url_m else ""
                        url = url.replace("?utm_source=openai", "").replace("&utm_source=openai", "")
                        if __event_emitter__:
                            await __event_emitter__(
                                {
                                    "type": "citation",
                                    "data": {
                                        "document": [title],
                                        "metadata": [
                                            {
                                                "date_accessed": datetime.now().isoformat(),
                                                "source": title,
                                            }
                                        ],
                                        "source": {"name": url, "url": url},
                                    },
                                }
                            )
                        continue
                    if et == "response.completed":
                        if event.response.usage:
                            self._update_usage(
                                usage_total, event.response.usage, loop_count
                            )
                        continue
            except Exception as ex:
                self.log.error("Error in pipeline loop %d: %s", loop_count, ex)
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "message",
                            "data": {
                                "content": f"❌ {type(ex).__name__}: {ex}\n{''.join(traceback.format_exc(limit=5))}",
                            },
                        }
                    )
                break

            if pending_calls:
                results = await self._execute_tool_calls(pending_calls, __tools__)
                for call, result in zip(pending_calls, results):
                    function_call_output = {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": str(result),
                    }
                    temp_input.insert(0, function_call_output)
                    if __event_emitter__:
                        citation_data = {
                            "document": [f"{call.name}({call.arguments})\n\n{result}"],
                            "metadata": [
                                {
                                    "date_accessed": datetime.now().isoformat(),
                                    "source": call.name.replace("_", " ").title(),
                                }
                            ],
                            "source": {"name": f"{call.name.replace('_', ' ').title()} Tool"},
                        }
                        if valves.PERSIST_TOOL_RESULTS:
                            citation_data["_fc"] = [
                                {
                                    "call_id": call.call_id,
                                    "name": call.name,
                                    "arguments": call.arguments,
                                    "output": str(result),
                                }
                            ]
                        await __event_emitter__({"type": "citation", "data": citation_data})
                continue

            # Clean up the server-side state unless the user opted to keep it
            # TODO Ensure that the stored response is deleted.  Doesn't seem to work with LiteLLM Response API.
            remaining = valves.MAX_TOOL_CALLS - loop_count
            thought = ""
            if loop_count == valves.MAX_TOOL_CALLS:
                request_params["tool_choice"] = "none"
                thought = (
                    f"[Internal thought] Final iteration ({loop_count}/{valves.MAX_TOOL_CALLS}). "
                    "Tool-calling phase is over; I'll produce my final answer now."
                )
            elif loop_count == 2 and valves.MAX_TOOL_CALLS > 2:
                thought = (
                    f"[Internal thought] I've just received the initial tool results from iteration 1. "
                    f"I'm now continuing an iterative tool interaction with up to {valves.MAX_TOOL_CALLS} iterations."
                )
            elif remaining == 1:
                thought = (
                    f"[Internal thought] Iteration {loop_count}/{valves.MAX_TOOL_CALLS}. "
                    "Next iteration is answer-only; any remaining tool calls must happen now."
                )
            elif loop_count > 2:
                thought = (
                    f"[Internal thought] Iteration {loop_count}/{valves.MAX_TOOL_CALLS} "
                    f"({remaining} remaining, no action needed)."
                )
            if thought:
                entry = {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": thought}],
                }
                temp_input.append(entry)
                if self.log.isEnabledFor(logging.DEBUG):
                    self.log.debug(
                        "Appended to temp_input: %s",
                        json.dumps(entry, indent=2),
                    )
            break

        await self._emit_status(__event_emitter__, "", last_status, done=True)

        self.log.info(
            "CHAT_DONE chat=%s dur_ms=%.0f loops=%d in_tok=%d out_tok=%d total_tok=%d",
            chat_id,
            (time.perf_counter_ns() - start_ns) / 1e6,
            usage_total.get("loops", 1),
            usage_total.get("input_tokens", 0),
            usage_total.get("output_tokens", 0),
            usage_total.get("total_tokens", 0),
        )

        if usage_total and __event_emitter__:
            await __event_emitter__(
                {"type": "chat:completion", "data": {"usage": usage_total}}
            )

        if __event_emitter__:
            await __event_emitter__({"type": "chat:completion", "data": {"done": True}})

        for rid in cleanup_ids:
            try:
                await delete_response(
                    client,
                    valves.BASE_URL,
                    valves.API_KEY,
                    rid,
                )
            except Exception as ex:  # pragma: no cover - logging only
                self.log.warning("Failed to delete response %s: %s", rid, ex)

        if last_response_id and not valves.STORE_RESPONSE:
            try:
                await delete_response(
                    client,
                    valves.BASE_URL,
                    valves.API_KEY,
                    last_response_id,
                )
            except Exception as ex:  # pragma: no cover - logging only
                self.log.warning("Failed to delete response %s: %s", last_response_id, ex)

        if self.log.isEnabledFor(logging.DEBUG) and debug_logs and __event_emitter__:
            await __event_emitter__(
                {
                    "type": "citation",
                    "data": {
                        "document": ["\n".join(debug_logs)],
                        "metadata": [
                            {
                                "date_accessed": datetime.now().isoformat(),
                                "source": "Debug Logs",
                            }
                        ],
                        "source": {"name": "Debug Logs"},
                    },
                }
            )

        self.log.removeHandler(mem_handler)

    async def _execute_tool_calls(
        self, calls: list[SimpleNamespace], registry: dict[str, Any]
    ) -> list[Any]:
        """Run tool calls asynchronously and return their results."""
        if self.log.isEnabledFor(logging.DEBUG):
            self.log.debug(
                "Executing %d tool call(s): %s",
                len(calls),
                ", ".join(c.name for c in calls),
            )
        results = await execute_responses_tool_calls(calls, registry, self.log)
        if self.log.isEnabledFor(logging.DEBUG):
            for call, result in zip(calls, results):
                self.log.debug("%s -> %s", call.name, result)
        return results

    async def _emit_status(
        self,
        emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        description: str,
        last_status: list[tuple[str, bool] | None],
        *,
        done: bool = False,
    ) -> None:
        """Emit a status update if it differs from the last one."""
        if emitter is None:
            return
        current = (description, done)
        if last_status[0] == current:
            return
        last_status[0] = current
        await emitter({"type": "status", "data": {"description": description, "done": done}})

    def _apply_user_overrides(self, user_valves: BaseModel | None) -> 'Pipe.Valves':
        """Return a ``Valves`` instance with user overrides applied."""
        valves = self.valves
        if not user_valves:
            self.log.setLevel(
                getattr(logging, valves.CUSTOM_LOG_LEVEL.upper(), logging.INFO)
            )
            return valves

        overrides = {
            k: v
            for k, v in (
                user_valves.model_dump(exclude_none=True)
                if hasattr(user_valves, "model_dump")
                else user_valves.dict(exclude_none=True)
            ).items()
            if not (isinstance(v, str) and v.lower() == "inherit")
        }

        valves = self.Valves(
            **deep_update(
                valves.model_dump() if hasattr(valves, "model_dump") else valves.dict(),
                overrides,
            )
        )

        if self.log.isEnabledFor(logging.DEBUG):
            for setting, val in overrides.items():
                self.log.debug("User override → %s set to %r", setting, val)

        self.log.setLevel(
            getattr(logging, valves.CUSTOM_LOG_LEVEL.upper(), logging.INFO)
        )

        return valves

    @staticmethod
    def _get_current_date_suffix() -> str:
        """Return today's date formatted for prompt injection."""
        return "Today's date: " + datetime.now().strftime("%A, %B %d, %Y")

    async def _lookup_ip_info(self, ip: str) -> None:
        """Resolve ``ip`` and store the result in the cache."""
        try:
            client = await self.get_http_client()
            resp = await client.get(f"http://ip-api.com/json/{ip}")
            resp.raise_for_status()
            data = resp.json()
            location = ", ".join(
                filter(None, (data.get("city"), data.get("regionName"), data.get("country")))
            )
            isp = data.get("isp") or ""
            info = f"{location} (approx based on IP) (ISP: {isp})" if isp else location
        except Exception as exc:  # pragma: no cover - network errors
            info = ""
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("IP lookup failed for %s: %s", ip, exc)
        self._ip_cache[ip] = info
        self._ip_tasks.pop(ip, None)
        if self.log.isEnabledFor(logging.DEBUG):
            self.log.debug("IP lookup result %s -> %r", ip, info)

    def _schedule_ip_lookup(self, ip: str) -> None:
        """Kick off a background task to fetch IP details if not cached."""
        if ip in self._ip_cache or ip in self._ip_tasks or ip == "unknown":
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("IP lookup skipped for %s", ip)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._ip_tasks[ip] = loop.create_task(self._lookup_ip_info(ip))

    def _get_user_info_suffix(self, user: Dict[str, Any]) -> str:
        """Return a user_info line."""
        name = user.get("name") or ""
        email = user.get("email") or ""
        return f"user_info: {name} <{email}>"

    def _get_browser_info_suffix(self, request: Request | None) -> str:
        """Return a browser_info line."""
        headers = request.headers if request and hasattr(request, "headers") else {}
        mobile = str(headers.get("sec-ch-ua-mobile", "")).strip('"')
        device_type = "Mobile" if mobile in {"?1", "1"} else "Desktop"
        platform = headers.get("sec-ch-ua-platform", "").strip('"') or "Unknown"
        return (
            f"browser_info: {device_type} | {platform} | Browser: "
            f"{simplify_user_agent(headers.get('user-agent', '') if request else '')}"
        )

    def _get_ip_info_suffix(self, request: Request | None) -> str:
        """Return an ip_info line and trigger background lookup if needed."""
        ip = getattr(getattr(request, "client", None), "host", "unknown") if request else "unknown"
        ip_info = self._ip_cache.get(ip)
        if ip_info is None and ip != "unknown":
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("IP info not cached for %s, scheduling lookup", ip)
            self._schedule_ip_lookup(ip)
        return f"ip_info: {ip}{f' - {ip_info}' if ip_info else ''}"


    async def _ensure_native_function_calling(self, metadata: dict[str, Any]) -> None:
        """Enable native function calling for a model if not already active."""
        if metadata.get("function_calling") == "native":
            return

        model_dict = metadata.get("model") or {}
        model_id = model_dict.get("id") if isinstance(model_dict, dict) else model_dict
        if model_id in NATIVE_TOOL_UNSUPPORTED_MODELS:
            self.log.debug("Model %s does not support native tool calling", model_id)
            return
        self.log.debug("Enabling native function calling for %s", model_id)

        model_info = await asyncio.to_thread(Models.get_model_by_id, model_id) if model_id else None
        if model_info:
            model_data = model_info.model_dump()
            model_data["params"]["function_calling"] = "native"
            model_data["params"] = ModelParams(**model_data["params"])
            updated = await asyncio.to_thread(
                Models.update_model_by_id, model_info.id, ModelForm(**model_data)
            )
            if updated:
                self.log.info(
                    "✅ Set model %s to native function calling", model_info.id
                )
            else:
                self.log.error("❌ Failed to update model %s", model_info.id)
        else:
            self.log.warning("⚠️ Model info not found for id %s", model_id)

        metadata["function_calling"] = "native"


    async def get_http_client(self) -> httpx.AsyncClient:
        """Return a shared httpx client."""
        if self._client and not self._client.is_closed:
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("Reusing existing httpx client.")
            return self._client
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                if self.log.isEnabledFor(logging.DEBUG):
                    self.log.debug("Client initialized while waiting for lock. Reusing existing.")
                return self._client
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.debug("Creating new httpx.AsyncClient.")
            timeout = httpx.Timeout(900.0, connect=30.0)
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=50)
            # HTTP/2 can stall if flow control windows aren't consumed quickly.
            # Using HTTP/1.1 avoids mid-stream pauses in high traffic scenarios.
            self._transport = httpx.AsyncHTTPTransport(http2=False, limits=limits)
            self._client = httpx.AsyncClient(transport=self._transport, timeout=timeout)
        return self._client

    @staticmethod
    def _extract_instructions(body: dict[str, Any]) -> str:
        """Return the last system message from the chat body."""
        return next(
            (
                m.get("content")
                for m in reversed(body.get("messages", []))
                if m.get("role") == "system"
            ),
            "",
        )

    @staticmethod
    def _update_usage(total: dict[str, Any], current: dict[str, Any], loops: int) -> None:
        """Aggregate token usage stats without unnecessary conversions."""
        if isinstance(current, SimpleNamespace):
            current = vars(current)
        current = current or {}
        for key, value in current.items():
            if isinstance(value, SimpleNamespace):
                value = vars(value)
            if isinstance(value, (int, float)):
                total[key] = total.get(key, 0) + value
            elif isinstance(value, dict):
                inner = total.setdefault(key, {})
                for subkey, subval in value.items():
                    if isinstance(subval, (int, float)):
                        inner[subkey] = inner.get(subkey, 0) + subval
        total["loops"] = loops


async def stream_responses(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    params: dict[str, Any],
) -> AsyncIterator[ResponsesEvent]:
    """Yield parsed ``ResponsesEvent`` objects from the API."""

    url = base_url.rstrip("/") + "/responses"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "POST %s/responses model=%s",
            base_url.rstrip("/"),
            params.get("model"),
        )

    async with client.stream("POST", url, headers=headers, json=params) as resp:
        resp.raise_for_status()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Streaming response with status %s", resp.status_code)
        event_type: str | None = None
        data_buf: list[str] = []
        async for raw in resp.aiter_lines():
            line = raw.rstrip("\r")
            if line.startswith(":"):
                continue
            if line == "":
                if data_buf:
                    data = "\n".join(data_buf)
                    if data.strip() == "[DONE]":
                        return
                    yield parse_responses_sse(event_type, data)
                event_type, data_buf = None, []
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_buf.append(line[len("data:"):].strip())
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Response stream closed")
async def delete_response(
    client: httpx.AsyncClient, base_url: str, api_key: str, response_id: str
) -> None:
    """Delete a stored response."""
    url = base_url.rstrip("/") + f"/responses/{response_id}"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    resp = await client.delete(url, headers=headers)
    resp.raise_for_status()


def transform_tools_for_responses_api(
    tools_completion_api_json: list[dict] | None,
) -> list[dict]:
    """Return ``tools_completion_api_json`` converted for the Responses API."""

    tools_responses_api_json: list[dict] = []
    for tool in tools_completion_api_json or []:
        if not isinstance(tool, dict):
            continue
        tool_type = tool.get("type")
        if tool_type == "function" or "function" in tool:
            function_spec = tool.get("function", tool)
            tools_responses_api_json.append(
                {
                    "type": "function",
                    "name": function_spec.get("name"),
                    "description": function_spec.get("description", ""),
                    "parameters": function_spec.get("parameters", {"type": "object"}),
                }
            )
        else:
            tools_responses_api_json.append(tool)

    return tools_responses_api_json


async def build_chat_history_for_responses_api(
    *, chat_id: str | None = None, messages: list[dict] | None = None
) -> list[dict]:
    """Return chat history formatted for the Responses API."""

    from_history = bool(chat_id)
    if chat_id:
        logger.debug("Retrieving message history for chat_id=%s", chat_id)
        chat_model = await asyncio.to_thread(Chats.get_chat_by_id, chat_id)
        if not chat_model:
            messages = []
        else:
            chat = chat_model.chat
            msg_lookup = chat.get("history", {}).get("messages", {})
            current_id = chat.get("history", {}).get("currentId")
            messages = get_message_list(msg_lookup, current_id) or []
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(pretty_log_block(messages, "history_thread"))
    else:
        messages = messages or []

    history: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        from_assistant = role == "assistant"

        if from_history and from_assistant:
            for src in m.get("sources", []):
                for fc in src.get("_fc", []):
                    cid = fc.get("call_id") or fc.get("id")
                    if not cid:
                        continue
                    history.append(
                        {
                            "type": "function_call",
                            "call_id": cid,
                            "name": fc.get("name") or fc.get("n"),
                            "arguments": fc.get("arguments") or fc.get("a"),
                        }
                    )
                    history.append(
                        {
                            "type": "function_call_output",
                            "call_id": cid,
                            "output": fc.get("output") or fc.get("o"),
                        }
                    )

        blocks: list[dict] = []
        raw_blocks = m.get("content", []) or []
        if not isinstance(raw_blocks, list):
            raw_blocks = [raw_blocks]
        for b in raw_blocks:
            if not b:
                continue
            if isinstance(b, dict) and b.get("type") in ("image", "image_url"):
                url = b.get("url") or b.get("image_url", {}).get("url")
                if url:
                    blocks.append(
                        {
                            "type": "input_image" if role == "user" else "output_image",
                            "image_url": url,
                        }
                    )
            else:
                text = b.get("text") if isinstance(b, dict) else str(b)
                if from_history and from_assistant and not text.strip():
                    continue
                if text.strip():
                    blocks.append(
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": text,
                        }
                    )

        if from_history:
            for f in m.get("files", []):
                if f and f.get("type") in ("image", "image_url"):
                    blocks.append(
                        {
                            "type": "input_image" if role == "user" else "output_image",
                            "image_url": f.get("url") or f.get("image_url", {}).get("url"),
                        }
                    )

        if blocks:
            history.append({"role": role, "content": blocks})

    return history


def pretty_log_block(data: Any, label: str = "") -> str:
    """Return a pretty formatted string for debug logging."""
    try:
        content = json.dumps(data, indent=2, default=str)
    except Exception:
        content = str(data)
    label_line = f"{label} =" if label else ""
    return f"\n{'-' * 40}\n{label_line}\n{content}\n{'-' * 40}"


def sanitize_for_log(obj: Any) -> Any:
    """Return ``obj`` with bulky or sensitive fields replaced by placeholders."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "profile_image_url":
                out[k] = "<profile_image_url>"
            elif k in {"__files__", "files"} and isinstance(v, list):
                out[k] = [
                    {
                        "id": f.get("id"),
                        "name": f.get("name") or f.get("file", {}).get("filename"),
                        "size": f.get("size")
                        or f.get("file", {}).get("meta", {}).get("size"),
                    }
                    for f in v
                    if isinstance(f, dict)
                ]
            elif k == "data" and isinstance(v, dict) and "content" in v:
                out[k] = {"content": "<content>"}
            else:
                out[k] = sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [sanitize_for_log(i) for i in obj]
    return obj


def simplify_user_agent(ua: str) -> str:
    """Return a short ``Browser Version`` string from ``ua``."""
    if not ua:
        return "Unknown"
    patterns = [
        (r"Edg(?:e|A)?/(?P<ver>[0-9.]+)", "Edge"),
        (r"OPR/(?P<ver>[0-9.]+)", "Opera"),
        (r"Chrome/(?P<ver>[0-9.]+)", "Chrome"),
        (r"Firefox/(?P<ver>[0-9.]+)", "Firefox"),
        (r"Version/(?P<ver>[0-9.]+).*Safari/", "Safari"),
        (r"Safari/(?P<ver>[0-9.]+)", "Safari"),
    ]
    for pat, name in patterns:
        m = re.search(pat, ua)
        if m:
            return f"{name} {m.group('ver').split('.')[0]}"
    return ua.split()[0]


async def prepare_payload(
    valves: Pipe.Valves,
    body: dict[str, Any],
    instructions: str,
    tools: list[dict[str, Any]] | None,
    user_email: str | None,
    chat_id: str | None = None,
    chat_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Return the JSON payload for the Responses API."""
    model = (body.get("model") or valves.MODEL_ID.split(",")[0]).split(".", 1)[-1]
    reasoning_effort = body.get("reasoning_effort", "none")
    if model in {"o3-mini-high", "o4-mini-high"}:
        model = model.replace("-high", "")
        reasoning_effort = "high"
    if chat_history is None:
        if chat_id:
            chat_history = await build_chat_history_for_responses_api(chat_id=chat_id)
        else:
            chat_history = await build_chat_history_for_responses_api(messages=body.get("messages", []))

    params = {
        "model": model,
        "instructions": instructions,
        "parallel_tool_calls": valves.PARALLEL_TOOL_CALLS,
        "max_output_tokens": body.get("max_tokens"),
        "temperature": body.get("temperature") or 1.0,
        "top_p": body.get("top_p") or 1.0,
        "user": user_email,
        "text": {"format": {"type": "text"}},
        "truncation": "auto",
        "stream": True,
        "store": True,
        "input": chat_history,
    }

    if tools is not None:
        params["tools"] = tools
        params["tool_choice"] = "auto" if tools else "none"

    if model in REASONING_MODELS and (
        reasoning_effort != "none" or valves.REASON_SUMMARY
    ):
        params["reasoning"] = {}
        if reasoning_effort != "none":
            params["reasoning"]["effort"] = reasoning_effort
        if valves.REASON_SUMMARY:
            params["reasoning"]["summary"] = valves.REASON_SUMMARY

    return params


def parse_responses_sse(event_type: str | None, data: str) -> ResponsesEvent:
    """Parse an SSE data payload into a ``ResponsesEvent`` with minimal overhead."""
    payload = json.loads(data)

    event_type = payload.get("type", event_type or "message")

    item = payload.get("item")
    if isinstance(item, dict):
        item = SimpleNamespace(**item)
    response = payload.get("response")
    if isinstance(response, dict):
        response = SimpleNamespace(**response)
    annotation = payload.get("annotation")
    if isinstance(annotation, dict):
        annotation = SimpleNamespace(**annotation)

    return ResponsesEvent(
        type=event_type,
        delta=payload.get("delta"),
        text=payload.get("text"),
        item_id=payload.get("item_id"),
        item=item,
        response=response,
        annotation=annotation,
        partial_image_index=payload.get("partial_image_index"),
        partial_image_b64=payload.get("partial_image_b64"),
    )


async def execute_responses_tool_calls(
    calls: list[SimpleNamespace],
    registry: dict[str, Any],
    log: logging.Logger | None = None,
) -> list[Any]:
    """Run tool calls asynchronously and return their results."""
    tasks: list[asyncio.Task] = []
    for call in calls:
        entry = registry.get(call.name)
        if entry is None:
            tasks.append(asyncio.create_task(asyncio.sleep(0, result="Tool not found")))
        else:
            args = json.loads(call.arguments or "{}")
            func = entry["callable"]
            if inspect.iscoroutinefunction(func):
                tasks.append(asyncio.create_task(func(**args)))
            else:
                tasks.append(asyncio.to_thread(func, **args))
    try:
        return await asyncio.gather(*tasks)
    except Exception as ex:  # pragma: no cover - log and return error results
        if log:
            log.error("Tool execution failed: %s", ex)
        return [f"Error: {ex}"] * len(tasks)

