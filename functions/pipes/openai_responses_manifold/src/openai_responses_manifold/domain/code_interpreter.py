"""Helpers for handling code interpreter events and output items."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from openai_responses_manifold.adapters.openai.events import (
    ResponseCodeInterpreterCallCodeDeltaEvent,
    ResponseCodeInterpreterCallCodeDoneEvent,
    ResponseCodeInterpreterCallCompletedEvent,
    ResponseCodeInterpreterCallInProgressEvent,
    ResponseCodeInterpreterCallInterpretingEvent,
)
from openai_responses_manifold.domain.events import RuntimeEvents
from openai_responses_manifold.core.logging import truncate_for_log

EmitStatusFn = Callable[[str], Awaitable[Any]]


async def handle_code_interpreter_event(
    event: Any,
    state: Any,
    emit_status: Callable[[str], Awaitable[Any]],
    logger: logging.Logger,
) -> bool:
    """Handle streaming code interpreter events. Returns True if the stream should stop."""

    if isinstance(event, ResponseCodeInterpreterCallInProgressEvent):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("code_interpreter.event in_progress output_index=%s", event.output_index)
        state.last_code_output_index = event.output_index
        await emit_status("Starting code interpreter…")
        return False

    if isinstance(event, ResponseCodeInterpreterCallInterpretingEvent):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("code_interpreter.event interpreting output_index=%s", event.output_index)
        await emit_status("Running Python code in the sandbox…")
        return False

    if isinstance(event, ResponseCodeInterpreterCallCodeDeltaEvent):
        return False

    if isinstance(event, ResponseCodeInterpreterCallCodeDoneEvent):
        code = (event.code or "").strip()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "code_interpreter.event code_done output_index=%s code_len=%d",
                event.output_index,
                len(code),
            )
        if event.output_index is not None:
            state.code_snippets[event.output_index] = code or state.code_snippets.get(event.output_index)
            state.last_code_output_index = event.output_index
        if code:
            await emit_status(
                f"Executed Python:\n```python\n{code}\n```",
                hidden=True,
                require_previous=True,
            )
        return False

    if isinstance(event, ResponseCodeInterpreterCallCompletedEvent):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("code_interpreter.event completed output_index=%s", event.output_index)
        await emit_status("Code interpreter run finished.", require_previous=True)
        return False

    return False


async def handle_code_interpreter_item(
    item: dict[str, Any],
    state: Any,
    events: RuntimeEvents,
    logger: logging.Logger,
    emit_status: Callable[..., Awaitable[Any]],
    *,
    output_index: int | None = None,
) -> None:
    """Handle a completed code_interpreter_call output item."""

    # Support both the OpenAI item shape (flat fields) and the previously nested shape
    ci_payload = item.get("code_interpreter_call") if isinstance(item.get("code_interpreter_call"), dict) else item
    outputs = (ci_payload.get("outputs") if isinstance(ci_payload, dict) else None) or item.get("outputs") or []
    run_index = output_index if output_index is not None else state.last_code_output_index
    log_chunks: list[str] = []
    other_outputs: list[str] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        output_type = output.get("type")
        if output_type == "logs":
            logs = output.get("logs")
            if isinstance(logs, str) and logs.strip():
                log_chunks.append(logs.strip())
            continue

        if output_type == "image":
            image = output.get("image") or {}
            file_id = image.get("file_id") or output.get("file_id") or output.get("file")
            filename = image.get("filename")
            desc = f"image: file_id={file_id}" if file_id else "image output"
            if filename:
                desc += f" ({filename})"
            other_outputs.append(desc)
            continue

        if output_type == "file":
            file_id = output.get("file_id") or output.get("file")
            filename = output.get("filename")
            desc = f"file: file_id={file_id}" if file_id else "file output"
            if filename:
                desc += f" ({filename})"
            other_outputs.append(desc)
            continue

        if output_type in ("text", "result", "data"):
            data_val = output.get("text") or output.get("result") or output.get("data")
            if data_val is not None:
                preview, truncated = truncate_for_log(data_val, 400)
                suffix = " …(truncated)" if truncated else ""
                other_outputs.append(f"{output_type}: {preview}{suffix}")
            continue

        keys = ", ".join(sorted(k for k in output.keys() if k != "type"))
        other_outputs.append(f"{output_type or 'output'} ({keys})")

    if log_chunks:
        logs_snippet = "\n".join(log_chunks)
        await emit_status(
            "Code interpreter logs:\n" + logs_snippet,
            hidden=True,
            require_previous=True,
        )

    code_snippet = (ci_payload.get("code") or item.get("code") or "").strip()
    if not code_snippet and run_index is not None:
        cached_code = state.code_snippets.get(run_index)
        if cached_code:
            code_snippet = cached_code
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "code_interpreter_call using fallback code snippet output_index=%s len=%d",
                    run_index,
                    len(code_snippet),
                )

    assistant_answer = (state.response_text or "").strip()
    pending_result = not (log_chunks or other_outputs or assistant_answer)

    # Emit a consolidated citation so users see logs/outputs/code (and result text if already present).
    snippet_parts: list[str] = []
    if log_chunks:
        snippet_parts.append("Logs:\n" + "\n".join(log_chunks))
    if other_outputs:
        snippet_parts.append("Outputs:\n- " + "\n- ".join(other_outputs))
    if assistant_answer and not pending_result:
        snippet_parts.append("Result:\n" + assistant_answer)
    if code_snippet:
        snippet_parts.append("Code:\n" + code_snippet)
    if not snippet_parts:
        snippet_parts.append(
            "Code interpreter returned no structured outputs yet. The assistant will share the result in text."
        )

    result_snippet = "\n\n".join(snippet_parts)
    citation = {
        "provider": "openai:code_interpreter",
        "id": f"ci-{len(state.citations) + 1}",
        "title": "Code interpreter run",
        "snippet": result_snippet,
        "metadata": {
            "item_type": "code_interpreter_call",
            "kind": "run",
            "has_logs": bool(log_chunks),
            "has_code": bool(code_snippet),
            "has_outputs": bool(other_outputs),
            "has_result_text": bool(assistant_answer and not pending_result),
            "pending_result_text": pending_result,
            "output_index": run_index,
        },
    }
    state.citations.append(citation)
    await events.citation(
        {
            "document": [result_snippet],
            "metadata": [citation["metadata"]],
            "source": {"name": citation["title"]},
        }
    )

    # Track pending results per run so we can emit a second citation once the assistant text arrives.
    if run_index is not None:
        if pending_result:
            state.pending_ci_results.add(run_index)
            if code_snippet:
                state.pending_ci_code_snippets[run_index] = code_snippet
        else:
            state.pending_ci_results.discard(run_index)
            state.pending_ci_code_snippets.pop(run_index, None)

        # Clear cached snippet after consumption (the pending copy, if any, is stored above)
        state.code_snippets.pop(run_index, None)

    if (
        not log_chunks
        and not code_snippet
        and logger.isEnabledFor(logging.DEBUG)
    ):
        logger.debug(
            "code_interpreter_call item had no logs/code; outputs_len=%d",
            len(outputs),
        )


async def emit_pending_code_interpreter_result(
    state: Any,
    events: RuntimeEvents,
    logger: logging.Logger,
    assistant_text: str | None = None,
) -> None:
    """Emit a follow-up citation with the assistant's result text when no structured outputs were returned."""

    if not getattr(state, "pending_ci_results", None):
        return

    result_text = (assistant_text or state.response_text or "").strip()
    if not result_text:
        return

    pending_indices = list(state.pending_ci_results)
    for run_index in pending_indices:
        code_snippet = state.pending_ci_code_snippets.get(run_index)
        snippet_parts = [f"Result:\n{result_text}"]
        if code_snippet:
            snippet_parts.append(f"Code:\n{code_snippet}")

        snippet = "\n\n".join(snippet_parts)
        citation = {
            "provider": "openai:code_interpreter",
            "id": f"ci-{len(state.citations) + 1}",
            "title": "Code interpreter result",
            "snippet": snippet,
            "metadata": {
                "item_type": "code_interpreter_call",
                "kind": "result",
                "has_logs": False,
                "has_code": bool(code_snippet),
                "has_outputs": False,
                "has_result_text": True,
                "pending_result_text": False,
                "output_index": run_index,
            },
        }
        state.citations.append(citation)
        await events.citation(
            {
                "document": [snippet],
                "metadata": [citation["metadata"]],
                "source": {"name": citation["title"]},
            }
        )

        state.pending_ci_results.discard(run_index)
        state.pending_ci_code_snippets.pop(run_index, None)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("code_interpreter result citation emitted len=%d", len(snippet))


__all__ = [
    "handle_code_interpreter_event",
    "handle_code_interpreter_item",
    "emit_pending_code_interpreter_result",
]
