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

try:  # pragma: no cover - fallback for test stubs without aiohttp
    from aiohttp.client_exceptions import ClientResponseError
except Exception:  # pragma: no cover
    ClientResponseError = Exception  # type: ignore[assignment]

from openai_responses_manifold.adapters.openai.client import OpenAIResponsesClient
from openai_responses_manifold.adapters.openai.events import (
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
from openai_responses_manifold.adapters.openai.requests import ResponseCreateParams
from openai_responses_manifold.core.logging import (
    OWUI_SESSION_ID,
    clear_session_logs,
    get_logger,
    get_session_logs,
    truncate_for_log,
)
from openai_responses_manifold.core.model_catalog import supports
from openai_responses_manifold.domain.events import NullRuntimeEvents, RuntimeEvents
from openai_responses_manifold.domain.history import HistoryPersistence, HistoryStore
from openai_responses_manifold.domain.code_interpreter import (
    handle_code_interpreter_event,
    handle_code_interpreter_item,
    emit_pending_code_interpreter_result,
)
from openai_responses_manifold.domain.turn_context import TurnContext
from openai_responses_manifold.domain.tasks import run_task_model
from openai_responses_manifold.domain.tools import ToolExecutor, tool_summaries_for_log


@dataclass
class _StreamState:
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
    has_any_status: bool = False
    thinking_tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    code_snippets: dict[int, str] = field(default_factory=dict)
    last_code_output_index: int | None = None
    pending_ci_results: set[int] = field(default_factory=set)
    pending_ci_code_snippets: dict[int, str] = field(default_factory=dict)

    def reset_for_next_response(self) -> None:
        self.completed_response = None
        self.usage_summary = None
        self.has_sent_status = False
        self.code_snippets.clear()
        self.last_code_output_index = None
        self.pending_ci_results.clear()
        self.pending_ci_code_snippets.clear()


@dataclass
class TurnResult:
    """Result of a streaming turn, reusable outside Open WebUI."""

    text: str
    usage: dict[str, Any] | None
    citations: list[dict[str, Any]]
    error_message: str | None = None


@dataclass
class StreamOutcome:
    """Result of a single Responses stream."""

    text: str
    output_items: list[dict[str, Any]]
    usage: dict[str, Any] | None
    citations: list[dict[str, Any]]
    error: str | None = None
    last_tool_result: str | None = None


class _StreamSession:
    """Consumes stream events while coordinating a single turn."""

    def __init__(
        self,
        engine: ResponsesEngine,
        body: ResponseCreateParams,
        ctx: TurnContext,
        events: RuntimeEvents,
        *,
        state: _StreamState | None = None,
    ) -> None:
        self.engine = engine
        self.body = body
        self.valves = ctx.valves
        self.metadata = ctx.metadata
        self.events = events or NullRuntimeEvents()
        self.state = state or _StreamState()
        self.debug_enabled = engine.logger.isEnabledFor(logging.DEBUG)
        self.state.thinking_tasks = self.engine._schedule_reasoning_statuses(body, self.emit_status)

    async def emit_status(
        self,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
        require_previous: bool = False,
    ) -> None:
        if require_previous and not self.state.has_any_status:
            return
        self.state.has_sent_status = True
        self.state.has_any_status = True
        await self.events.status(description, done=done, hidden=hidden)

    async def handle_event(self, event: Any) -> bool:
        """Process a single stream event. Returns True when the stream should stop."""

        if isinstance(event, ResponseOutputTextDeltaEvent):
            await self._handle_text_delta(event)
            return False

        if isinstance(event, ResponseOutputItemAddedEvent):
            await self._handle_item_added(event)
            return False

        if isinstance(event, ResponseOutputItemDoneEvent):
            await self._handle_item_done(event)
            return False

        if isinstance(event, ResponseReasoningSummaryTextDoneEvent):
            await self._handle_reasoning_summary(event)
            return False

        if isinstance(event, ResponseOutputTextDoneEvent):
            await self._handle_text_done(event)
            return False

        handled_ci = await handle_code_interpreter_event(
            event,
            self.state,
            self.emit_status,
            self.engine.logger,
        )
        if handled_ci:
            return True

        if isinstance(event, ResponseCompletedEvent):
            await self.engine._cancel_tasks(self.state.thinking_tasks)
            self.state.completed_response = event.response
            self.state.usage_summary = self.engine._extract_usage_from_final_response(event.response)
            if self.debug_enabled:
                usage_keys = sorted((self.state.usage_summary or {}).keys())
                self.engine.logger.debug("event=response.completed usage_keys=%s", usage_keys)
            return True

        if isinstance(event, (ResponseFailedEvent, ErrorEvent)):
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
            await self.engine._handle_stream_error(self.events, self.state.error_message or "")
            return True

        if isinstance(event, ResponseIncompleteEvent):
            await self.engine._cancel_tasks(self.state.thinking_tasks)
            self.state.completed_response = event.response
            self.state.usage_summary = self.engine._extract_usage_from_final_response(event.response)
            if self.debug_enabled:
                usage_keys = sorted((self.state.usage_summary or {}).keys())
                self.engine.logger.debug("event=response.incomplete usage_keys=%s", usage_keys)
            await self.emit_status("Response was incomplete (e.g., max_output_tokens or content filter).")
            return True

        if isinstance(event, (ResponseCreatedEvent, ResponseInProgressEvent, ResponseQueuedEvent)):
            if self.debug_enabled:
                self.engine.logger.debug(
                    "event=%s model=%s", event.type.value, getattr(event, "response", {}).get("model")
                )
            return False

        return False

    async def collect_output_items(self) -> list[dict[str, Any]]:
        if not self.state.completed_response:
            return []

        output_items = self.engine._sanitize_output_items(
            (self.state.completed_response or {}).get("output") or [], store=self.body.store
        )

        if output_items:
            if isinstance(self.body.input, list):
                self.body.input.extend(output_items)
            else:
                self.body.input = output_items

        return output_items

    async def append_tool_outputs(self, function_outputs: list[dict[str, Any]]) -> bool:
        if not function_outputs:
            return False

        self.state.last_tool_result = str(function_outputs[-1].get("output", ""))
        if getattr(self.valves, "PERSIST_TOOL_RESULTS", True):
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

    def _capture_action_sources(self, item: dict[str, Any]) -> None:
        action = item.get("action")
        if not isinstance(action, dict):
            return
        sources = action.get("sources")
        if not isinstance(sources, list):
            return

        item_type = item.get("type") or ""
        provider_map = {
            "web_search_call": "openai:web_search",
            "file_search_call": "openai:file_search",
            "mcp_call": "openai:mcp",
            "code_interpreter_call": "openai:code_interpreter",
        }
        provider = provider_map.get(item_type, "openai:tool")
        prefix = provider.split(":")[-1] or "source"

        for idx, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            url = source.get("url") or source.get("link")
            if not url:
                continue
            title = source.get("title") or url
            snippet = source.get("snippet") or source.get("content") or ""
            self.state.citations.append(
                {
                    "provider": provider,
                    "id": f"{prefix}-{len(self.state.citations) + 1}",
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "metadata": {"rank": idx, "item_type": item_type},
                }
            )

    async def _handle_text_delta(self, event: ResponseOutputTextDeltaEvent) -> None:
        delta_val = event.delta
        if delta_val:
            self.state.response_text += delta_val
            await self.events.delta(delta_val)

    async def _handle_item_added(self, event: ResponseOutputItemAddedEvent) -> None:
        item = event.item or {}
        if item.get("type") == "message" and item.get("status") == "in_progress":
            await self.emit_status("Responding to the user…", require_previous=True)

    async def _handle_item_done(self, event: ResponseOutputItemDoneEvent) -> None:
        item = event.item or {}
        item_type = item.get("type") or ""

        should_persist = False
        if item_type == "reasoning":
            should_persist = getattr(self.valves, "PERSIST_REASONING_TOKENS", "disabled") == "conversation"
        elif item_type in ("message", "web_search_call"):
            should_persist = False
        else:
            should_persist = getattr(self.valves, "PERSIST_TOOL_RESULTS", True)

        if should_persist:
            await self._persist_items([item])

        if item_type == "code_interpreter_call":
            await handle_code_interpreter_item(
                item,
                self.state,
                self.events,
                self.engine.logger,
                self.emit_status,
                output_index=event.output_index,
            )

        status_desc = self.engine._status_from_output_item(item)
        if status_desc:
            await self.emit_status(status_desc)
        self._capture_action_sources(item)

    async def _handle_reasoning_summary(self, event: ResponseReasoningSummaryTextDoneEvent) -> None:
        text_val = (event.text or "").strip()
        if text_val:
            title, content = self.engine._parse_reasoning_summary(text_val)
            await self.engine._cancel_tasks(self.state.thinking_tasks)
            await self.emit_status(f"{title}\n{content}")

    async def _handle_text_done(self, event: ResponseOutputTextDoneEvent) -> None:
        text_val = event.text
        if self.debug_enabled:
            self.engine.logger.debug("event=response.output_text.done text_len=%d", len(text_val or ""))
        await self.engine._cancel_tasks(self.state.thinking_tasks)
        if text_val and not self.state.response_text:
            self.state.response_text = text_val
        await self.events.replace(self.state.response_text or text_val)
        await emit_pending_code_interpreter_result(
            self.state,
            self.events,
            self.engine.logger,
            assistant_text=text_val,
        )

    async def _persist_items(self, items: list[dict[str, Any]]) -> None:
        chat_id = self.metadata.get("chat_id")
        message_id = self.metadata.get("message_id")
        model_id = (self.metadata.get("model") or {}).get("id")
        if chat_id and message_id and model_id:
            try:
                hidden_markers = self.engine.history_persistence.persist_items_for_message(
                    chat_id,
                    message_id,
                    items,
                    model_id=model_id,
                )
            except Exception as exc:  # pragma: no cover
                self.engine.logger.warning("Failed to persist output items: %s", exc)
                hidden_markers = ""
            if hidden_markers:
                self.state.response_text += hidden_markers
                await self.events.replace(self.state.response_text)


class SSEStreamRunner:
    """Run a single Responses stream and return structured outcome."""

    def __init__(self, engine: ResponsesEngine, *, logger: logging.Logger | None = None) -> None:
        self.engine = engine
        self.logger = logger or get_logger(__name__)
        self.state = _StreamState()
        self.session: _StreamSession | None = None

    async def stream(
        self,
        body: ResponseCreateParams,
        ctx: TurnContext,
        events: RuntimeEvents,
    ) -> StreamOutcome:
        self.state.reset_for_next_response()
        self.session = _StreamSession(self.engine, body, ctx, events, state=self.state)
        await self.engine._stream_response(self.session, body, ctx.valves)

        if self.session.debug_enabled and self.state.completed_response:
            try:
                payload_str = json.dumps(self.state.completed_response, ensure_ascii=False)
                preview, truncated = truncate_for_log(payload_str, limit=1000)
                self.logger.debug(
                    "response.payload_preview enabled=true truncated=%s len=%d payload=%s",
                    truncated,
                    len(payload_str),
                    preview,
                )
            except Exception:
                pass

        output_items = await self.session.collect_output_items()
        error_message = self.state.error_message if self.state.has_error else None
        return StreamOutcome(
            text=self.state.response_text,
            output_items=output_items,
            usage=self.state.usage_summary,
            citations=list(self.state.citations),
            error=error_message,
            last_tool_result=self.state.last_tool_result,
        )


class ToolLoop:
    """Loop streaming + tool execution until no more tool calls or limits hit."""

    def __init__(
        self,
        runner: SSEStreamRunner,
        executor: ToolExecutor,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.runner = runner
        self.executor = executor
        self.logger = logger or get_logger(__name__)

    async def run_turn(
        self,
        body: ResponseCreateParams,
        ctx: TurnContext,
        events: RuntimeEvents,
        tool_registry: dict[str, dict[str, Any]],
        *,
        max_loops: int,
        function_calls_supported: bool,
    ) -> TurnResult:
        citations: list[dict[str, Any]] = []
        last_text = ""
        last_error: str | None = None
        usage: dict[str, Any] | None = None

        for _ in range(max_loops):
            outcome = await self.runner.stream(body, ctx, events)
            citations = outcome.citations
            last_text = outcome.text
            usage = outcome.usage
            last_error = outcome.error

            if outcome.error or not function_calls_supported:
                break

            output_items = outcome.output_items or []
            tool_calls = self._find_tool_calls(output_items)
            if not tool_calls:
                break

            executed_before = self.runner.state.tool_calls_executed
            if body.max_tool_calls is not None:
                remaining = max(body.max_tool_calls - executed_before, 0)
                if remaining <= 0:
                    await self._emit_status("Tool call limit reached; ignoring further tool requests.")
                    break
                if len(tool_calls) > remaining:
                    tool_calls = tool_calls[:remaining]
                    if not tool_calls:
                        await self._emit_status("Tool call limit reached; ignoring further tool requests.")
                        break

            outputs = await self.executor.run(
                tool_calls,
                tool_registry,
                emit_status=self._emit_status,
                valves=ctx.valves,
            )
            if not outputs:
                break

            self.runner.state.tool_calls_executed = executed_before + len(outputs)
            session = self.runner.session
            appended = False
            if session:
                appended = await session.append_tool_outputs(outputs)
            if not appended:
                break

        return TurnResult(
            text=last_text,
            usage=usage,
            citations=citations,
            error_message=last_error,
        )

    def _find_tool_calls(self, output_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in output_items if item.get("type") == "function_call"]

    async def _emit_status(self, description: str) -> None:
        session = self.runner.session
        if session:
            await session.emit_status(description)

class ResponsesEngine:
    """Encapsulates streaming and tool orchestration."""

    def __init__(
        self,
        *,
        client: OpenAIResponsesClient | None = None,
        item_store: HistoryStore | None = None,
        history_persistence: HistoryPersistence | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client or OpenAIResponsesClient()
        self.history_persistence = history_persistence or HistoryPersistence(item_store)
        self.logger = logger or get_logger(__name__)

    async def run_streaming_turn(
        self,
        body: ResponseCreateParams,
        *,
        ctx: TurnContext,
        events: RuntimeEvents | None,
        tool_registry: dict[str, dict[str, Any]] | None = None,
    ) -> TurnResult:
        runtime_events = events or NullRuntimeEvents()
        tool_registry = tool_registry or {}
        runner = SSEStreamRunner(self, logger=self.logger)
        executor = ToolExecutor(self.logger)
        loop = ToolLoop(runner, executor, logger=self.logger)
        self._log_tool_summaries(body.tools or [], logging.DEBUG, reason="request")

        model_router_result = body.model_router_result
        if model_router_result:
            body.model_router_result = None
            explanation = model_router_result.get("explanation", "")
            await runtime_events.status(
                description=(
                    f"Routing to {model_router_result.get('model')} "
                    f"(effort: {model_router_result.get('reasoning_effort')})\n"
                    f"Explanation: {explanation}"
                )
            )

        self.logger.info("turn.start model=%s task=chat", body.model)
        start_time = perf_counter()
        function_calls_supported = supports("function_calling", body.model)

        try:
            loop_result = await loop.run_turn(
                body,
                ctx,
                runtime_events,
                tool_registry,
                max_loops=getattr(ctx.valves, "MAX_FUNCTION_CALL_LOOPS", 10),
                function_calls_supported=function_calls_supported,
            )
            runner_state = runner.state

            usage_summary = loop_result.usage or runner_state.usage_summary or {}
            tokens_in = usage_summary.get("input_tokens")
            tokens_out = usage_summary.get("output_tokens")
            respond_time = perf_counter() - start_time
            summary_kwargs = {
                "status": "error" if loop_result.error_message else "ok",
                "model": body.model,
                "duration_sec": respond_time,
                "tool_calls": runner_state.tool_calls_executed,
                "citations": len(loop_result.citations),
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
            }
            if loop_result.error_message:
                summary_kwargs["last_error"] = loop_result.error_message
            self.logger.info(
                "Streaming summary status=%(status)s model=%(model)s duration_sec=%(duration_sec).2f "
                "tool_calls=%(tool_calls)d citations=%(citations)d "
                "input_tokens=%(input_tokens)s output_tokens=%(output_tokens)s"
                + (" last_error=%(last_error)s" if loop_result.error_message else ""),
                summary_kwargs,
            )
        except ClientResponseError as exc:
            await self._cancel_tasks(runner.state.thinking_tasks)
            runner.state.has_error = True
            runner.state.error_message = f"{exc.status} {exc.message}"
            request_url = ""
            try:
                request_url = str(exc.request_info.real_url) if exc.request_info else ""
            except Exception:
                request_url = ""
            self.logger.error(
                "turn.error type=ClientResponseError status=%s url=%s message=%s",
                exc.status,
                request_url,
                exc.message,
            )
            self._log_tool_summaries(body.tools or [], logging.ERROR, reason="request")
            await self._handle_stream_error(runtime_events, runner.state.error_message or "")
            loop_result = TurnResult(
                text="",
                usage=None,
                citations=runner.state.citations,
                error_message=runner.state.error_message,
            )
        except Exception as exc:  # pragma: no cover
            await self._cancel_tasks(runner.state.thinking_tasks)
            runner.state.has_error = True
            runner.state.error_message = str(exc)
            self.logger.error("turn.error type=%s message=%s", type(exc).__name__, runner.state.error_message)
            self._log_tool_summaries(body.tools or [], logging.ERROR, reason="request")
            await self._handle_stream_error(runtime_events, runner.state.error_message or "")
            loop_result = TurnResult(
                text="",
                usage=None,
                citations=runner.state.citations,
                error_message=runner.state.error_message,
            )

        # Finalize and emit completion
        await self._emit_log_citation(runtime_events, loop_result.citations)
        if not loop_result.text and not loop_result.error_message and runner.state.last_tool_result:
            loop_result.text = runner.state.last_tool_result
        usage_for_completion = (
            loop_result.usage
            or runner.state.usage_summary
            or self._extract_usage_from_final_response(runner.state.completed_response or {})
            or None
        )
        if runner.session:
            await runner.session.emit_status("Done", done=True, hidden=False, require_previous=True)
        completion_payload: dict[str, Any] = {"done": True}
        if loop_result.error_message:
            completion_payload["error"] = {"message": loop_result.error_message}
        else:
            completion_payload.update({"content": loop_result.text, "usage": usage_for_completion})
        await runtime_events.chat_completion(completion_payload)

        return TurnResult(
            text=loop_result.text,
            usage=usage_for_completion,
            citations=loop_result.citations if loop_result.citations else [],
            error_message=loop_result.error_message,
        )

    async def run_task_model(
        self,
        body: dict[str, Any],
        valves: Any,
    ) -> str:
        return await run_task_model(self.client, body, valves)

    async def emit_notification(
        self,
        events: RuntimeEvents | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        if not events:
            return
        await events.notification(content, level=level)

    async def emit_error(
        self,
        events: RuntimeEvents | None,
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        done: bool = False,
    ) -> None:
        if not show_error_message:
            return
        if not events:
            return
        await events.chat_completion({"error": {"message": str(error_obj)}, "done": done})

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
        events: RuntimeEvents | None,
        emitted_citations: list[dict[str, Any]],
    ) -> None:
        session_id = OWUI_SESSION_ID.get()
        if not session_id or not events or isinstance(events, NullRuntimeEvents):
            return
        logs = get_session_logs(session_id)
        if not logs:
            return
        log_text = "\n".join(logs)
        truncated = len(log_text) > 4000
        self.logger.debug("Emitting log citation lines=%d truncated=%s", len(logs), truncated)
        await events.citation(
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
        events: RuntimeEvents | None,
        message: str,
    ) -> None:
        self.logger.error("Streaming error: %s", message)
        if events:
            await events.chat_completion({"error": {"message": message}, "done": False})

    def _log_tool_summaries(
        self,
        tools: list[dict[str, Any]],
        level: int,
        *,
        reason: str,
    ) -> None:
        if not self.logger.isEnabledFor(level):
            return
        summaries = tool_summaries_for_log(tools)
        if not summaries:
            self.logger.log(level, "%s.tools count=0", reason)
            return
        self.logger.log(
            level,
            "%s.tools count=%d summary=%s",
            reason,
            len(tools),
            "; ".join(summaries),
        )

    async def _stream_response(
        self,
        session: _StreamSession,
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


__all__ = ["ResponsesEngine", "TurnResult"]
