"""Adapter that maps the domain RuntimeEvents protocol to Open WebUI's emitter."""

from __future__ import annotations

from typing import Any

from openai_responses_manifold.domain.events import RuntimeEvents

from .events import EventEmitter


class OpenWebUIRuntimeEvents(RuntimeEvents):
    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter

    async def status(self, description: str, *, done: bool = False, hidden: bool = False) -> None:
        await self._emitter.status(description, done=done, hidden=hidden)

    async def delta(self, content: str) -> None:
        await self._emitter.delta(content)

    async def replace(self, content: str) -> None:
        await self._emitter.replace(content)

    async def citation(self, data: dict[str, Any]) -> None:
        await self._emitter.citation(data)

    async def files(self, files: list[dict[str, Any]]) -> None:
        await self._emitter.files(files)

    async def chat_completion(self, data: dict[str, Any]) -> None:
        await self._emitter.chat_completion(data)

    async def notification(self, content: str, *, level: str = "info") -> None:
        await self._emitter.notification(content, level=level)


__all__ = ["OpenWebUIRuntimeEvents"]
