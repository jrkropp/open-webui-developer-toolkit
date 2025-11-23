from __future__ import annotations

import datetime
import json
import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

from openai_responses_manifold.core.config import RuntimeConfig
from openai_responses_manifold.core.logging import (
    OWUI_SESSION_ID,
    consume_session_logs,
    get_logger,
)
from openai_responses_manifold.domain.code_interpreter import (
    emit_pending_code_interpreter_result,
    handle_code_interpreter_event,
    handle_code_interpreter_item,
)
from openai_responses_manifold.domain.types import (
    Citation,
    RuntimeEvents,
    ToolCall,
    ToolResult,
    TurnContext,
    TurnResult,
    TurnState,
)
from openai_responses_manifold.openai_api import (
    OpenAIClient,
    ResponseCodeInterpreterCallCodeDeltaEvent,
    ResponseCodeInterpreterCallCodeDoneEvent,
    ResponseCodeInterpreterCallCompletedEvent,
    ResponseCodeInterpreterCallInProgressEvent,
    ResponseCodeInterpreterCallInterpretingEvent,
    ResponseCompletedEvent,
    ResponseEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponsesRequest,
)

from .history import MARKER_PLACEHOLDER, HistoryManager

_LOGGER = get_logger(__name__)


class ResponsesEngine:
    """Orchestrate a single streaming turn against the Responses API."""

    def __init__(
        self,
        client: OpenAIClient,
        history_manager: HistoryManager,
        logger: logging.Logger | None = None,
    ):
        self._client = client
        self._history_manager = history_manager
        self._logger = logger or _LOGGER

    async def run_streaming_turn(
        self,
        request: ResponsesRequest,
        ctx: TurnContext,
        events: RuntimeEvents,
        history_key: dict[str, Any],
        tool_executor,
    ) -> TurnResult:
        cfg: RuntimeConfig = ctx.runtime_config
        state = TurnState()
        result: TurnResult | None = None
        final_text: str = ""

        try:
            await events.status("Calling OpenAI Responses API…", done=False)
        except Exception:
            self._logger.debug("Failed to emit start status", exc_info=True)

        try:
            if request.model_router_result:
                await self._emit_routing_status(request.model_router_result, events)
                request.model_router_result = None

            for _ in range(cfg.MAX_FUNCTION_CALL_LOOPS):
                response = await self._stream_single_response(
                    request=request,
                    ctx=ctx,
                    state=state,
                    events=events,
                    base_url=cfg.BASE_URL,
                    api_key=cfg.API_KEY,
                )
                if response is None:
                    break
                self._merge_usage(state, response)

                tool_calls = self._extract_tool_calls(response)
                if not tool_calls:
                    break

                if cfg.MAX_TOOL_CALLS is not None and (
                    state.tool_calls_executed + len(tool_calls) > cfg.MAX_TOOL_CALLS
                ):
                    await events.status(
                        f"Tool call limit ({cfg.MAX_TOOL_CALLS}) reached. Stopping further tool calls.",
                        done=False,
                    )
                    break

                tool_results = await tool_executor.execute(tool_calls)
                state.tool_calls_executed += len(tool_results)
                items = self._tool_results_to_output_items(tool_results)
                for item in items:
                    self._record_structured_item(item, state, cfg)
                request.input = (request.input or []) + items
        except Exception as exc:
            self._logger.exception("Streaming turn failed")
            state.error_message = state.error_message or f"Internal error: {exc}"
            if not state.assistant_internal_text:
                state.assistant_internal_text = state.error_message or ""
            try:
                await events.status("Request failed — see logs for details.", done=True, level="error")
            except Exception:
                self._logger.debug("Failed to emit failure status", exc_info=True)
        finally:
            final_text = state.assistant_internal_text or state.error_message or ""
            items_to_persist = [
                item for item in state.structured_items if _should_persist_item(item, cfg)
            ]
            try:
                final_text = self._history_manager.persist_items_for_message(
                    chat_key=history_key,
                    message_id=str(ctx.metadata.get("message_id", "")),
                    items=items_to_persist,
                    model_id=ctx.model_id,
                    openwebui_model_id=str(ctx.metadata.get("owui_model_id", "")),
                    current_assistant_text=final_text,
                    marker_placeholder=MARKER_PLACEHOLDER,
                )
            except Exception:
                self._logger.exception("Failed to persist history items")

            try:
                await emit_pending_code_interpreter_result(
                    state, events, self._logger, assistant_text=final_text
                )
            except Exception:
                self._logger.exception("Failed to emit pending CI result citation")

            result = TurnResult(
                text=final_text,
                usage=state.usage,
                citations=list(state.citations),
                error=state.error_message,
            )

            try:
                await events.chat_completion({
                    "content": state.assistant_visible_text or final_text,
                    "usage": state.usage,
                    "error": state.error_message,
                    "done": True,
                })
            except Exception:
                self._logger.exception("Failed to emit chat_completion")
            try:
                await self._emit_log_citation(ctx, state, events)
            except Exception:
                self._logger.exception("Failed to emit log citation")

        return result

    async def run_task(self, request: ResponsesRequest, ctx: TurnContext) -> str:
        request.stream = False
        request.store = False
        request.tools = None
        request.include = None
        response = await self._client.create_response(
            request,
            base_url=ctx.runtime_config.BASE_URL,
            api_key=ctx.runtime_config.API_KEY,
        )
        try:
            outputs = response.get("output") or []
            text_blocks = []
            for item in outputs:
                if item.get("type") == "output_text":
                    content = item.get("content") or []
                    if isinstance(content, str):
                        text_blocks.append(str(content))
                    else:
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "output_text":
                                text_blocks.append(str(block.get("text", "")))
                if item.get("type") == "message":
                    for block in item.get("content", []):
                        if isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                            text_blocks.append(str(block.get("text", "")))
            return "".join(text_blocks)
        except Exception:
            return json.dumps(response)

    async def _stream_single_response(
        self,
        *,
        request: ResponsesRequest,
        ctx: TurnContext,
        state: TurnState,
        events: RuntimeEvents,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any] | None:
        response_payload: dict[str, Any] | None = None
        first_event = True
        async for event in self._client.stream_responses(request, base_url=base_url, api_key=api_key):
            if first_event:
                first_event = False
                try:
                    await events.status("Streaming response from model…", done=False)
                except Exception:
                    self._logger.debug("Failed to emit streaming status", exc_info=True)
            response_payload = await self._handle_event(event, state, events, ctx)
            if isinstance(event, (ResponseFailedEvent, ResponseIncompleteEvent)):
                break
        return response_payload

    async def _handle_event(
        self,
        event: ResponseEvent,
        state: TurnState,
        events: RuntimeEvents,
        ctx: TurnContext,
    ) -> dict[str, Any] | None:
        async def emit_status(description: str, **kwargs: Any) -> None:
            await events.status(description, **kwargs)

        if isinstance(
            event,
            (
                ResponseCodeInterpreterCallInProgressEvent,
                ResponseCodeInterpreterCallInterpretingEvent,
                ResponseCodeInterpreterCallCodeDeltaEvent,
                ResponseCodeInterpreterCallCodeDoneEvent,
                ResponseCodeInterpreterCallCompletedEvent,
            ),
        ):
            await handle_code_interpreter_event(event, state, emit_status, self._logger)
            return None

        if isinstance(event, ResponseOutputTextDeltaEvent):
            delta = event.delta or ""
            if delta:
                state.assistant_visible_text += delta
                state.assistant_internal_text += delta
                await events.delta(delta)
            return None

        if isinstance(event, ResponseReasoningSummaryTextDoneEvent):
            if event.text:
                await events.status(event.text, done=False)
            return None

        if isinstance(event, ResponseOutputTextAnnotationAddedEvent):
            annotation = event.annotation or {}
            if annotation.get("type") == "url_citation":
                url = annotation.get("url")
                if not url:
                    return None

                url = _strip_tracking_params(url)
                source_name = _host_from_url(url) or "source"
                title = annotation.get("title") or url
                if url not in state.citation_ordinals:
                    state.citation_ordinals[url] = len(state.citation_ordinals) + 1
                ordinal = state.citation_ordinals[url]
                citation = Citation(
                    source_name=source_name,
                    url=url,
                    document=[title],
                    metadata={
                        "source": url,
                        "date_accessed": datetime.date.today().isoformat(),
                        "ordinal": ordinal,
                    },
                )
                state.citations.append(citation)
                payload = {
                    "source": {"name": citation.source_name, "url": citation.url},
                    "document": citation.document,
                    "metadata": [citation.metadata],
                }
                await events.source(payload)
                await events.citation(payload)
            return None

        if isinstance(event, (ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent)):
            item = event.item or {}
            if item:
                if item.get("type") == "code_interpreter_call":
                    await handle_code_interpreter_item(
                        item,
                        state,
                        events,
                        self._logger,
                        emit_status,
                        output_index=getattr(event, "output_index", None),
                    )
                self._record_structured_item(item, state, ctx.runtime_config)
            return None

        if isinstance(event, ResponseCompletedEvent):
            state.response_text = json.dumps(event.response)
            return event.response

        if isinstance(event, ResponseIncompleteEvent):
            state.error_message = event.error_message or "Response incomplete"
            return event.response or {}

        if isinstance(event, ResponseFailedEvent):
            state.error_message = event.error_message or "Response failed"
            return event.response or {}

        return None

    def _merge_usage(self, state: TurnState, response: dict[str, Any]) -> None:
        usage = _extract_usage(response)
        if usage:
            if state.usage is None:
                state.usage = dict(usage)
            else:
                for key, value in usage.items():
                    try:
                        state.usage[key] = state.usage.get(key, 0) + value
                    except Exception:
                        state.usage[key] = value

    def _extract_tool_calls(self, response: dict[str, Any]) -> list[ToolCall]:
        output_items = response.get("output") or []
        calls: list[ToolCall] = []
        for item in output_items:
            if item.get("type") != "function_call":
                continue
            call_id = str(item.get("call_id") or item.get("id") or "")
            name = str(item.get("name") or "")
            arguments = item.get("arguments")
            arguments_json = json.dumps(arguments) if arguments is not None else "{}"
            if call_id and name:
                calls.append(ToolCall(call_id=call_id, name=name, arguments_json=arguments_json))
        return calls

    def _tool_results_to_output_items(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for result in results:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": result.call_id,
                    "output": result.output,
                    "status": result.status,
                    "error": result.error_message,
                }
            )
        return items

    async def _emit_routing_status(self, router_result: dict[str, Any], events: RuntimeEvents) -> None:
        model = router_result.get("model")
        effort = router_result.get("reasoning_effort")
        explanation = router_result.get("reason") or router_result.get("explanation")
        parts = [str(model or "")]
        if effort:
            parts.append(f"effort={effort}")
        if explanation:
            parts.append(str(explanation))
        message = ": ".join(filter(None, [", ".join(filter(None, parts[:-1])), parts[-1] if len(parts) > 1 else None]))
        await events.status(message or "Routing decision applied", done=False)

    def _record_structured_item(self, item: dict[str, Any], state: TurnState, cfg: RuntimeConfig) -> None:
        state.structured_items.append(item)
        if _should_persist_item(item, cfg):
            state.assistant_internal_text += MARKER_PLACEHOLDER


    async def _emit_log_citation(
        self,
        ctx: TurnContext,
        state: TurnState,
        events: RuntimeEvents,
    ) -> None:
        session_id = ctx.metadata.get("session_id") or OWUI_SESSION_ID.get()
        if not session_id:
            return

        logs = consume_session_logs(session_id)
        if not logs:
            return

        source_name = "Error Logs" if state.error_message else "Logs"
        log_text = "\n".join(logs)
        max_len = 4000
        truncated = len(log_text) > max_len
        if truncated:
            log_text = log_text[:max_len] + "\n… (truncated)"

        citation = Citation(
            source_name=source_name,
            url=None,
            document=[log_text],
            metadata={
                "source": source_name,
                "total_lines": len(logs),
                "truncated": truncated,
            },
        )
        state.citations.append(citation)

        self._logger.debug(
            "Emitting log citation lines=%d truncated=%s", len(logs), truncated
        )
        await events.citation(
            {
                "document": citation.document,
                "metadata": [citation.metadata],
                "source": {"name": citation.source_name},
            }
        )


def _should_persist_item(item: dict[str, Any], cfg: RuntimeConfig) -> bool:
    item_type = item.get("type")
    if item_type in {"function_call", "function_call_output", "code_interpreter_call"}:
        return bool(cfg.PERSIST_TOOL_RESULTS)
    if item_type == "reasoning":
        return cfg.PERSIST_REASONING_TOKENS == "conversation"
    return False


def _extract_usage(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}

    usage = response.get("usage")
    if isinstance(usage, dict):
        return usage

    nested = response.get("response")
    if isinstance(nested, dict):
        nested_usage = nested.get("usage")
        if isinstance(nested_usage, dict):
            return nested_usage

    return {}


def _strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    query_params = parsed.query.split("&")
    filtered = [
        param
        for param in query_params
        if param
        and not param.lower().startswith("utm_")
        and not param.lower().startswith("ref=")
    ]
    return urlunparse(parsed._replace(query="&".join(filtered)))


def _host_from_url(url: str) -> str | None:
    try:
        return urlparse(url).hostname
    except Exception:
        return None


__all__ = ["ResponsesEngine"]
