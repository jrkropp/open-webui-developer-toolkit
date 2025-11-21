"""UI-agnostic interface for runtime events consumed by the engine."""

from __future__ import annotations

from typing import Any, Literal, Protocol


class RuntimeEvents(Protocol):
    async def status(self, description: str, *, done: bool = False, hidden: bool = False) -> None: ...

    async def delta(self, content: str) -> None: ...

    async def replace(self, content: str) -> None: ...

    async def citation(self, data: dict[str, Any]) -> None: ...

    async def files(self, files: list[dict[str, Any]]) -> None: ...

    async def chat_completion(self, data: dict[str, Any]) -> None: ...

    async def notification(
        self,
        content: str,
        *,
        level: Literal["info", "success", "error", "warning"] = "info",
    ) -> None: ...


class NullRuntimeEvents:
    """No-op implementation useful for tests or non-UI contexts."""

    async def status(self, description: str, *, done: bool = False, hidden: bool = False) -> None:
        return None

    async def delta(self, content: str) -> None:
        return None

    async def replace(self, content: str) -> None:
        return None

    async def citation(self, data: dict[str, Any]) -> None:
        return None

    async def files(self, files: list[dict[str, Any]]) -> None:
        return None

    async def chat_completion(self, data: dict[str, Any]) -> None:
        return None

    async def notification(
        self,
        content: str,
        *,
        level: Literal["info", "success", "error", "warning"] = "info",
    ) -> None:
        return None


__all__ = ["RuntimeEvents", "NullRuntimeEvents"]
