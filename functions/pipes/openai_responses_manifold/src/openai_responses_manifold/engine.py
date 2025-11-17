"""Streaming and tool orchestration engine for the Responses manifold."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Literal

from open_webui.models.chats import Chats

from .core.api_models import ResponsesBody
from .core.events import (
    BaseStreamEvent,
    ErrorEvent,
    EventType,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)
from .core.errors import ToolExecutionError
from .model_catalog import supports
from .infra import ItemStore, OpenAIResponsesClient
from .services.history import HistoryPersistence
from .services.tools import execute_tool_calls
from .utils import (
    OWUI_SESSION_ID,
    clear_session_logs,
    emit_chat_message,
    emit_citation,
    emit_completion,
    emit_error,
    emit_status,
    get_logger,
    get_session_logs,
    merge_usage_stats,
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
        self.logger = logger or get_logger(__name__)

    async def run_streaming_turn(
        self,
        body: ResponsesBody,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitter,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        delta_log_stride = int(os.getenv("DELTA_LOG_STRIDE", "500") or "500")
        tool_registry = tool_registry or {}
        assistant_message = ""
        total_usage: dict[str, Any] = {}
        emitted_citations: list[dict[str, Any]] = []
        debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        delta_count = 0
        delta_chars = 0
        tool_call_count = 0
        last_error: str | None = None

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

        self.logger.info("turn.start model=%s task=chat", body.model)
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
                    typed=True,
                ):
                    event_dict = event.model_dump() if isinstance(event, BaseStreamEvent) else event
                    event_type = event_dict.get("type")

                    if event_type == EventType.RESPONSE_OUTPUT_TEXT_DELTA.value:
                        delta_val = (
                            event.delta if isinstance(event, ResponseOutputTextDeltaEvent) else event_dict.get("delta", "")
                        )
                        delta_count += 1
                        delta_chars += len(delta_val or "")
                        if debug_enabled and delta_val and (delta_count == 1 or delta_count % delta_log_stride == 0):
                            self.logger.debug("delta_progress count=%d chars=%d", delta_count, delta_chars)
                        if delta_val:
                            assistant_message += delta_val
                            await emit_chat_message(event_emitter, assistant_message)
                        continue

                    if event_type == EventType.RESPONSE_OUTPUT_TEXT_DONE.value:
                        text_val = (
                            event.text if isinstance(event, ResponseOutputTextDoneEvent) else event_dict.get("text", "")
                        )
                        if debug_enabled:
                            self.logger.debug("event=response.output_text.done text_len=%d", len(text_val or ""))
                        final_response = event_dict
                        await self._cancel_tasks(thinking_tasks)
                        continue

                    if event_type == EventType.RESPONSE_COMPLETED.value:
                        if debug_enabled:
                            response_payload = event_dict.get("response") or {}
                            usage = response_payload.get("usage") or {}
                            self.logger.debug("event=response.completed usage_keys=%s", sorted(usage.keys()))
                        final_response = event_dict.get("response") or event_dict
                        await self._cancel_tasks(thinking_tasks)
                        break

                    if event_type in {
                        EventType.RESPONSE_FAILED.value,
                        EventType.RESPONSE_INCOMPLETE.value,
                        EventType.ERROR.value,
                    }:
                        await self._cancel_tasks(thinking_tasks)
                        error_occurred = True
                        if isinstance(event, ErrorEvent):
                            last_error = event.message
                        else:
                            response_payload = event_dict.get("response") or {}
                            last_error = (response_payload.get("error") or {}).get(
                                "message", "OpenAI returned an error."
                            )
                        self.logger.error("turn.error type=response_error message=%s", last_error)
                        await self._handle_stream_error(event_emitter, last_error)
                        break

                    if event_type in {
                        EventType.RESPONSE_CREATED.value,
                        EventType.RESPONSE_IN_PROGRESS.value,
                    }:
                        if debug_enabled:
                            response_payload = event_dict.get("response") or {}
                            self.logger.debug("event=%s model=%s", event_type, response_payload.get("model"))
                        continue

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
                tool_call_count += len(tool_calls)
                try:
                    function_outputs = await execute_tool_calls(tool_calls, tool_registry)
                except ToolExecutionError as exc:
                    self.logger.warning("Skipping malformed tool arguments: %s", exc)
                    await emit_status(event_emitter, "Skipping malformed tool arguments.", action="warning")
                    break
                if not function_outputs:
                    break
                existing_input = list(body.input) if isinstance(body.input, list) else []
                body.input = existing_input + function_outputs

            if debug_enabled and final_response:
                try:
                    payload_str = json.dumps(final_response, ensure_ascii=False)
                    preview, truncated = truncate_for_log(payload_str, limit=1000)
                    self.logger.debug(
                        "response.payload_preview enabled=true truncated=%s len=%d payload=%s",
                        truncated,
                        len(payload_str),
                        preview,
                    )
                except Exception:
                    pass

            tokens_in = (total_usage or {}).get("input_tokens")
            tokens_out = (total_usage or {}).get("output_tokens")
            total_tokens = (total_usage or {}).get("total_tokens")
            try:
                tokens_total = (
                    total_tokens
                    if isinstance(total_tokens, (int, float))
                    else (tokens_in or 0) + (tokens_out or 0)
                )
            except Exception:
                tokens_total = None
            respond_time = perf_counter() - start_time
            tokens_sec = (
                round(tokens_total / respond_time, 2) if tokens_total and respond_time > 0 else None
            )
            respond_time = perf_counter() - start_time
            summary_kwargs = {
                "status": "error" if error_occurred else "ok",
                "model": body.model,
                "duration_sec": respond_time,
                "deltas": delta_count,
                "text_chars": delta_chars,
                "tool_calls": tool_call_count,
                "citations": len(emitted_citations),
                "input_tokens": (total_usage or {}).get("input_tokens"),
                "output_tokens": (total_usage or {}).get("output_tokens"),
                "tokens_sec": tokens_sec,
            }
            if last_error:
                summary_kwargs["last_error"] = last_error
            self.logger.info(
                "Streaming summary status=%(status)s model=%(model)s duration_sec=%(duration_sec).2f deltas=%(deltas)d text_chars=%(text_chars)d tool_calls=%(tool_calls)d citations=%(citations)d input_tokens=%(input_tokens)s output_tokens=%(output_tokens)s tokens_sec=%(tokens_sec)s"
                + (" last_error=%(last_error)s" if last_error else ""),
                summary_kwargs,
            )

        except Exception as exc:  # pragma: no cover
            await self._cancel_tasks(thinking_tasks)
            error_occurred = True
            last_error = str(exc)
            self.logger.error("turn.error type=%s message=%s", type(exc).__name__, last_error)
            await self._handle_stream_error(event_emitter, last_error)

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
        session_id = OWUI_SESSION_ID.get()
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
