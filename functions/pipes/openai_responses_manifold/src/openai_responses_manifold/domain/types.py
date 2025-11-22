"""Shared domain types for the OpenAI Responses engine and adapters.

This module hosts turn-level context objects, per-turn state,
tool call/result containers, citation payloads, and the runtime
events protocol used by the engine and adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from ..core.config import RuntimeConfig


@dataclass
class TurnContext:
    """Context passed across the engine, history manager, and adapters."""

    runtime_config: RuntimeConfig
    model_id: str
    features: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnState:
    """Mutable per-turn state maintained by the engine."""

    assistant_visible_text: str = ""
    assistant_internal_text: str = ""
    response_text: str = ""
    usage: dict | None = None
    citations: list["Citation"] = field(default_factory=list)
    structured_items: list[dict] = field(default_factory=list)
    tool_calls_executed: int = 0
    error_message: str | None = None
    citation_ordinals: dict[str, int] = field(default_factory=dict)
    last_code_output_index: int | None = None
    code_snippets: dict[int, str] = field(default_factory=dict)
    pending_ci_results: set[int] = field(default_factory=set)
    pending_ci_code_snippets: dict[int, str] = field(default_factory=dict)


@dataclass
class ToolCall:
    """Represents a function/tool call request emitted by the model."""

    call_id: str
    name: str
    arguments_json: str


@dataclass
class ToolResult:
    """Result of executing a tool call."""

    call_id: str
    output: str
    status: Literal["ok", "error", "timeout"]
    error_message: str | None = None


@dataclass
class Citation:
    """Citation payload derived from url_citation annotations."""

    source_name: str
    url: str | None
    document: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    """Final result returned by the engine after a streaming turn."""

    text: str
    usage: dict | None = None
    citations: list[Citation] = field(default_factory=list)
    error: str | None = None


@runtime_checkable
class RuntimeEvents(Protocol):
    """Protocol for runtime event sinks used by the engine."""

    async def status(self, description: str, *, done: bool = False, **extra: Any) -> None:
        ...

    async def delta(self, content: str) -> None:
        ...

    async def replace(self, content: str) -> None:
        ...

    async def citation(self, data: dict[str, Any]) -> None:
        ...

    async def source(self, data: dict[str, Any]) -> None:
        ...

    async def chat_completion(self, data: dict[str, Any]) -> None:
        ...

    async def notification(
        self,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        ...


__all__ = [
    "TurnContext",
    "TurnState",
    "ToolCall",
    "ToolResult",
    "Citation",
    "TurnResult",
    "RuntimeEvents",
]
