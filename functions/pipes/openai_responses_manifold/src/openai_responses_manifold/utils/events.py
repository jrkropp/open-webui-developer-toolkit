"""Utility functions for emitting OpenWebUI events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


def wrap_event_emitter(
    emitter: EventEmitter | None,
    *,
    suppress_chat_messages: bool = False,
    suppress_completion: bool = False,
) -> EventEmitter:
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


async def emit_status(
    emitter: EventEmitter | None,
    description: str,
    *,
    action: str | None = None,
    **extra: Any,
) -> None:
    if emitter is None:
        return
    payload = {"description": description}
    if action:
        payload["action"] = action
    payload.update(extra)
    await emitter({"type": "status", "data": payload})


async def emit_chat_message(
    emitter: EventEmitter | None,
    content: str,
    *,
    options: dict[str, Any] | None = None,
) -> None:
    if emitter is None:
        return
    payload = {"content": content}
    if options:
        payload["options"] = options
    await emitter({"type": "chat:message", "data": payload})


async def emit_completion(
    emitter: EventEmitter | None,
    *,
    content: str | None = "",
    title: str | None = None,
    usage: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    done: bool = True,
) -> None:
    if emitter is None:
        return
    data: dict[str, Any] = {"done": done}
    if content is not None:
        data["content"] = content
    if title is not None:
        data["title"] = title
    if usage is not None:
        data["usage"] = usage
    if error is not None:
        data["error"] = error
    await emitter({"type": "chat:completion", "data": data})


async def emit_usage_delta(
    emitter: EventEmitter | None,
    usage: dict[str, Any],
) -> None:
    if emitter is None or not usage:
        return
    await emitter({"type": "usage", "data": usage})


async def emit_citation(
    emitter: EventEmitter | None,
    document: str | list[str],
    source_name: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    if emitter is None:
        return
    if isinstance(document, list):
        doc_text = "\n".join(document)
    else:
        doc_text = document
    await emitter(
        {
            "type": "citation",
            "data": {
                "document": [doc_text],
                "metadata": [
                    {
                        "source": source_name,
                        **(metadata or {}),
                    }
                ],
                "source": {"name": source_name},
            },
        }
    )


async def emit_error(
    emitter: EventEmitter | None,
    message: str,
    *,
    done: bool = False,
) -> None:
    """Emit a standard error completion event."""

    await emit_completion(emitter, error={"message": message}, done=done)


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


__all__ = [
    "EventEmitter",
    "emit_chat_message",
    "emit_citation",
    "emit_completion",
    "emit_error",
    "emit_status",
    "emit_usage_delta",
    "merge_usage_stats",
    "wrap_code_block",
    "wrap_event_emitter",
]
