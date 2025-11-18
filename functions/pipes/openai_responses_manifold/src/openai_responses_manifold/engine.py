"""Streaming and tool orchestration engine for the Responses manifold."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import json
from time import perf_counter
from typing import Any, Literal

from open_webui.models.chats import Chats

from .core.openai_requests import ResponseCreateParams
from .core.openai_response_events import (
    ErrorEvent,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseQueuedEvent,
)
from .core.errors import ToolExecutionError
from .model_catalog import supports
from .infra import ItemStore, OpenAIResponsesClient
from .services.history import HistoryPersistence
from .services.tasks import run_task_model
from .services.tools import execute_tool_calls
from .utils import (
    OWUI_SESSION_ID,
    clear_session_logs,
    EventEmitter,
    EventEmitterFn,
    get_session_logs,
    get_logger,
    truncate_for_log,
)


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
        body: ResponseCreateParams,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitterFn,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        emitter = EventEmitter(event_emitter)
        delta_log_stride = int(os.getenv("DELTA_LOG_STRIDE", "500") or "500")
        tool_registry = tool_registry or {}
        assistant_message = ""
        last_usage: dict[str, Any] | None = None
        emitted_citations: list[dict[str, Any]] = []
        debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        delta_count = 0
        delta_chars = 0
        tool_call_count = 0
        last_error: str | None = None

        thinking_tasks = self._schedule_reasoning_statuses(body, emitter)
        final_response_payload: dict[str, Any] | None = None

        model_router_result = body.model_router_result
        if model_router_result:
            body.model_router_result = None
            explanation = model_router_result.get("explanation", "")
            await emitter.status(
                description=(
                    f"Routing to {model_router_result.get('model')} "
                    f"(effort: {model_router_result.get('reasoning_effort')})\n"
                    f"Explanation: {explanation}"
                )
            )

        self.logger.info("turn.start model=%s task=chat", body.model)
        start_time = perf_counter()
        error_occurred = False
        try:
            max_loops = getattr(valves, "MAX_FUNCTION_CALL_LOOPS", 10)
            for _ in range(max_loops):
                final_response_payload = None
                async for event in self.client.stream(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                    typed=True,
                ):
                    if isinstance(event, ResponseOutputTextDeltaEvent):
                        delta_val = event.delta
                        delta_count += 1
                        delta_chars += len(delta_val or "")
                        if debug_enabled and delta_val and (delta_count == 1 or delta_count % delta_log_stride == 0):
                            self.logger.debug("delta_progress count=%d chars=%d", delta_count, delta_chars)
                        if delta_val:
                            assistant_message += delta_val
                            await emitter.delta(delta_val)
                        continue

                    if isinstance(event, ResponseOutputTextDoneEvent):
                        text_val = event.text
                        if debug_enabled:
                            self.logger.debug("event=response.output_text.done text_len=%d", len(text_val or ""))
                        await self._cancel_tasks(thinking_tasks)
                        # Emit a final chat message reflecting the accumulated text.
                        if text_val and not assistant_message:
                            assistant_message = text_val
                        await emitter.replace(assistant_message or text_val)
                        continue

                    if isinstance(event, ResponseCompletedEvent):
                        if debug_enabled:
                            usage = event.response.get("usage") or {}
                            self.logger.debug("event=response.completed usage_keys=%s", sorted(usage.keys()))
                        final_response_payload = event.response
                        await self._cancel_tasks(thinking_tasks)
                        break

                    if isinstance(event, (ResponseFailedEvent, ResponseIncompleteEvent, ErrorEvent)):
                        await self._cancel_tasks(thinking_tasks)
                        error_occurred = True
                        if isinstance(event, ErrorEvent):
                            last_error = event.message
                        else:
                            response_payload = event.response
                            last_error = (response_payload.get("error") or {}).get(
                                "message", "OpenAI returned an error."
                            )
                        self.logger.error("turn.error type=response_error message=%s", last_error)
                        await self._handle_stream_error(emitter, last_error)
                        break

                    if isinstance(
                        event,
                        (
                            ResponseCreatedEvent,
                            ResponseInProgressEvent,
                            ResponseQueuedEvent,
                        ),
                    ):
                        if debug_enabled:
                            self.logger.debug(
                                "event=%s model=%s", event.type.value, getattr(event, "response", {}).get("model")
                            )
                        continue

                if final_response_payload:
                    usage_from_response = self._extract_usage_from_final_response(final_response_payload)
                    if usage_from_response:
                        last_usage = usage_from_response

                if error_occurred or not final_response_payload:
                    break

                if not supports("function_calling", body.model):
                    break
                call_items = (final_response_payload or {}).get("output", [])
                tool_calls = [item for item in call_items if item.get("type") == "function_call"]
                if not tool_calls:
                    break
                tool_call_count += len(tool_calls)
                try:
                    function_outputs = await execute_tool_calls(tool_calls, tool_registry)
                except ToolExecutionError as exc:
                    self.logger.warning("Skipping malformed tool arguments: %s", exc)
                    await emitter.status("Skipping malformed tool arguments.")
                    break
                if not function_outputs:
                    break
                existing_input = list(body.input) if isinstance(body.input, list) else []
                body.input = existing_input + function_outputs

            if debug_enabled and final_response_payload:
                try:
                    payload_str = json.dumps(final_response_payload, ensure_ascii=False)
                    preview, truncated = truncate_for_log(payload_str, limit=1000)
                    self.logger.debug(
                        "response.payload_preview enabled=true truncated=%s len=%d payload=%s",
                        truncated,
                        len(payload_str),
                        preview,
                    )
                except Exception:
                    pass

            usage_summary = last_usage or {}
            tokens_in = usage_summary.get("input_tokens")
            tokens_out = usage_summary.get("output_tokens")
            total_tokens = usage_summary.get("total_tokens")
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
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
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
            await self._handle_stream_error(emitter, last_error)

        finally:
            await self._emit_log_citation(emitter, emitted_citations)
            usage_for_completion = last_usage or self._extract_usage_from_final_response(final_response_payload or {}) or None
            await emitter.chat_completion(
                {"content": assistant_message, "usage": usage_for_completion, "done": True}
            )
            chat_id = metadata.get("chat_id")
            message_id = metadata.get("message_id")
            if chat_id and message_id and emitted_citations:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id,
                    message_id,
                    {"sources": emitted_citations},
                )

        return assistant_message

    async def run_nonstreaming_turn(
        self,
        body: ResponseCreateParams,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitterFn,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        body.stream = True
        return await self.run_streaming_turn(
            body,
            valves=valves,
            metadata=metadata,
            event_emitter=event_emitter,
            tool_registry=tool_registry,
        )

    async def run_task_model(
        self,
        body: dict[str, Any],
        valves: Any,
    ) -> str:
        return await run_task_model(self.client, body, valves)

    async def emit_notification(
        self,
        event_emitter: EventEmitterFn | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        await EventEmitter(event_emitter).notification(content, level=level)

    async def emit_error(
        self,
        event_emitter: EventEmitterFn | None,
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        done: bool = False,
    ) -> None:
        if not show_error_message:
            return
        await EventEmitter(event_emitter).chat_completion(
            {"error": {"message": str(error_obj)}, "done": done}
        )

    def _schedule_reasoning_statuses(
        self, body: ResponsesBody, emitter: EventEmitter
    ) -> list[asyncio.Task[Any]]:
        if not supports("reasoning", body.model):
            return []

        async def _later(delay: float, msg: str) -> None:
            await asyncio.sleep(delay)
            await emitter.status(msg)

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

    async def _emit_log_citation(
        self,
        emitter: EventEmitter,
        emitted_citations: list[dict[str, Any]],
    ) -> None:
        session_id = OWUI_SESSION_ID.get()
        if not session_id:
            return
        logs = get_session_logs(session_id)
        if not logs:
            return
        log_text = "\n".join(logs)
        truncated = len(log_text) > 4000
        self.logger.debug("Emitting log citation lines=%d truncated=%s", len(logs), truncated)
        await emitter.citation(
            {
                "document": [log_text],
                "metadata": [{"source": "Logs"}],
                "source": {"name": "Logs"},
            }
        )
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

    def _extract_usage_from_final_response(self, final_response: dict[str, Any]) -> dict[str, Any]:
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
        emitter: EventEmitter | None,
        message: str,
    ) -> None:
        self.logger.error("Streaming error: %s", message)
        if emitter:
            await emitter.chat_completion({"error": {"message": message}, "done": False})

__all__ = ["EventEmitterFn", "ResponsesEngine"]
