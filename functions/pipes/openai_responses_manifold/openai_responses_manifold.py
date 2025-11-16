"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: OpenAI Responses API Manifold
required_open_webui_version: 0.6.28
requirements: aiohttp, fastapi, pydantic>=2
version: 0.9.7
license: MIT

NOTES - PLEASE READ:
This is an experimental restructure build that modularizes the pipe under src/ and re-bundles it into a single file.
Use the version in the alpha-preview or main branches instead.
"""

from __future__ import annotations

# === core/capabilities.py ===
"""Registry for OpenAI model capabilities and pseudo-model aliases.

To add support for a a new OpenAI model:

* Look up the model in the OpenAI reference: https://platform.openai.com/docs/models
* Add an entry to ``MODEL_FEATURES`` keyed by the canonical API model ID
* (Optional) Add an entry to ``MODEL_ALIASES`` for pseudo-model shortcuts
"""

import re
from copy import deepcopy
from typing import Any

DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
EMPTY_FEATURES: frozenset[str] = frozenset()

# Update MODEL_FEATURES whenever OpenAI adds/removes model capabilities.
MODEL_FEATURES: dict[str, frozenset[str]] = {
    "gpt-5-auto": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5-mini": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5-nano": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-4.1": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-nano": frozenset({"function_calling", "image_gen_tool"}),
    "gpt-4o": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4o-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "o3": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-mini": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-pro": frozenset({"function_calling", "reasoning"}),
    "o4-mini": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool"}),
    "o3-deep-research": frozenset(
        {"function_calling", "reasoning", "reasoning_summary", "deep_research"}
    ),
    "o4-mini-deep-research": frozenset(
        {"function_calling", "reasoning", "reasoning_summary", "deep_research"}
    ),
    "gpt-5-chat-latest": frozenset({"function_calling", "web_search_tool"}),
    "chatgpt-4o-latest": EMPTY_FEATURES,
}

# Add entries to MODEL_ALIASES for any pseudo-model name users can pick.
# Each alias is a preset that points to a base model and optional default params,
# e.g. gpt-5-thinking-high -> gpt-5 with reasoning effort fixed to high.
MODEL_ALIASES: dict[str, dict[str, Any]] = {
    "gpt-5-thinking": {"base_model": "gpt-5"},
    "gpt-5-thinking-minimal": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-high": {"base_model": "gpt-5", "params": {"reasoning": {"effort": "high"}}},
    "gpt-5-thinking-mini": {"base_model": "gpt-5-mini"},
    "gpt-5-thinking-mini-minimal": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-mini-high": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-nano": {"base_model": "gpt-5-nano"},
    "gpt-5-thinking-nano-minimal": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-nano-high": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "high"}},
    },
    "o3-mini-high": {"base_model": "o3-mini", "params": {"reasoning": {"effort": "high"}}},
    "o4-mini-high": {"base_model": "o4-mini", "params": {"reasoning": {"effort": "high"}}},
}

def _is_known_model(model_id: str) -> bool:
    return model_id in MODEL_FEATURES or model_id in MODEL_ALIASES


def _normalize_model_id(model_id: str) -> str:
    """Normalize Open WebUI model identifiers and aliases."""

    raw = (model_id or "").strip().lower()
    no_date = DATE_SUFFIX_RE.sub("", raw)

    if _is_known_model(no_date):
        return no_date

    dot_index = no_date.find(".")
    if dot_index != -1:
        tail = no_date[dot_index + 1 :]
        tail_no_date = DATE_SUFFIX_RE.sub("", tail)
        if _is_known_model(tail_no_date):
            return tail_no_date

    return no_date


def normalize(model_id: str) -> str:
    """Normalize an Open WebUI model identifier by stripping prefixes and dates."""
    return _normalize_model_id(model_id)


def base_model(model_id: str) -> str:
    """Return the canonical base model for the supplied identifier."""
    key = _normalize_model_id(model_id)
    alias = MODEL_ALIASES.get(key, {})
    base = alias.get("base_model")
    return _normalize_model_id(base) if base else key


def alias_defaults(model_id: str) -> dict[str, Any]:
    """Retrieve default parameters defined for the alias, if any."""
    params = MODEL_ALIASES.get(_normalize_model_id(model_id), {}).get("params")
    return deepcopy(params) if params else {}


def features(model_id: str) -> frozenset[str]:
    """Return the feature set associated with the base model."""
    return MODEL_FEATURES.get(base_model(model_id), EMPTY_FEATURES)


def supports(feature: str, model_id: str) -> bool:
    """Determine whether the model supports a given feature."""
    return feature in features(model_id)


__all__ = [
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "alias_defaults",
    "base_model",
    "features",
    "normalize",
    "supports",
]

# === settings.py ===
"""Shared pipe settings and defaults."""

import os
from typing import Literal, cast

from pydantic import BaseModel, Field

_PIPE_LOG_LEVELS: tuple[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], ...] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)
_default_pipe_log_level = (os.getenv("GLOBAL_LOG_LEVEL", "INFO") or "INFO").upper()
if _default_pipe_log_level not in _PIPE_LOG_LEVELS:
    _default_pipe_log_level = "INFO"
DEFAULT_PIPE_LOG_LEVEL = cast(
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], _default_pipe_log_level
)


class PipeValves(BaseModel):
    BASE_URL: str = Field(
        default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
        description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
    )
    API_KEY: str = Field(
        default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
        description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
    )
    MODEL_ID: str = Field(
        default="gpt-5-auto, gpt-5-chat-latest, gpt-5-thinking, gpt-5-thinking-high, gpt-5-thinking-minimal, gpt-4.1-nano, chatgpt-4o-latest, o3, gpt-4o",
        description=(
            "Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. "
            "Supports all official OpenAI model IDs and pseudo IDs (see README.md for full list)."
        ),
    )
    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"] = Field(
        default="disabled",
        description="REQUIRES VERIFIED OPENAI ORG. Visible reasoning summary (auto | concise | detailed | disabled). Works on gpt-5, o3, o4-mini; ignored otherwise. Docs: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
    )
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"] = Field(
        default="disabled",
        description="REQUIRES VERIFIED OPENAI ORG. If verified, highly recommend using 'response' or 'conversation' for best results. If `disabled` (default) = never request encrypted reasoning tokens; if `response` = request tokens so the model can carry reasoning across tool calls for the current response; If `conversation` = also persist tokens for future messages in this chat (higher token usage; quality may vary).",
    )
    PERSIST_TOOL_RESULTS: bool = Field(
        default=True,
        description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
    )
    PARALLEL_TOOL_CALLS: bool = Field(
        default=True,
        description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
    )
    ENABLE_STRICT_TOOL_CALLING: bool = Field(
        default=True,
        description=(
            "When True, converts Open WebUI registry tools to strict JSON Schema for OpenAI tools, "
            "enforcing explicit types, required fields, and disallowing additionalProperties."
        ),
    )
    MAX_TOOL_CALLS: int | None = Field(
        default=None,
        description=(
            "Maximum number of individual tool or function calls the model can make "
            "within a single response. Applies to the total number of calls across "
            "all built-in tools. Further tool-call attempts beyond this limit will be ignored."
        ),
    )
    MAX_FUNCTION_CALL_LOOPS: int = Field(
        default=10,
        description=(
            "Maximum number of full execution cycles (loops) allowed per request. "
            "Each loop involves the model generating one or more function/tool calls, "
            "executing all requested functions, and feeding the results back into the model. "
            "Looping stops when this limit is reached or when the model no longer requests "
            "additional tool or function calls."
        ),
    )
    ENABLE_WEB_SEARCH_TOOL: bool = Field(
        default=False,
        description="Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini, o3, o4-mini, o4-mini-high). NOTE: This appears to disable parallel tool calling. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
    )
    WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
        default="medium",
        description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH_TOOL=True.",
    )
    WEB_SEARCH_USER_LOCATION: str | None = Field(
        default=None,
        description='User location for web search context. Leave blank to disable. Must be in valid JSON format according to OpenAI spec.  E.g., {"type": "approximate","country": "US","city": "San Francisco","region": "CA"}.',
    )
    REMOTE_MCP_SERVERS_JSON: str | None = Field(
        default=None,
        description=(
            "[EXPERIMENTAL] A JSON-encoded list (or single JSON object) defining one or more "
            "remote MCP servers to be automatically attached to each request. This can be useful "
            "for globally enabling tools across all chats."
        ),
    )
    TRUNCATION: Literal["auto", "disabled"] = Field(
        default="auto",
        description="OpenAI truncation strategy. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
    )
    PROMPT_CACHE_KEY: Literal["id", "email"] = Field(
        default="id",
        description="Controls which user identifier is sent in the 'user' parameter to OpenAI.",
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default=DEFAULT_PIPE_LOG_LEVEL,
        description="Select logging level. Recommend INFO or WARNING for production use.",
    )


class PipeUserValves(BaseModel):
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"] = Field(
        default="INHERIT",
        description="Select logging level. 'INHERIT' uses the pipe default.",
    )

# === engine.py ===
"""Streaming and tool orchestration engine for the Responses manifold."""

import asyncio
import datetime
import inspect
import json
import logging
import random
from collections import deque
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Literal

from open_webui.models.chats import Chats


EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class ResponsesEngine:
    """Encapsulates the streaming and tool orchestration logic."""

    def __init__(
        self, *, client: OpenAIResponsesClient | None = None, logger: logging.Logger | None = None
    ) -> None:
        self.client = client or OpenAIResponsesClient()
        self.logger = logger or SessionLogger.get_logger(__name__)

    async def stream(
        self,
        body: ResponsesBody,
        valves: Any,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        return await self._run_streaming_loop(body, valves, event_emitter, metadata, tools or {})

    async def create(
        self,
        body: ResponsesBody,
        valves: Any,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        return await self._run_nonstreaming_loop(body, valves, event_emitter, metadata, tools or {})

    async def nonstreaming(
        self,
        body: ResponsesBody,
        valves: Any,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Backwards-compatible alias for create()."""

        return await self.create(body, valves, event_emitter, metadata, tools)

    async def create_task(
        self,
        body: dict[str, Any],
        valves: Any,
    ) -> str:
        return await self._run_task_model_request(body, valves)

    async def run_task_model(
        self,
        body: dict[str, Any],
        valves: Any,
    ) -> str:
        """Backwards-compatible alias for create_task()."""

        return await self.create_task(body, valves)

    async def emit_notification(
        self,
        event_emitter: EventEmitter | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        await self._emit_notification(event_emitter, content, level=level)

    async def emit_error(
        self,
        event_emitter: EventEmitter | None,
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        show_error_log_citation: bool = False,
        done: bool = False,
    ) -> None:
        await self._emit_error(
            event_emitter,
            error_obj,
            show_error_message=show_error_message,
            show_error_log_citation=show_error_log_citation,
            done=done,
        )

    async def _run_streaming_loop(
        self,
        body: ResponsesBody,
        valves: Any,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]],
    ) -> str:
        tools = tools or {}
        openwebui_model = metadata.get("model", {}).get("id", "")
        assistant_message = ""
        completion_emitted = False
        total_usage: dict[str, Any] = {}
        ordinal_by_url: dict[str, int] = {}
        emitted_citations: list[dict[str, Any]] = []

        thinking_tasks: list[asyncio.Task[Any]] = []
        if supports("reasoning", body.model):

            async def _later(delay: float, msg: str) -> None:
                await asyncio.sleep(delay)
                await event_emitter({"type": "status", "data": {"description": msg}})

            for delay, msg in [
                (0, "Thinking…"),
                (1.5, "Reading the user's question…"),
                (4.0, "Gathering my thoughts…"),
                (6.0, "Exploring possible responses…"),
                (7.0, "Building a plan…"),
            ]:
                thinking_tasks.append(
                    asyncio.create_task(_later(delay + random.uniform(0, 0.5), msg))
                )

        def cancel_thinking() -> None:
            if thinking_tasks:
                for task in thinking_tasks:
                    task.cancel()
                thinking_tasks.clear()

        model_router_result = body.model_router_result
        if model_router_result:
            body.model_router_result = None
            model = model_router_result.get("model", "")
            reasoning_effort = model_router_result.get("reasoning_effort", "")
            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": f"Routing to {model} (effort: {reasoning_effort})\nExplanation: {model_router_result.get('explanation', '')}",
                    },
                }
            )

        start_time = perf_counter()
        error_occurred = False
        try:
            for _ in range(getattr(valves, "MAX_FUNCTION_CALL_LOOPS", 10)):
                final_response: dict[str, Any] | None = None
                async for event in self.client.stream_events(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                ):
                    event_type = event.get("type")
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Received event: %s", event_type)
                        if not str(event_type).endswith(".delta"):
                            self.logger.debug(
                                "Event data: %s", json.dumps(event, indent=2, ensure_ascii=False)
                            )

                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            assistant_message += delta
                            await event_emitter(
                                {"type": "chat:message", "data": {"content": assistant_message}}
                            )
                    elif event_type == "response.output_text.done":
                        final_response = event
                        cancel_thinking()
                    elif event_type == "response.error":
                        cancel_thinking()
                        error_occurred = True
                        await self._emit_error(
                            event_emitter,
                            event.get("error", {}).get("message", "OpenAI returned an error."),
                            show_error_message=True,
                            show_error_log_citation=True,
                        )
                        break
                    elif event_type == "response.completed_with_error":
                        cancel_thinking()
                        error_occurred = True
                        await self._emit_error(
                            event_emitter,
                            event.get("error", {}).get("message", "OpenAI returned an error."),
                            show_error_message=True,
                            show_error_log_citation=True,
                        )
                        break
                    elif event_type == "response.completed":
                        cancel_thinking()
                        break
                    elif event_type == "response.output_text.delta.truncated":
                        continue
                    elif event_type == "response.usage_delta":
                        total_usage = merge_usage_stats(total_usage, event.get("delta", {}))
                    elif event_type == "response.output_items.delta":
                        await self._handle_output_items_delta(
                            event, event_emitter, emitted_citations, ordinal_by_url, metadata
                        )
                    elif event_type == "response.tool_call_arguments.delta":
                        partial_args = event.get("delta", "")
                        if partial_args:
                            event.setdefault("event_metadata", {})
                            event["event_metadata"]["partial_arguments"] = partial_args
                    elif event_type == "response.function_call_arguments.delta":
                        continue
                    elif event_type == "response.function_call_arguments.done":
                        continue
                    elif event_type == "response.function_call_output.delta":
                        continue
                    elif event_type == "response.output_items.done":
                        final_response = event.get("response")
                        cancel_thinking()
                    elif event_type == "response.message.start":
                        continue
                    elif event_type == "response.message.delta":
                        await self._handle_message_delta(
                            event, emitted_citations, ordinal_by_url, event_emitter
                        )
                    elif event_type == "response.message.completed":
                        continue

                if error_occurred or not final_response:
                    break

                if not supports("function_calling", body.model):
                    break
                call_items = final_response.get("output", [])
                tool_calls = [item for item in call_items if item.get("type") == "function_call"]
                if not tool_calls:
                    break
                function_outputs = await self._execute_function_calls(tool_calls, tools)
                if not function_outputs:
                    break
                existing_input = list(body.input) if isinstance(body.input, list) else []
                body.input = existing_input + function_outputs

            respond_time = perf_counter() - start_time
            self.logger.info("Total streaming duration: %.2f seconds", respond_time)

        except Exception as exc:  # pragma: no cover
            cancel_thinking()
            error_occurred = True
            await self._emit_error(
                event_emitter, exc, show_error_message=True, show_error_log_citation=True
            )

        finally:
            if getattr(valves, "LOG_LEVEL", "INHERIT") != "INHERIT":
                session_id = SessionLogger.session_id.get()
                logs = SessionLogger.logs.get(session_id, deque())
                if logs:
                    await self._emit_citation(event_emitter, "\n".join(logs), "Logs")
            if not completion_emitted:
                await self._emit_completion(event_emitter, content="", usage=total_usage, done=True)
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)
            chat_id = metadata.get("chat_id")
            message_id = metadata.get("message_id")
            if chat_id and message_id and emitted_citations:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id, message_id, {"sources": emitted_citations}
                )

        return assistant_message

    async def _run_nonstreaming_loop(
        self,
        body: ResponsesBody,
        valves: Any,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]],
    ) -> str:
        body.stream = True
        wrapped_emitter = wrap_event_emitter(
            event_emitter, suppress_chat_messages=True, suppress_completion=False
        )
        return await self._run_streaming_loop(body, valves, wrapped_emitter, metadata, tools)

    async def _run_task_model_request(
        self,
        body: dict[str, Any],
        valves: Any,
    ) -> str:
        task_body = {
            "model": body.get("model"),
            "instructions": body.get("instructions", ""),
            "input": body.get("input", ""),
            "stream": False,
            "store": False,
        }
        response = await self.client.request(
            task_body, api_key=valves.API_KEY, base_url=valves.BASE_URL
        )
        text_parts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_parts.append(content.get("text", ""))
        return "".join(text_parts)

    @staticmethod
    async def _execute_function_calls(
        calls: list[dict[str, Any]],
        tools: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        def _make_task(call: dict[str, Any]) -> Awaitable[Any]:
            tool_cfg = tools.get(call["name"])
            if not tool_cfg:
                return asyncio.sleep(0, result="Tool not found")
            fn = tool_cfg["callable"]
            args = json.loads(call["arguments"])
            if inspect.iscoroutinefunction(fn):
                return fn(**args)
            return asyncio.to_thread(fn, **args)

        tasks = [_make_task(call) for call in calls]
        results = await asyncio.gather(*tasks)
        return [
            {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": str(result),
            }
            for call, result in zip(calls, results, strict=True)
        ]

    async def _handle_output_items_delta(
        self,
        event: dict[str, Any],
        event_emitter: EventEmitter,
        emitted_citations: list[dict[str, Any]],
        ordinal_by_url: dict[str, int],
        metadata: dict[str, Any],
    ) -> None:
        items = (event.get("output_items", {}) or {}).get("items", [])
        openai_persisted_items: list[dict[str, Any]] = []
        for item in items:
            item_type = item.get("type", "")
            item_name = item.get("name", "")
            if not item_type:
                continue
            if item_type == "openai_response.items":
                openai_persisted_items.append(item)
                continue
            title = ""
            content = ""
            if item_type == "function_call":
                title = f"Running the {item_name} tool…"
                arguments = json.loads(item.get("arguments") or "{}")
                args_formatted = ", ".join(
                    f"{k}={json.dumps(v)}" for k, v in arguments.items()
                )
                content = wrap_code_block(f"{item_name}({args_formatted})", "python")
            elif item_type == "web_search_call":
                action = item.get("action", {}) or {}
                if action.get("type") == "search":
                    query = action.get("query")
                    sources = action.get("sources") or []
                    urls = [source.get("url") for source in sources if source.get("url")]
                    if query:
                        await event_emitter(
                            {
                                "type": "status",
                                "data": {
                                    "action": "web_search_queries_generated",
                                    "description": "Searching",
                                    "queries": [query],
                                    "done": False,
                                },
                            }
                        )
                    if urls:
                        await event_emitter(
                            {
                                "type": "status",
                                "data": {
                                    "action": "web_search",
                                    "description": "Reading through {{count}} sites",
                                    "query": query,
                                    "urls": urls,
                                    "done": False,
                                },
                            }
                        )
                return
            elif item_type in {
                "response_completion",
                "response.output_text.delta",
                "response_tool_call",
                "typing_status",
            }:
                continue
            else:
                title = f"Processing {item_type}"
                content = json.dumps(item, indent=2, ensure_ascii=False)

            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "action": "tool_call",
                        "description": title,
                        "content": content,
                        "done": False,
                    },
                }
            )

        if openai_persisted_items:
            chat_id = metadata.get("chat_id") or ""
            message_id = metadata.get("message_id") or ""
            openwebui_model_id = metadata.get("model", {}).get("id", "") or ""
            hidden_uid_marker = persist_openai_response_items(
                chat_id, message_id, openai_persisted_items, openwebui_model_id
            )
            if hidden_uid_marker:
                await event_emitter(
                    {
                        "type": "chat:message",
                        "data": {
                            "content": hidden_uid_marker,
                            "options": {"persist_history": False},
                        },
                    }
                )

    async def _handle_message_delta(
        self,
        event: dict[str, Any],
        emitted_citations: list[dict[str, Any]],
        ordinal_by_url: dict[str, int],
        event_emitter: EventEmitter,
    ) -> None:
        deltas = event.get("delta", {}).get("content", [])
        for delta in deltas:
            if delta.get("type") == "citations":
                citations = delta.get("citations") or []
                for citation in citations:
                    content_items = citation.get("content") or []
                    for item in content_items:
                        if item.get("type") != "input_text":
                            continue
                        text_value = item.get("text") or ""
                        if not text_value or len(text_value) < 20:
                            continue
                        source_url = citation.get("metadata", {}).get("url")
                        if not source_url:
                            continue
                        ordinal = ordinal_by_url.setdefault(source_url, len(ordinal_by_url) + 1)
                        emitted_citations.append(
                            {
                                "provider": "openai:citation",
                                "id": f"{ordinal}",
                                "title": citation.get("metadata", {}).get("title")
                                or source_url,
                                "link": source_url,
                                "snippet": text_value,
                                "metadata": citation.get("metadata", {}),
                            }
                        )

    async def _emit_error(
        self,
        event_emitter: EventEmitter | None,
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        show_error_log_citation: bool = False,
        done: bool = False,
    ) -> None:
        error_message = str(error_obj)
        self.logger.error("Error: %s", error_message)
        if show_error_message and event_emitter:
            await event_emitter(
                {
                    "type": "chat:completion",
                    "data": {"error": {"message": error_message}, "done": done},
                }
            )
            if show_error_log_citation:
                session_id = SessionLogger.session_id.get()
                logs = SessionLogger.logs.get(session_id, deque())
                if logs:
                    await self._emit_citation(event_emitter, "\n".join(logs), "Error Logs")
                else:
                    self.logger.warning("No debug logs found for session_id %s", session_id)

    async def _emit_citation(
        self,
        event_emitter: EventEmitter | None,
        document: str | list[str],
        source_name: str,
    ) -> None:
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
        event_emitter: EventEmitter | None,
        *,
        content: str | None = "",
        title: str | None = None,
        usage: dict[str, Any] | None = None,
        done: bool = True,
    ) -> None:
        if event_emitter is None:
            return
        await event_emitter(
            {
                "type": "chat:completion",
                "data": {
                    "done": done,
                    "content": content,
                    **({"title": title} if title is not None else {}),
                    **({"usage": usage} if usage is not None else {}),
                },
            }
        )

# === main.py ===
"""Open WebUI pipe implementation that delegates to a Responses engine."""

import asyncio
import datetime
import inspect
import json
import logging
import random
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from time import perf_counter
from typing import Any

from fastapi import Request
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models


class Pipe:
    class Valves(PipeValves):
        """Admin-level valve configuration."""

    class UserValves(PipeUserValves):
        """Per-user valve overrides."""

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = SessionLogger.get_logger(__name__)
        self.engine = ResponsesEngine(logger=self.logger)

    async def pipes(self) -> list[dict[str, str]]:
        model_ids = [
            model_id.strip() for model_id in self.valves.MODEL_ID.split(",") if model_id.strip()
        ]
        return [{"id": model_id, "name": f"OpenAI: {model_id}"} for model_id in model_ids]

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: EventEmitter,
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]] | None,
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: dict[str, Any] | None = None,
        __task_body__: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None] | str | None:
        valves = self._merge_valves(
            self.valves, self.UserValves.model_validate(__user__.get("valves", {}))
        )
        openwebui_model_id = __metadata__.get("model", {}).get("id", "")
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]
        features = __metadata__.get("features", {}).get("openai_responses", {})

        SessionLogger.session_id.set(__metadata__.get("session_id"))
        SessionLogger.log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        if __event_call__:
            await __event_call__(
                {
                    "type": "execute",
                    "data": {
                        "code": """
                (() => {
                if (document.getElementById("owui-status-unclamp")) return "ok";
                const style = document.createElement("style");
                style.id = "owui-status-unclamp";
                style.textContent = `
                    .status-description .line-clamp-1,
                    .status-description .text-base.line-clamp-1,
                    .status-description .text-gray-500.text-base.line-clamp-1 {
                    display: block !important;
                    overflow: visible !important;
                    -webkit-line-clamp: unset !important;
                    -webkit-box-orient: initial !important;
                    white-space: pre-wrap !important;
                    word-break: break-word;
                    }

                    .status-description .text-base::first-line,
                    .status-description .text-gray-500.text-base::first-line {
                    font-weight: 500 !important;
                    }
                `;

                document.head.appendChild(style);
                return "ok";
                })();
                """,
                    },
                }
            )

        completions_body = CompletionsBody.model_validate(body)
        extra_params: dict[str, Any] = {
            "truncation": valves.TRUNCATION,
            "user": user_identifier,
        }
        chat_id_value = __metadata__.get("chat_id")
        if isinstance(chat_id_value, str):
            extra_params["chat_id"] = chat_id_value
        if valves.MAX_TOOL_CALLS is not None:
            extra_params["max_tool_calls"] = valves.MAX_TOOL_CALLS

        responses_body = ResponsesBody.from_completions(
            completions_body=completions_body,
            openwebui_model_id=openwebui_model_id or None,
            **extra_params,
        )

        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self.engine.run_task_model(responses_body.model_dump(), valves)

        __tools__ = await __tools__ if inspect.isawaitable(__tools__) else __tools__
        tool_registry: dict[str, dict[str, Any]] | None = (
            __tools__ if isinstance(__tools__, dict) else None
        )
        tools = build_tools(
            responses_body,
            valves,
            __tools__=tool_registry,
            features=features,
            extra_tools=getattr(completions_body, "extra_tools", None),
        )

        if tools and supports("function_calling", responses_body.model):
            model = Models.get_model_by_id(openwebui_model_id)
            if model:
                params = dict(model.params or {})
                if params.get("function_calling") != "native":
                    await self.engine.emit_notification(
                        __event_emitter__,
                        content=f"Enabling native function calling for model: {openwebui_model_id}. Please re-run your query.",
                        level="info",
                    )
                    params["function_calling"] = "native"
                    form_data = model.model_dump()
                    form_data["params"] = params
                    Models.update_model_by_id(openwebui_model_id, ModelForm(**form_data))

        if openwebui_model_id.endswith(".gpt-5-auto-dev"):
            responses_body = await route_gpt5_auto(
                self.engine.client,
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                valves=valves,
                tools=tools,
                event_emitter=__event_emitter__,
            )
        elif openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self.engine.emit_notification(
                __event_emitter__,
                content="Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast).",
                level="warning",
            )

        if supports("function_calling", responses_body.model):
            responses_body.tools = tools

        if (
            supports("reasoning_summary", responses_body.model)
            and valves.REASONING_SUMMARY != "disabled"
        ):
            reasoning_params = dict(responses_body.reasoning or {})
            reasoning_params["summary"] = valves.REASONING_SUMMARY
            responses_body.reasoning = reasoning_params

        if (
            supports("reasoning", responses_body.model)
            and valves.PERSIST_REASONING_TOKENS != "disabled"
            and responses_body.store is False
        ):
            responses_body.include = responses_body.include or []
            if "reasoning.encrypted_content" not in responses_body.include:
                responses_body.include.append("reasoning.encrypted_content")

        if any(
            isinstance(tool, dict) and tool.get("type") == "web_search"
            for tool in (responses_body.tools or [])
        ):
            if supports("web_search_tool", responses_body.model):
                responses_body.include = list(responses_body.include or [])
                if "web_search_call.action.sources" not in responses_body.include:
                    responses_body.include.append("web_search_call.action.sources")

        input_items = responses_body.input if isinstance(responses_body.input, list) else None
        if input_items:
            last_item = input_items[-1]
            content_blocks = last_item.get("content") if last_item.get("role") == "user" else None
            first_block = (
                content_blocks[0] if isinstance(content_blocks, list) and content_blocks else {}
            )
            last_user_text = (first_block.get("text") or "").strip().lower()

            directive_to_verbosity = {"add details": "high", "more concise": "low"}
            verbosity_value = directive_to_verbosity.get(last_user_text)

            if verbosity_value and supports("verbosity", responses_body.model):
                current_text_params = dict(getattr(responses_body, "text", {}) or {})
                current_text_params["verbosity"] = verbosity_value
                responses_body.text = current_text_params
                input_items.pop()
                await self.engine.emit_notification(
                    __event_emitter__,
                    f"Regenerating with verbosity set to {verbosity_value}.",
                    level="info",
                )
                self.logger.debug(
                    "Set text.verbosity=%s based on regenerate directive '%s'",
                    verbosity_value,
                    last_user_text,
                )

        self.logger.debug(
            "Transformed ResponsesBody: %s",
            json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False),
        )

        if responses_body.stream:
            return await self.engine.stream(
                responses_body, valves, __event_emitter__, __metadata__, tool_registry or {}
            )

        await self.engine.emit_error(
            __event_emitter__,
            "Non-streaming is currently not supported with the OpenAI Responses Manifold.  Please enable streaming and try again",
            show_error_message=True,
        )
        return ""

    def _merge_valves(
        self, global_valves: Pipe.Valves, user_valves: Pipe.UserValves
    ) -> Pipe.Valves:
        if not user_valves:
            return global_valves
        update = {
            key: value
            for key, value in user_valves.model_dump().items()
            if value is not None and str(value).lower() != "inherit"
        }
        return global_valves.model_copy(update=update)

# === core/markers.py ===
"""Helpers for encoding/decoding hidden response markers."""

import re
import secrets
from typing import Any

ULID_LENGTH = 16
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SENTINEL = "[openai_responses:v2:"
_MARKER_RE = re.compile(
    r"\[openai_responses:v2:(?P<kind>[a-z0-9_]{2,30}):(?P<ulid>[A-Z0-9]{16})(?:\?(?P<query>[^\]]+))?\]:\s*#",
    re.I,
)


def generate_item_id() -> str:
    """Generate a short ULID-like identifier."""

    return "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))


def _qs(metadata: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in metadata.items()) if metadata else ""


def _parse_qs(query: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in query.split("&")) if query else {}


def create_marker(
    item_type: str,
    *,
    ulid: str | None = None,
    model_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """Create a bare marker payload (without the wrapping newlines)."""

    if not re.fullmatch(r"[a-z0-9_]{2,30}", item_type):
        raise ValueError("item_type must be 2-30 chars of [a-z0-9_]")

    meta = {**(metadata or {})}
    if model_id:
        meta["model"] = model_id

    base = f"openai_responses:v2:{item_type}:{ulid or generate_item_id()}"
    return f"{base}?{_qs(meta)}" if meta else base


def wrap_marker(marker: str) -> str:
    """Wrap a marker string in an empty markdown link."""

    return f"\n[{marker}]: #\n"


def contains_marker(text: str) -> bool:
    """Return True if the sentinel substring is present."""

    return _SENTINEL in text


def parse_marker(marker: str) -> dict[str, Any]:
    """Parse a raw marker string back into its components."""

    if not marker.startswith("openai_responses:v2:"):
        raise ValueError("not a v2 marker")
    _, _, kind, rest = marker.split(":", 3)
    uid, _, query = rest.partition("?")
    return {"version": "v2", "item_type": kind, "ulid": uid, "metadata": _parse_qs(query)}


def extract_markers(text: str, *, parsed: bool = False) -> list[Any]:
    """Extract hidden markers from the assistant text."""

    found: list[Any] = []
    for match in _MARKER_RE.finditer(text):
        raw = f"openai_responses:v2:{match.group('kind')}:{match.group('ulid')}"
        if match.group("query"):
            raw += f"?{match.group('query')}"
        found.append(parse_marker(raw) if parsed else raw)
    return found


def split_text_by_markers(text: str) -> list[dict[str, str]]:
    """Split text into a list of literal segments and marker segments."""

    segments: list[dict[str, str]] = []
    last = 0
    for match in _MARKER_RE.finditer(text):
        if match.start() > last:
            segments.append({"type": "text", "text": text[last : match.start()]})
        raw = f"openai_responses:v2:{match.group('kind')}:{match.group('ulid')}"
        if match.group("query"):
            raw += f"?{match.group('query')}"
        segments.append({"type": "marker", "marker": raw})
        last = match.end()
    if last < len(text):
        segments.append({"type": "text", "text": text[last:]})
    return segments

# === core/session_logger.py ===
"""Request-scoped logger used throughout the manifold."""

import logging
import sys
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import ClassVar


class SessionLogger:
    """Per-request logger storing log lines in memory and stdout."""

    session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
    log_level: ContextVar[int] = ContextVar("log_level", default=logging.INFO)
    logs: ClassVar[defaultdict[str | None, deque[str]]] = defaultdict(lambda: deque(maxlen=2000))

    @classmethod
    def get_logger(cls, name: str = __name__) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        def _filter(record: logging.LogRecord) -> bool:
            record.session_id = cls.session_id.get()
            return record.levelno >= cls.log_level.get()

        logger.addFilter(_filter)

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s"))
        logger.addHandler(console)

        class _MemoryHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                session = getattr(record, "session_id", None)
                if session:
                    SessionLogger.logs[session].append(self.format(record))

        mem_handler = _MemoryHandler()
        mem_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(mem_handler)

        return logger

# === core/utils.py ===
"""General-purpose helpers shared across modules."""

from collections.abc import Awaitable, Callable
from typing import Any


def wrap_event_emitter(
    emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
    *,
    suppress_chat_messages: bool = False,
    suppress_completion: bool = False,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Wrap the given event emitter and optionally suppress certain event types."""

    if emitter is None:

        async def _noop(_: dict[str, Any]) -> None:
            return

        return _noop

    async def _wrapped(event: dict[str, Any]) -> None:
        event_type = (event or {}).get("type")
        if suppress_chat_messages and event_type == "chat:message":
            return
        if suppress_completion and event_type == "chat:completion":
            return
        await emitter(event)

    return _wrapped


def merge_usage_stats(total: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested usage dicts."""

    for key, value in new.items():
        if isinstance(value, dict):
            total[key] = merge_usage_stats(total.get(key, {}), value)
        elif isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
        elif value is not None:
            total[key] = value
    return total


def wrap_code_block(text: str, language: str = "python") -> str:
    """Wrap a block of text in fenced markdown code."""

    return f"```{language}\n{text}\n```"

# === core/models.py ===
"""Pydantic request/response models and transformations."""

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, model_validator


logger = logging.getLogger(__name__)


class CompletionsBody(BaseModel):
    """Request body compatible with OpenAI's legacy Completions API."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False

    class Config:
        extra = "allow"


class ResponsesBody(BaseModel):
    """Request body for the OpenAI Responses API."""

    model: str
    input: str | list[dict[str, Any]]
    instructions: str | None = ""
    stream: bool = False
    store: bool | None = False
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    truncation: Literal["auto", "disabled"] | None = None
    reasoning: dict[str, Any] | None = None
    parallel_tool_calls: bool | None = True
    user: str | None = None
    tool_choice: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    include: list[str] | None = None
    text: dict[str, Any] | None = None
    model_router_result: dict[str, Any] | None = None

    class Config:
        extra = "allow"

    @model_validator(mode="after")
    def _apply_alias_defaults(self) -> ResponsesBody:
        """Normalize alias defaults so callers get a canonical model id."""

        orig_model = self.model or ""
        canonical_model = base_model(orig_model)
        defaults = alias_defaults(orig_model) or {}

        if canonical_model == orig_model and not defaults:
            return self

        data = json.loads(self.model_dump_json(exclude_none=False))
        data["model"] = canonical_model

        def _deep_overlay(dst: dict, src: dict) -> dict:
            for key, value in src.items():
                if isinstance(value, dict):
                    node = dst.get(key)
                    if isinstance(node, dict):
                        _deep_overlay(node, value)
                    else:
                        dst[key] = json.loads(json.dumps(value))
                elif isinstance(value, list):
                    existing = dst.get(key)
                    if isinstance(existing, list):
                        seen: set[tuple[str, str]] = set()
                        merged: list[Any] = []

                        def _make_key(item: Any) -> tuple[str, str]:
                            try:
                                return ("json", json.dumps(item, sort_keys=True))
                            except Exception:  # pragma: no cover - fallback
                                return ("id", str(id(item)))

                        for item in existing + value:
                            key_tuple = _make_key(item)
                            if key_tuple not in seen:
                                seen.add(key_tuple)
                                merged.append(item)
                        dst[key] = merged
                    else:
                        dst[key] = list(value)
                else:
                    dst[key] = value
            return dst

        if defaults:
            _deep_overlay(data, defaults)

        for key, value in data.items():
            setattr(self, key, value)
        return self

    @staticmethod
    def transform_owui_tools(
        __tools__: dict[str, dict] | None, *, strict: bool = False
    ) -> list[dict]:
        """Convert Open WebUI tool registry entries into OpenAI tool specs."""

        if not __tools__:
            return []

        tools: list[dict] = []
        for item in __tools__.values():
            spec = item.get("spec") or {}
            name = spec.get("name")
            if not name:
                continue

            params = spec.get("parameters") or {"type": "object", "properties": {}}
            tool = {
                "type": "function",
                "name": name,
                "description": spec.get("description") or name,
                "parameters": ResponsesBody._strictify_schema(params) if strict else params,
            }
            if strict:
                tool["strict"] = True
            tools.append(tool)
        return tools

    @staticmethod
    def _strictify_schema(schema: Any) -> dict:
        """Strictify JSON schema nodes for OpenAI's Responses API."""

        if not isinstance(schema, dict):
            return {}

        data = json.loads(json.dumps(schema))

        def _enforce(node: dict) -> None:
            node_type = node.get("type")
            is_object = (
                node_type == "object"
                or (isinstance(node_type, list) and "object" in node_type)
                or "properties" in node
            )
            if is_object:
                props = node.setdefault("properties", {})
                if not isinstance(props, dict):
                    props = {}
                    node["properties"] = props

                original_required = set(node.get("required") or [])
                node["additionalProperties"] = False
                node["required"] = list(props.keys())

                for name, prop in props.items():
                    if not isinstance(prop, dict):
                        continue
                    if name not in original_required:
                        ptype = prop.get("type")
                        if isinstance(ptype, str) and ptype != "null":
                            prop["type"] = [ptype, "null"]
                        elif isinstance(ptype, list) and "null" not in ptype:
                            prop["type"] = [*ptype, "null"]
                    _enforce(prop)

            items = node.get("items")
            if isinstance(items, dict):
                _enforce(items)
            elif isinstance(items, list):
                for entry in items:
                    if isinstance(entry, dict):
                        _enforce(entry)

            for key in ("anyOf", "oneOf"):
                branches = node.get(key)
                if isinstance(branches, list):
                    for branch in branches:
                        if isinstance(branch, dict):
                            _enforce(branch)

        _enforce(data)
        return data

    @staticmethod
    def _build_mcp_tools(mcp_json: str) -> list[dict]:
        """Build MCP tool descriptors from the valve JSON."""

        if not mcp_json:
            return []

        def _coerce_to_list(value: Any) -> list[dict]:
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
            return []

        try:
            decoded = json.loads(mcp_json)
        except Exception as exc:  # pragma: no cover - valved bug
            logger.warning("REMOTE_MCP_SERVERS_JSON is not valid JSON: %s", exc)
            return []

        tools: list[dict] = []
        for item in _coerce_to_list(decoded):
            tool = {
                "type": "mcp",
                "server_label": item.get("server_label"),
                "server_url": item.get("server_url"),
            }
            for key in (
                "model_preference",
                "client_capabilities",
                "require_approval",
                "allowed_tools",
            ):
                if key in item:
                    tool[key] = item[key]
            tools.append(tool)
        return tools

    @staticmethod
    def transform_messages_to_input(
        messages: list[dict[str, Any]],
        chat_id: str | None = None,
        openwebui_model_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert Open WebUI chat messages into Responses API input items."""

        required_item_ids: set[str] = set()
        if chat_id and openwebui_model_id:
            for message in messages:
                if (
                    message.get("role") == "assistant"
                    and message.get("content")
                    and contains_marker(message["content"])
                ):
                    for marker in extract_markers(message["content"], parsed=True):
                        required_item_ids.add(marker["ulid"])

        items_lookup: dict[str, dict[str, Any]] = {}
        if chat_id and openwebui_model_id and required_item_ids:
            items_lookup = fetch_openai_response_items(
                chat_id,
                list(required_item_ids),
                openwebui_model_id=openwebui_model_id,
            )

        openai_input: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")

            if role == "system":
                continue

            if role == "user":
                blocks = message.get("content") or []
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]

                transform = {
                    "text": lambda block: {"type": "input_text", "text": block.get("text", "")},
                    "image_url": lambda block: {
                        "type": "input_image",
                        "image_url": block.get("image_url", {}).get("url"),
                    },
                    "input_file": lambda block: {
                        "type": "input_file",
                        "file_id": block.get("file_id"),
                    },
                }
                openai_input.append(
                    {
                        "role": "user",
                        "content": [
                            transform.get(block.get("type"), lambda b: b)(block)
                            for block in blocks
                            if block
                        ],
                    }
                )
                continue

            if role == "developer":
                openai_input.append({"role": "developer", "content": content})
                continue

            if contains_marker(content):
                for segment in split_text_by_markers(content):
                    if segment["type"] == "marker":
                        marker = parse_marker(segment["marker"])
                        item = items_lookup.get(marker["ulid"])
                        if item is not None:
                            openai_input.append(item)
                    elif segment["type"] == "text" and segment["text"].strip():
                        openai_input.append(
                            {
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": segment["text"].strip()}
                                ],
                            }
                        )
            elif content:
                openai_input.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                )

        return openai_input

    @classmethod
    def from_completions(
        ResponsesBody,
        completions_body: CompletionsBody,
        chat_id: str | None = None,
        openwebui_model_id: str | None = None,
        **extra_params: Any,
    ) -> ResponsesBody:
        """Convert a Completions request payload into Responses format."""

        completions_dict = completions_body.model_dump(exclude_none=True)

        unsupported_fields = {
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "logit_bias",
            "logprobs",
            "top_logprobs",
            "n",
            "stop",
            "response_format",
            "suffix",
            "stream_options",
            "audio",
            "function_call",
            "functions",
            "reasoning_effort",
            "max_tokens",
            "tools",
            "extra_tools",
        }

        sanitized_params = {}
        for key, value in completions_dict.items():
            if key in unsupported_fields:
                logger.warning("Dropping unsupported parameter: %s", key)
                continue
            sanitized_params[key] = value

        if "max_tokens" in completions_dict:
            sanitized_params["max_output_tokens"] = completions_dict["max_tokens"]

        effort = completions_dict.get("reasoning_effort")
        if effort:
            reasoning = sanitized_params.get("reasoning", {})
            reasoning.setdefault("effort", effort)
            sanitized_params["reasoning"] = reasoning

        instructions = next(
            (
                msg["content"]
                for msg in reversed(completions_dict.get("messages", []))
                if msg["role"] == "system"
            ),
            None,
        )
        if instructions:
            sanitized_params["instructions"] = instructions

        if "messages" in completions_dict:
            sanitized_params.pop("messages", None)
            sanitized_params["input"] = ResponsesBody.transform_messages_to_input(
                completions_dict.get("messages", []),
                chat_id=chat_id,
                openwebui_model_id=openwebui_model_id,
            )

        return ResponsesBody(
            **sanitized_params,
            **extra_params,
        )

# === infra/persistence.py ===
"""Persistence helpers for storing auxiliary Responses items in Open WebUI."""

import datetime
from typing import Any

from open_webui.models.chats import Chats


def persist_openai_response_items(
    chat_id: str,
    message_id: str,
    items: list[dict[str, Any]],
    openwebui_model_id: str,
) -> str:
    """Persist response items and return concatenated hidden markers."""

    if not items:
        return ""

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return ""

    pipe_root = chat_model.chat.setdefault("openai_responses_pipe", {"__v": 3})
    items_store = pipe_root.setdefault("items", {})
    messages_index = pipe_root.setdefault("messages_index", {})

    message_bucket = messages_index.setdefault(
        message_id,
        {"role": "assistant", "done": True, "item_ids": []},
    )

    now = int(datetime.datetime.utcnow().timestamp())
    hidden_markers: list[str] = []
    for payload in items:
        item_id = generate_item_id()
        items_store[item_id] = {
            "model": openwebui_model_id,
            "created_at": now,
            "payload": payload,
            "message_id": message_id,
        }
        message_bucket["item_ids"].append(item_id)
        hidden_markers.append(
            wrap_marker(create_marker(payload.get("type", "unknown"), ulid=item_id))
        )

    Chats.update_chat_by_id(chat_id, chat_model.chat)
    return "".join(hidden_markers)


def fetch_openai_response_items(
    chat_id: str,
    item_ids: list[str],
    *,
    openwebui_model_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch persisted items by ULID, optionally filtering by model id."""

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return {}

    items_store = chat_model.chat.get("openai_responses_pipe", {}).get("items", {})
    lookup: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        item = items_store.get(item_id)
        if not item:
            continue
        if openwebui_model_id and item.get("model", "") != openwebui_model_id:
            continue
        lookup[item_id] = item.get("payload", {})
    return lookup

# === infra/client.py ===
"""HTTP client for interacting with the OpenAI Responses endpoint."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp


class OpenAIResponsesClient:
    """Thin wrapper around ``aiohttp`` that streams Responses API events."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._logger = logging.getLogger(__name__)

    async def stream_events(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE events as soon as they arrive."""

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"

        buf = bytearray()
        async with session.post(url, json=request_body, headers=headers) as resp:
            resp.raise_for_status()

            async for chunk in resp.content.iter_chunked(4096):
                buf.extend(chunk)
                start_idx = 0
                while True:
                    newline_idx = buf.find(b"\n", start_idx)
                    if newline_idx == -1:
                        break
                    line = buf[start_idx:newline_idx].strip()
                    start_idx = newline_idx + 1
                    if not line or line.startswith(b":") or not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        return
                    yield json.loads(payload.decode("utf-8"))
                if start_idx > 0:
                    del buf[:start_idx]

    async def request(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> dict[str, Any]:
        """Send a non-streaming Responses API request."""

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"
        async with session.post(url, json=request_body, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self) -> None:
        """Close the underlying client session."""

        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_or_init_http_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            self._logger.debug("Reusing existing aiohttp session")
            return self._session

        connector = aiohttp.TCPConnector(
            limit=50,
            limit_per_host=10,
            keepalive_timeout=75,
            ttl_dns_cache=300,
        )
        timeout = aiohttp.ClientTimeout(
            connect=30,
            sock_connect=30,
            sock_read=3600,
        )
        self._logger.debug("Creating new aiohttp session")
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            json_serialize=json.dumps,
        )
        return self._session

# === features/tools.py ===
"""Helpers for constructing OpenAI tool payloads."""

import json
import logging
from typing import Any


logger = logging.getLogger(__name__)


def build_tools(
    responses_body: ResponsesBody,
    valves: Any,
    __tools__: dict[str, Any] | None = None,
    *,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI Responses-API tool spec list for this request."""

    features = features or {}
    if not supports("function_calling", responses_body.model):
        return []

    tools: list[dict[str, Any]] = []

    if isinstance(__tools__, dict) and __tools__:
        tools.extend(
            ResponsesBody.transform_owui_tools(
                __tools__,
                strict=getattr(valves, "ENABLE_STRICT_TOOL_CALLING", False),
            )
        )

    allow_web = (
        supports("web_search_tool", responses_body.model)
        and (getattr(valves, "ENABLE_WEB_SEARCH_TOOL", False) or features.get("web_search", False))
        and ((responses_body.reasoning or {}).get("effort", "").lower() != "minimal")
    )
    if allow_web:
        web_search_tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": getattr(valves, "WEB_SEARCH_CONTEXT_SIZE", "medium"),
        }
        user_location = getattr(valves, "WEB_SEARCH_USER_LOCATION", None)
        if user_location:
            try:
                web_search_tool["user_location"] = json.loads(user_location)
            except Exception as exc:
                logger.warning("WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring: %s", exc)
        tools.append(web_search_tool)

    remote_mcp = getattr(valves, "REMOTE_MCP_SERVERS_JSON", None)
    if remote_mcp:
        tools.extend(ResponsesBody._build_mcp_tools(remote_mcp))

    if isinstance(extra_tools, list) and extra_tools:
        tools.extend(extra_tools)

    return _dedupe_tools(tools)


def _dedupe_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Deduplicate tool entries by (type, name) identity."""

    if not tools:
        return []

    seen: dict[tuple[str, str | None], dict[str, Any]] = {}

    for tool in tools:
        tool_type = tool.get("type")
        if not isinstance(tool_type, str):
            continue
        identifier: str | None = None
        if tool_type == "function":
            name = tool.get("name")
            if isinstance(name, str):
                identifier = name
        seen[(tool_type, identifier)] = tool

    return list(seen.values())

# === features/router.py ===
"""Model routing helpers (e.g., GPT-5 auto selection)."""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any


logger = logging.getLogger(__name__)


async def route_gpt5_auto(
    client: OpenAIResponsesClient,
    router_model: str,
    responses_body: ResponsesBody,
    valves: Any,
    tools: list[dict[str, Any]],
    event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> ResponsesBody:
    """Route GPT-5 auto requests via a lightweight helper model."""

    _ = tools, event_emitter, router_model  # not yet used but kept for parity
    router_body = {
        "model": "gpt-5-mini",
        "reasoning": {"effort": "minimal"},
        "instructions": '# Role and Objective\nServe as a **routing helper** for selecting the most appropriate GPT-5 model for user messages, evaluating tool necessity and task complexity.\n\n---\n\n# Instructions\n- If a message may require the use of **any available tool**, select a model with **function calling** capabilities. If **web search** is required, you may only choose **low, medium or high** reasoning, not minimal.\n- When tools are not necessary, favor the **fastest** or **most capable** model according to the complexity of the request.\n\n---\n\n# Available Models and Capabilities\n## Models\n\n- **gpt-5-chat-latest**\n  - Fast, general-purpose, and creative.\n  - Best for writing, drafting, and chat-based interactions.\n  - ⚠️ Does **not** support tool calling—select only when tools are not required.\n\n- **gpt-5-mini**\n  - Lightweight, supports tool usage, and is rapidly responsive.\n  - Suited for **simple tasks that may use tools** but don\'t demand extensive reasoning.\n  - ✅ Function calling supported—offers a strong balance between speed and utility.\n\n- **gpt-5**\n  - Strong at reasoning and complex, multi-step analysis.\n  - Designed for **complex or deeply analytical tasks**.\n  - ✅ Supports function calling and advanced operations—choose for tool-reliant or high-complexity reasoning needs.\n\n---\n\n# Routing Checklist\n- Assess whether tool integration could improve the response.\n- Evaluate how much reasoning or problem-solving is required.\n- Match model to requirements:\n  - No tool usage required → use `gpt-5-chat-latest`\n  - Tools required, simple task → use `gpt-5-mini`\n  - Tools required, complex task → use `gpt-5`\n- When in doubt, prioritize a tool-capable model (prefer `gpt-5`).\n- Ask for more information if requirements are ambiguous.\n\n---\n\n# Output Format\nRespond only with a JSON object containing your model selection and a concise explanation. If the requirements are unclear, include an appropriate error message in the JSON response.\n\n---\n\n# Examples\n- **What\'s the weather in Vancouver right now?**\n  ```json\n  {\n    "model": "gpt-5-mini",\n    "explanation": "Quick tool lookup; simple enough for a fast model."\n  }\n  ```\n\n- **Compare the newest M3 laptops and cite sources.**\n  ```json\n  {\n    "model": "gpt-5",\n    "explanation": "Research and synthesis with tools requires reasoning depth."\n  }\n  ```\n\n- **Summarize this email draft and make it more formal.**\n  ```json\n  {\n    "model": "gpt-5-chat-latest",\n    "explanation": "Polishing text only; no tools needed."\n  }\n  ```\n\n- **Summarize this uploaded PDF into bullet points.**\n  ```json\n  {\n    "model": "gpt-5",\n    "explanation": "Document parsing may require tools; complex enough for gpt-5."\n  }\n  ```\n\n- **Translate this paragraph into Spanish.**\n  ```json\n  {\n    "model": "gpt-5-chat-latest",\n    "explanation": "Simple translation; tools not required."\n  }\n  ```\n\n- **List my upcoming meetings tomorrow.**\n  ```json\n  {\n    "model": "gpt-5-mini",\n    "explanation": "Calendar tool lookup is simple; mini is efficient."\n  }\n  ```',
        "input": responses_body.input,
        "prompt_cache_key": "openai_responses_gpt5-router",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "gpt5_router",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "enum": ["gpt-5-chat-latest", "gpt-5", "gpt-5-mini"],
                        },
                        "reasoning_effort": {
                            "type": "string",
                            "enum": ["minimal", "low", "medium", "high"],
                        },
                        "explanation": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 500,
                        },
                    },
                    "required": ["model", "explanation", "reasoning_effort"],
                    "additionalProperties": False,
                },
                "verbosity": "medium",
            },
        },
    }

    try:
        response = await client.request(
            router_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("GPT-5 router request failed: %s", exc)
        return responses_body

    try:
        text = next(
            (
                block["text"]
                for output in reversed(response["output"])
                if output["type"] == "message"
                for block in output["content"]
                if block["type"] == "output_text"
            ),
            "",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Router response missing expected fields: %s; payload keys=%s",
            exc,
            list(response.keys()),
        )
        return responses_body

    try:
        router_json: dict[str, Any] = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        router_json = (
            json.loads(text[start : end + 1]) if start != -1 and end != -1 and end > start else {}
        )

    if router_json:
        model_choice = router_json.get("model")
        if isinstance(model_choice, str):
            responses_body.model = model_choice
        if supports("reasoning", responses_body.model):
            reasoning = dict(responses_body.reasoning or {})
            effort = router_json.get("reasoning_effort")
            if isinstance(effort, str):
                reasoning["effort"] = effort
            responses_body.reasoning = reasoning
        responses_body.model_router_result = router_json

    return responses_body
