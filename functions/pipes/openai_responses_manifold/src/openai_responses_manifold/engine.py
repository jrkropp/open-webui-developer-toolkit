"""Streaming and tool orchestration engine for the Responses manifold."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Literal

from open_webui.models.chats import Chats

from .core.api_models import ResponsesBody
from .core.capabilities import supports
from .infra import ItemStore, OpenAIResponsesClient
from .services.history import HistoryPersistence
from .services.tools import execute_tool_calls
from .utils import (
    SessionLogger,
    clear_session_logs,
    current_session_id,
    emit_chat_message,
    emit_citation,
    emit_completion,
    emit_error,
    emit_status,
    get_session_logs,
    merge_usage_stats,
    truncate_for_log,
    wrap_code_block,
    wrap_event_emitter,
)

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class ResponsesEngine:
    """Encapsulates the streaming and tool orchestration logic."""

    def __init__(
        self,
        *,
        client: OpenAIResponsesClient | None = None,
        item_store: ItemStore | None = None,
        history_persistence: HistoryPersistence | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client or OpenAIResponsesClient()
        self.store = item_store or ItemStore()
        self.history_persistence = history_persistence or HistoryPersistence(self.store)
        self.logger = logger or SessionLogger.get_logger(__name__)

    async def run_streaming_turn(
        self,
        body: ResponsesBody,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitter,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        tool_registry = tool_registry or {}
        assistant_message = ""
        total_usage: dict[str, Any] = {}
        ordinal_by_url: dict[str, int] = {}
        emitted_citations: list[dict[str, Any]] = []
        openwebui_model = metadata.get("model", {}).get("id", "")

        thinking_tasks = self._schedule_reasoning_statuses(body, event_emitter)
        final_response: dict[str, Any] | None = None

        model_router_result = body.model_router_result
        if model_router_result:
            body.model_router_result = None
            explanation = model_router_result.get("explanation", "")
            await emit_status(
                event_emitter,
                f"Routing to {model_router_result.get('model')} (effort: {model_router_result.get('reasoning_effort')})\nExplanation: {explanation}",
            )

        start_time = perf_counter()
        error_occurred = False
        try:
            max_loops = getattr(valves, "MAX_FUNCTION_CALL_LOOPS", 10)
            for _ in range(max_loops):
                final_response = None
                async for event in self.client.stream(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                ):
                    event_type = event.get("type")
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Received event: %s", event_type)
                        if not str(event_type).endswith(".delta"):
                            payload, truncated = truncate_for_log(
                                json.dumps(event, ensure_ascii=False), limit=3000
                            )
                            suffix = " (truncated)" if truncated else ""
                            self.logger.debug("Event data%s: %s", suffix, payload)

                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            assistant_message += delta
                            await emit_chat_message(event_emitter, assistant_message)
                    elif event_type == "response.output_text.done":
                        final_response = event
                        await self._cancel_tasks(thinking_tasks)
                    elif event_type == "response.error":
                        await self._cancel_tasks(thinking_tasks)
                        error_occurred = True
                        await self._handle_stream_error(
                            event_emitter,
                            event.get("error", {}).get("message", "OpenAI returned an error."),
                        )
                        break
                    elif event_type == "response.completed_with_error":
                        await self._cancel_tasks(thinking_tasks)
                        error_occurred = True
                        await self._handle_stream_error(
                            event_emitter,
                            event.get("error", {}).get("message", "OpenAI returned an error."),
                        )
                        break
                    elif event_type == "response.completed":
                        final_response = event.get("response") or final_response or event
                        await self._cancel_tasks(thinking_tasks)
                        break
                    elif event_type == "response.output_text.delta.truncated":
                        continue
                    elif event_type == "response.usage_delta":
                        total_usage = merge_usage_stats(total_usage, event.get("delta", {}))
                    elif event_type == "response.output_items.delta":
                        await self._handle_output_items_delta(
                            event,
                            event_emitter,
                            emitted_citations,
                            ordinal_by_url,
                            metadata,
                        )
                    elif event_type == "response.tool_call_arguments.delta":
                        partial_args = event.get("delta", "")
                        if partial_args:
                            event.setdefault("event_metadata", {})
                            event["event_metadata"]["partial_arguments"] = partial_args
                    elif event_type == "response.output_items.done":
                        final_response = event.get("response") or final_response or event
                        await self._cancel_tasks(thinking_tasks)
                    elif event_type == "response.message.delta":
                        await self._handle_message_delta(event, emitted_citations, ordinal_by_url)

                if final_response and not total_usage:
                    usage_from_response = self._extract_usage_from_final_response(
                        final_response
                    )
                    if usage_from_response:
                        total_usage = merge_usage_stats(total_usage, usage_from_response)

                if error_occurred or not final_response:
                    break

                if not supports("function_calling", body.model):
                    break
                call_items = (final_response or {}).get("output", [])
                tool_calls = [item for item in call_items if item.get("type") == "function_call"]
                if not tool_calls:
                    break
                function_outputs = await execute_tool_calls(tool_calls, tool_registry)
                if not function_outputs:
                    break
                existing_input = list(body.input) if isinstance(body.input, list) else []
                body.input = existing_input + function_outputs

            respond_time = perf_counter() - start_time
            self.logger.info("Total streaming duration: %.2f seconds", respond_time)

        except Exception as exc:  # pragma: no cover
            await self._cancel_tasks(thinking_tasks)
            error_occurred = True
            await self._handle_stream_error(event_emitter, str(exc))

        finally:
            await self._flush_logs(event_emitter, valves, emitted_citations)
            await emit_completion(
                event_emitter,
                content=assistant_message,
                usage=total_usage or None,
                done=True,
            )
            chat_id = metadata.get("chat_id")
            message_id = metadata.get("message_id")
            if chat_id and message_id and emitted_citations:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id, message_id, {"sources": emitted_citations}
                )

        return assistant_message

    async def run_nonstreaming_turn(
        self,
        body: ResponsesBody,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitter,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        body.stream = True
        wrapped_emitter = wrap_event_emitter(
            event_emitter, suppress_chat_messages=True, suppress_completion=False
        )
        return await self.run_streaming_turn(
            body,
            valves=valves,
            metadata=metadata,
            event_emitter=wrapped_emitter,
            tool_registry=tool_registry,
        )

    async def run_task_model(
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
        response = await self.client.create(
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

    async def emit_notification(
        self,
        event_emitter: EventEmitter | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        await emit_status(event_emitter, content, action=level)

    async def emit_error(
        self,
        event_emitter: EventEmitter | None,
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        done: bool = False,
    ) -> None:
        if not show_error_message:
            return
        await emit_error(event_emitter, str(error_obj), done=done)

    def _schedule_reasoning_statuses(
        self, body: ResponsesBody, event_emitter: EventEmitter
    ) -> list[asyncio.Task[Any]]:
        if not supports("reasoning", body.model):
            return []

        async def _later(delay: float, msg: str) -> None:
            await asyncio.sleep(delay)
            await emit_status(event_emitter, msg)

        tasks: list[asyncio.Task[Any]] = []
        for delay, msg in [
            (0, "Thinking…"),
            (1.5, "Reading the user's question…"),
            (4.0, "Gathering my thoughts…"),
            (6.0, "Exploring possible responses…"),
            (7.0, "Building a plan…"),
        ]:
            tasks.append(asyncio.create_task(_later(delay + random.uniform(0, 0.5), msg)))
        return tasks

    async def _cancel_tasks(self, tasks: list[asyncio.Task[Any]]) -> None:
        if not tasks:
            return
        to_cancel = list(tasks)
        tasks.clear()
        for task in to_cancel:
            task.cancel()
        await asyncio.gather(*to_cancel, return_exceptions=True)

    def _extract_usage_from_final_response(
        self, final_response: dict[str, Any]
    ) -> dict[str, Any]:
        if "usage" in final_response:
            usage = final_response.get("usage")
            return usage if isinstance(usage, dict) else {}

        response_payload = final_response.get("response")
        if isinstance(response_payload, dict):
            usage = response_payload.get("usage")
            if isinstance(usage, dict):
                return usage

        return {}

    async def _handle_stream_error(
        self,
        event_emitter: EventEmitter | None,
        message: str,
    ) -> None:
        self.logger.error("Streaming error: %s", message)
        await emit_error(event_emitter, message, done=False)

    async def _flush_logs(
        self,
        event_emitter: EventEmitter | None,
        valves: Any,
        emitted_citations: list[dict[str, Any]] | None = None,
    ) -> None:
        session_id = current_session_id.get()
        if not session_id:
            return
        logs = get_session_logs(session_id)
        if logs:
            log_text = "\n".join(logs)
            is_truncated = len(log_text) > 4000
            self.logger.debug(
                "Emitting log citation lines=%d truncated=%s", len(logs), is_truncated
            )
            await emit_citation(event_emitter, log_text, "Logs")
            if emitted_citations is not None:
                snippet = log_text if len(log_text) <= 4000 else log_text[-4000:]
                emitted_citations.append(
                    {
                        "provider": "openai:logs",
                        "id": str(len(emitted_citations) + 1),
                        "title": "Logs",
                        "snippet": snippet,
                        "metadata": {
                            "source": "Logs",
                            "total_lines": len(logs),
                            "truncated": len(snippet) < len(log_text),
                        },
                    }
                )
            clear_session_logs(session_id)

    async def _handle_output_items_delta(
        self,
        event: dict[str, Any],
        event_emitter: EventEmitter,
        emitted_citations: list[dict[str, Any]],
        ordinal_by_url: dict[str, int],
        metadata: dict[str, Any],
    ) -> None:
        items = (event.get("output_items", {}) or {}).get("items", [])
        persistable: list[dict[str, Any]] = []
        for item in items:
            item_type = item.get("type", "")
            item_name = item.get("name", "")
            if not item_type:
                continue
            if item_type == "openai_response.items":
                persistable.append(item)
                continue
            title = ""
            content = ""
            if item_type == "function_call":
                title = f"Running the {item_name} tool…"
                try:
                    arguments = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    self.logger.warning(
                        "Received malformed tool arguments for %s: %s", item_name, exc
                    )
                    await emit_status(
                        event_emitter,
                        "Skipping malformed tool arguments.",
                        action="warning",
                    )
                    continue
                args_formatted = ", ".join(f"{k}={json.dumps(v)}" for k, v in arguments.items())
                content = wrap_code_block(f"{item_name}({args_formatted})", "python")
            elif item_type == "web_search_call":
                action = item.get("action", {}) or {}
                if action.get("type") == "search":
                    query = action.get("query")
                    sources = action.get("sources") or []
                    urls = [source.get("url") for source in sources if source.get("url")]
                    if query:
                        await emit_status(
                            event_emitter,
                            "Searching",
                            action="web_search_queries_generated",
                            queries=[query],
                            done=False,
                        )
                    if urls:
                        await emit_status(
                            event_emitter,
                            "Reading sources…",
                            action="web_search",
                            query=query,
                            urls=urls,
                            done=False,
                        )
                continue
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

            await emit_status(
                event_emitter,
                title,
                action="tool_call",
                content=content,
                done=False,
            )

        if persistable:
            chat_id = metadata.get("chat_id") or ""
            message_id = metadata.get("message_id") or ""
            openwebui_model_id = metadata.get("model", {}).get("id", "") or ""
            hidden_marker = self.history_persistence.persist_items_for_message(
                chat_id,
                message_id,
                persistable,
                model_id=openwebui_model_id,
            )
            if hidden_marker:
                await emit_chat_message(
                    event_emitter,
                    hidden_marker,
                    options={"persist_history": False},
                )

    async def _handle_message_delta(
        self,
        event: dict[str, Any],
        emitted_citations: list[dict[str, Any]],
        ordinal_by_url: dict[str, int],
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
                        payload = {
                            "provider": "openai:citation",
                            "id": f"{ordinal}",
                            "title": citation.get("metadata", {}).get("title") or source_url,
                            "link": source_url,
                            "snippet": text_value,
                            "metadata": citation.get("metadata", {}),
                        }
                        emitted_citations.append(payload)


__all__ = ["EventEmitter", "ResponsesEngine"]
