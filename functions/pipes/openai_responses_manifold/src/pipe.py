"""Open WebUI pipe implementation backed by a modular runner."""

from __future__ import annotations

import asyncio
import datetime
import inspect
import json
import logging
import os
import random
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from time import perf_counter
from typing import Any, Literal, cast

from fastapi import Request
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models
from pydantic import BaseModel, Field

from core import (
    CompletionsBody,
    ResponsesBody,
    SessionLogger,
    merge_usage_stats,
    supports,
    wrap_code_block,
    wrap_event_emitter,
)
from features import build_tools, route_gpt5_auto
from infra import OpenAIResponsesClient, persist_openai_response_items

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

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


class ResponseRunner:
    """Encapsulates the streaming and tool orchestration logic."""

    def __init__(
        self, *, client: OpenAIResponsesClient | None = None, logger: logging.Logger | None = None
    ) -> None:
        self.client = client or OpenAIResponsesClient()
        self.logger = logger or SessionLogger.get_logger(__name__)

    async def stream(
        self,
        body: ResponsesBody,
        valves: Pipe.Valves,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        return await self._run_streaming_loop(body, valves, event_emitter, metadata, tools or {})

    async def nonstreaming(
        self,
        body: ResponsesBody,
        valves: Pipe.Valves,
        event_emitter: EventEmitter,
        metadata: dict[str, Any],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        return await self._run_nonstreaming_loop(body, valves, event_emitter, metadata, tools or {})

    async def run_task_model(
        self,
        body: dict[str, Any],
        valves: Pipe.Valves,
    ) -> str:
        return await self._run_task_model_request(body, valves)

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
        valves: Pipe.Valves,
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
            for _ in range(valves.MAX_FUNCTION_CALL_LOOPS):
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
                    elif event_type == "response.refusal.delta":
                        await event_emitter(
                            {"type": "status", "data": {"description": event.get("delta", "")}}
                        )
                    elif event_type == "response.usage.delta":
                        total_usage = merge_usage_stats(total_usage, event.get("delta", {}))
                        await event_emitter({"type": "usage", "data": total_usage})
                    elif event_type == "response.completed":
                        respond_time = perf_counter() - start_time
                        await self._emit_completion(
                            event_emitter,
                            content="",
                            usage=total_usage,
                            done=True,
                        )
                        completion_emitted = True
                        cancel_thinking()
                        self.logger.info("Completed streaming in %.2f seconds", respond_time)
                        break
                    elif event_type == "response.cancelled":
                        cancel_thinking()
                        break
                    elif event_type == "response.output_item.delta":
                        item = event.get("item", {})
                        item_type = item.get("type", "")
                        item_name = item.get("name", "unnamed_tool")
                        if item_type in ("message",):
                            continue
                        should_persist = False
                        if item_type == "reasoning":
                            should_persist = valves.PERSIST_REASONING_TOKENS == "conversation"
                        elif item_type in ("message", "web_search_call"):
                            should_persist = False
                        else:
                            should_persist = valves.PERSIST_TOOL_RESULTS
                        if should_persist:
                            chat_id = metadata.get("chat_id")
                            message_id = metadata.get("message_id")
                            if isinstance(chat_id, str) and isinstance(message_id, str):
                                hidden_uid_marker = persist_openai_response_items(
                                    chat_id,
                                    message_id,
                                    [item],
                                    openwebui_model,
                                )
                                if hidden_uid_marker:
                                    assistant_message += hidden_uid_marker
                                    await event_emitter(
                                        {
                                            "type": "chat:message",
                                            "data": {"content": assistant_message},
                                        }
                                    )

                        title = f"Running `{item_name}`"
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
                                urls = [
                                    source.get("url") for source in sources if source.get("url")
                                ]
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
                            continue
                        elif item_type == "response_completion":
                            continue
                        elif item_type == "response.output_text.delta":
                            continue
                        elif item_type == "response_tool_call":
                            continue
                        elif item_type == "typing_status":
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
                                        ordinal = ordinal_by_url.setdefault(
                                            source_url, len(ordinal_by_url) + 1
                                        )
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
                    elif event_type == "response.message.completed":
                        continue
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
            if valves.LOG_LEVEL != "INHERIT":
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
        valves: Pipe.Valves,
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
        valves: Pipe.Valves,
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

    async def _emit_notification(
        self,
        event_emitter: EventEmitter | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        if event_emitter is None:
            return
        await event_emitter({"type": "notification", "data": {"type": level, "content": content}})


class Pipe:
    class Valves(BaseModel):
        BASE_URL: str = Field(
            default=(
                (os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"
            ),
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

    class UserValves(BaseModel):
        LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"] = Field(
            default="INHERIT",
            description="Select logging level. 'INHERIT' uses the pipe default.",
        )

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = SessionLogger.get_logger(__name__)
        self.runner = ResponseRunner(logger=self.logger)

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
            return await self.runner.run_task_model(responses_body.model_dump(), valves)

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

        if tools and supports("function_calling", openwebui_model_id):
            model = Models.get_model_by_id(openwebui_model_id)
            if model:
                params = dict(model.params or {})
                if params.get("function_calling") != "native":
                    await self.runner.emit_notification(
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
                self.runner.client,
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                valves=valves,
                tools=tools,
                event_emitter=__event_emitter__,
            )
        elif openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self.runner.emit_notification(
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
                await self.runner.emit_notification(
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
            return await self.runner.stream(
                responses_body, valves, __event_emitter__, __metadata__, tool_registry or {}
            )

        await self.runner.emit_error(
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
