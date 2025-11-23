"""Event adapter that maps domain runtime events to Open WebUI."""

from __future__ import annotations

import inspect
from typing import Any, Literal

from openai_responses_manifold.domain.types import RuntimeEvents


class OpenWebUIRuntimeEvents(RuntimeEvents):
    """Wrap ``__event_emitter__`` with the runtime events protocol."""

    def __init__(self, emitter: Any):
        self._emitter = emitter

    async def _emit(self, payload: dict[str, Any]) -> None:
        if not self._emitter:
            return
        if inspect.iscoroutinefunction(self._emitter):
            await self._emitter(payload)
            return
        result = self._emitter(payload)
        if inspect.isawaitable(result):
            await result

    async def status(self, description: str, *, done: bool = False, **extra: Any) -> None:
        await self._emit({"type": "status", "data": {"description": description, "done": done, **extra}})

    async def delta(self, content: str) -> None:
        await self._emit(
            {"type": "chat:message:delta", "data": {"role": "assistant", "content": content}}
        )

    async def replace(self, content: str) -> None:
        await self._emit(
            {"type": "chat:message", "data": {"role": "assistant", "content": content}}
        )

    async def citation(self, data: dict[str, Any]) -> None:
        await self._emit({"type": "citation", "data": data})

    async def source(self, data: dict[str, Any]) -> None:
        await self._emit({"type": "source", "data": data})

    async def chat_completion(self, data: dict[str, Any]) -> None:
        await self._emit({"type": "chat:completion", "data": data})

    async def notification(
        self,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        await self._emit({"type": "notification", "data": {"type": level, "content": content}})


__all__ = ["OpenWebUIRuntimeEvents"]
