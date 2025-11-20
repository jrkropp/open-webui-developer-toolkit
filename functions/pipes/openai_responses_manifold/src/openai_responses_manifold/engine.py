"""Streaming orchestration and tool loop for the Responses manifold.

The flow is deliberately linear and explicit:
1) Stream a response from OpenAI Responses API.
2) Emit deltas, statuses, and persist structured items as they arrive.
3) If the model requested tool calls, run local tools, append outputs, and loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal

from open_webui.models.chats import Chats

from .core.openai_requests import ResponseCreateParams
from .core.openai_response_events import (
    ErrorEvent,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseQueuedEvent,
    ResponseReasoningSummaryTextDoneEvent,
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


@dataclass
class TurnState:
    """Streaming scratch space for a single turn."""

    response_text: str = ""
    usage_summary: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_executed: int = 0
    completed_response: dict[str, Any] | None = None
    error_message: str | None = None
    has_error: bool = False
    last_tool_result: str | None = None
    has_sent_status: bool = False
    thinking_tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    def reset_for_next_response(self) -> None:
        self.completed_response = None
        self.usage_summary = None
        self.has_sent_status = False


class TurnSession:
    """Consumes stream events while coordinating a single turn."""

    def __init__(
        self,
        engine: ResponsesEngine,
        body: ResponseCreateParams,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitterFn,
        *,
        openwebui_tools: dict[str, dict[str, Any]] | None,
    ) -> None:
        self.engine = engine
        self.body = body
        self.valves = valves
        self.emitter = EventEmitter(event_emitter)
        self.openwebui_tools = openwebui_tools
        self.debug_enabled = engine.logger.isEnabledFor(logging.DEBUG)

        self.chat_id = metadata.get("chat_id")
        self.message_id = metadata.get("message_id")
        self.model_id = (metadata.get("model") or {}).get("id")
        self.can_persist_items = bool(self.chat_id and self.message_id and self.model_id)
        self.persist_reasoning_tokens = getattr(
            self.valves, "PERSIST_REASONING_TOKENS", "disabled"
        ) == "conversation"
        self.persist_tool_results = getattr(self.valves, "PERSIST_TOOL_RESULTS", True)

        self.state = TurnState()
        self.state.thinking_tasks = self.engine._schedule_reasoning_statuses(body, self.emit_status)

        self.event_dispatch: dict[type[Any], Callable[[Any], Awaitable[bool]]] = {
            ResponseOutputTextDeltaEvent: self._on_text_delta,
            ResponseOutputItemAddedEvent: self._on_item_added,
            ResponseOutputItemDoneEvent: self._on_item_done,
            ResponseReasoningSummaryTextDoneEvent: self._on_reasoning_summary,
            ResponseOutputTextDoneEvent: self._on_text_done,
            ResponseCompletedEvent: self._on_completed,
            ResponseFailedEvent: self._on_error,
            ResponseIncompleteEvent: self._on_error,
            ErrorEvent: self._on_error,
            ResponseCreatedEvent: self._on_progress,
            ResponseInProgressEvent: self._on_progress,
            ResponseQueuedEvent: self._on_progress,
        }

    async def emit_status(
        self,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
        require_previous: bool = False,
    ) -> None:
        if require_previous and not self.state.has_sent_status:
            return
        self.state.has_sent_status = True
        await self.emitter.status(description, done=done, hidden=hidden)

    async def handle_event(self, event: Any) -> bool:
        """Process a single stream event. Returns True when the stream should stop."""

        handler = self.event_dispatch.get(type(event))
        if handler is not None:
            return await handler(event)
        return False

    async def prepare_output_items_and_tool_calls(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Hydrate sanitized output items and return any requested tool calls."""

        response_payload = self.state.completed_response
        if not response_payload:
            return [], []

        raw_output = response_payload.get("output") or []
        if not raw_output:
            return [], []

        output_items = self.engine._sanitize_output_items(raw_output, store=self.body.store)
        if not output_items:
            return [], []

        if isinstance(self.body.input, list):
            self.body.input.extend(output_items)
        else:
            self.body.input = list(output_items)

        tool_calls = [item for item in output_items if item.get("type") == "function_call"]
        if tool_calls:
            self.state.tool_calls_executed += len(tool_calls)

        return output_items, tool_calls

    async def execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tool_calls:
            return []

        if not self.openwebui_tools:
            self.engine.logger.warning("Tool calls requested but no tool registry provided; skipping execution.")
            await self.emit_status("Tool execution skipped: no tool registry available.")
            return []

        try:
            function_outputs = await execute_tool_calls(tool_calls, self.openwebui_tools)
        except ToolExecutionError as exc:
            self.engine.logger.warning("Skipping malformed tool arguments: %s", exc)
            await self.emit_status("Skipping malformed tool arguments.")
            return []

        return function_outputs

    async def append_tool_outputs(self, function_outputs: list[dict[str, Any]]) -> bool:
        if not function_outputs:
            return False

        self.state.last_tool_result = str(function_outputs[-1].get("output", ""))
        if self.persist_tool_results:
            await self._persist_items(function_outputs)

        for output in function_outputs:
            output_str = output.get("output", "")
            if output_str:
                await self.emit_status(f"Received tool result\n{output_str}")

        if isinstance(self.body.input, list):
            self.body.input.extend(function_outputs)
        else:
            self.body.input = list(function_outputs)
        return True

    async def _on_text_delta(self, event: ResponseOutputTextDeltaEvent) -> bool:
        delta_val = event.delta
        if delta_val:
            self.state.response_text += delta_val
            await self.emitter.delta(delta_val)
        return False

    async def _on_item_added(self, event: ResponseOutputItemAddedEvent) -> bool:
        item = event.item or {}
        if item.get("type") == "message" and item.get("status") == "in_progress":
            await self.emit_status("Responding to the user…", require_previous=True)
        return False

    async def _on_item_done(self, event: ResponseOutputItemDoneEvent) -> bool:
        item = event.item or {}
        item_type = item.get("type") or ""

        if item_type == "reasoning" and self.persist_reasoning_tokens:
            await self._persist_items([item])
            return False

        if item_type in ("message", "web_search_call"):
            return False

        if self.persist_tool_results:
            await self._persist_items([item])

        status_desc = self.engine._status_from_output_item(item)
        if status_desc:
            await self.emit_status(status_desc)
        return False

    async def _on_reasoning_summary(self, event: ResponseReasoningSummaryTextDoneEvent) -> bool:
        text_val = (event.text or "").strip()
        if text_val:
            title, content = self.engine._parse_reasoning_summary(text_val)
            await self.engine._cancel_tasks(self.state.thinking_tasks)
            await self.emit_status(f"{title}\n{content}")
        return False

    async def _on_text_done(self, event: ResponseOutputTextDoneEvent) -> bool:
        text_val = event.text
        if self.debug_enabled:
            self.engine.logger.debug("event=response.output_text.done text_len=%d", len(text_val or ""))
        await self.engine._cancel_tasks(self.state.thinking_tasks)
        if text_val and not self.state.response_text:
            self.state.response_text = text_val
        await self.emitter.replace(self.state.response_text or text_val)
        return False

    async def _on_completed(self, event: ResponseCompletedEvent) -> bool:
        await self.engine._cancel_tasks(self.state.thinking_tasks)
        self.state.completed_response = event.response
        self.state.usage_summary = self.engine._extract_usage_from_final_response(event.response)
        if self.debug_enabled:
            usage_keys = sorted((self.state.usage_summary or {}).keys())
            self.engine.logger.debug("event=response.completed usage_keys=%s", usage_keys)
        return True

    async def _on_error(self, event: ErrorEvent | ResponseFailedEvent | ResponseIncompleteEvent) -> bool:
        await self.engine._cancel_tasks(self.state.thinking_tasks)
        self.state.has_error = True
        if isinstance(event, ErrorEvent):
            self.state.error_message = event.message
        else:
            response_payload = event.response
            self.state.error_message = (response_payload.get("error") or {}).get(
                "message", "OpenAI returned an error."
            )
        self.engine.logger.error("turn.error type=response_error message=%s", self.state.error_message)
        await self.engine._handle_stream_error(self.emitter, self.state.error_message or "")
        return True

    async def _on_progress(
        self, event: ResponseCreatedEvent | ResponseInProgressEvent | ResponseQueuedEvent
    ) -> bool:
        if self.debug_enabled:
            self.engine.logger.debug(
                "event=%s model=%s", event.type.value, getattr(event, "response", {}).get("model")
            )
        return False

    async def _persist_items(self, items: list[dict[str, Any]]) -> None:
        if not (items and self.can_persist_items):
            return

        try:
            hidden_markers = self.engine.history_persistence.persist_items_for_message(
                self.chat_id,
                self.message_id,
                items,
                model_id=self.model_id,
            )
        except Exception as exc:  # pragma: no cover
            self.engine.logger.warning("Failed to persist output items: %s", exc)
            hidden_markers = ""

        if hidden_markers:
            self.state.response_text += hidden_markers
            await self.emitter.replace(self.state.response_text)

class ResponsesEngine:
    """Encapsulates streaming and tool orchestration."""

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
        self.history_persistence = history_persistence or HistoryPersistence.from_item_store(
            self.store
        )
        self.logger = logger or get_logger(__name__)

    async def run_streaming_turn(
        self,
        body: ResponseCreateParams,
        *,
        valves: Any,
        metadata: dict[str, Any],
        event_emitter: EventEmitterFn,
        openwebui_tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        session = TurnSession(
            self,
            body,
            valves,
            metadata,
            event_emitter,
            openwebui_tools=openwebui_tools,
        )

        model_router_result = body.model_router_result
        if model_router_result:
            body.model_router_result = None
            explanation = model_router_result.get('explanation', '')
            await session.emit_status(
                description=(
                    f"Routing to {model_router_result.get('model')} "
                    f"(effort: {model_router_result.get('reasoning_effort')})\n"
                    f"Explanation: {explanation}"
                )
            )

        self.logger.info('turn.start model=%s task=chat', body.model)
        start_time = perf_counter()
        function_calls_supported = supports('function_calling', body.model)

        try:
            max_loops = getattr(valves, 'MAX_FUNCTION_CALL_LOOPS', 10)
            for _ in range(max_loops):
                session.state.reset_for_next_response()

                await self._stream_response(session, body, valves)

                if session.state.has_error or not session.state.completed_response:
                    break

                if not function_calls_supported:
                    break

                _, tool_calls = await session.prepare_output_items_and_tool_calls()
                if not tool_calls:
                    break

                function_outputs = await session.execute_tool_calls(tool_calls)
                if not function_outputs:
                    break

                if not await session.append_tool_outputs(function_outputs):
                    break

            if session.debug_enabled and session.state.completed_response:
                try:
                    payload_str = json.dumps(session.state.completed_response, ensure_ascii=False)
                    preview, truncated = truncate_for_log(payload_str, limit=1000)
                    self.logger.debug(
                        'response.payload_preview enabled=true truncated=%s len=%d payload=%s',
                        truncated,
                        len(payload_str),
                        preview,
                    )
                except Exception:
                    pass

            usage_summary = session.state.usage_summary or {}
            tokens_in = usage_summary.get('input_tokens')
            tokens_out = usage_summary.get('output_tokens')
            respond_time = perf_counter() - start_time
            summary_kwargs = {
                'status': 'error' if session.state.has_error else 'ok',
                'model': body.model,
                'duration_sec': respond_time,
                'tool_calls': session.state.tool_calls_executed,
                'citations': len(session.state.citations),
                'input_tokens': tokens_in,
                'output_tokens': tokens_out,
            }
            if session.state.error_message:
                summary_kwargs['last_error'] = session.state.error_message
            self.logger.info(
                'Streaming summary status=%(status)s model=%(model)s duration_sec=%(duration_sec).2f '
                'tool_calls=%(tool_calls)d citations=%(citations)d '
                'input_tokens=%(input_tokens)s output_tokens=%(output_tokens)s'
                + (' last_error=%(last_error)s' if session.state.error_message else ''),
                summary_kwargs,
            )

        except Exception as exc:  # pragma: no cover
            await self._cancel_tasks(session.state.thinking_tasks)
            session.state.has_error = True
            session.state.error_message = str(exc)
            self.logger.error('turn.error type=%s message=%s', type(exc).__name__, session.state.error_message)
            await self._handle_stream_error(session.emitter, session.state.error_message)

        finally:
            await self._emit_log_citation(session.emitter, session.state.citations)
            if not session.state.response_text and not session.state.has_error and session.state.last_tool_result:
                session.state.response_text = session.state.last_tool_result
            usage_for_completion = (
                session.state.usage_summary
                or self._extract_usage_from_final_response(session.state.completed_response or {})
                or None
            )
            await session.emit_status('Done', done=True, hidden=False, require_previous=True)
            await session.emitter.chat_completion(
                {'content': session.state.response_text, 'usage': usage_for_completion, 'done': True}
            )
            chat_id = metadata.get('chat_id')
            message_id = metadata.get('message_id')
            if chat_id and message_id and session.state.citations:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id,
                    message_id,
                    {'id': message_id, 'sources': session.state.citations},
                )

        return session.state.response_text

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
        self, body: ResponseCreateParams, status_fn: Callable[[str], Awaitable[Any]]
    ) -> list[asyncio.Task[Any]]:
        if not supports("reasoning", body.model):
            return []

        async def _later(delay: float, msg: str) -> None:
            await asyncio.sleep(delay)
            await status_fn(msg)

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

    def _sanitize_output_items(self, items: list[dict[str, Any]], *, store: bool | None) -> list[dict[str, Any]]:
        """Strip server-side IDs when store=False to avoid lookups on replay."""

        if store is not False:
            return [item for item in items if isinstance(item, dict)]

        cleaned: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                clone = dict(item)
                clone.pop("id", None)
                cleaned.append(clone)
        return cleaned

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

    async def _stream_response(
        self,
        session: TurnSession,
        body: ResponseCreateParams,
        valves: Any,
    ) -> None:
        async for event in self.client.stream(
            body.model_dump(exclude_none=True),
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
            typed=True,
        ):
            if await session.handle_event(event):
                break

    def _status_from_output_item(self, item: dict[str, Any]) -> str | None:
        """Return a user-facing status string for a completed output item."""

        item_type = item.get("type")
        if not item_type:
            return None

        if item_type == "function_call":
            name = item.get("name", "tool")
            try:
                arguments = json.loads(item.get("arguments") or "{}")
                args_formatted = ", ".join(f"{k}={json.dumps(v)}" for k, v in arguments.items())
                return f"Running the {name} tool…\n{name}({args_formatted})"
            except Exception:
                return f"Running the {name} tool…"

        if item_type == "web_search_call":
            action = item.get("action") or {}
            if action.get("type") == "search":
                query = action.get("query")
                return f"Searching\n{query}" if query else "Searching the web…"
            return "Web search in progress…"

        if item_type == "file_search_call":
            return "Let me skim those files…"
        if item_type == "image_generation_call":
            return "Let me create that image…"
        if item_type == "mcp_call":
            return "Querying the MCP server…"
        if item_type == "code_interpreter_call":
            return "Running code interpreter…"

        return None

    def _parse_reasoning_summary(self, text_val: str) -> tuple[str, str]:
        """Extract a title/content pair from reasoning summary text."""

        title = "Thinking…"
        content = text_val
        if "**" in text_val:
            try:
                parts = text_val.split("**")
                bold_segments = [parts[i] for i in range(1, len(parts), 2)]
                if bold_segments:
                    title = bold_segments[-1].strip()
                    content = text_val.replace(f"**{bold_segments[-1]}**", "").strip()
            except Exception:
                pass
        return title, content


__all__ = ["EventEmitterFn", "ResponsesEngine"]
