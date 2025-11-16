"""General-purpose helpers shared across modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def wrap_event_emitter(
    emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
    *,
    suppress_chat_messages: bool = False,
    suppress_completion: bool = False,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
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
