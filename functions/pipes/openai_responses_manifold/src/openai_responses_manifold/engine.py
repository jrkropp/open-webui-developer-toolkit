"""Streaming and tool orchestration engine for the Responses manifold."""

from __future__ import annotations

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

from .core import (
    ResponsesBody,
    SessionLogger,
    merge_usage_stats,
    supports,
    wrap_code_block,
    wrap_event_emitter,
)
from .infra import OpenAIResponsesClient, persist_openai_response_items

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

