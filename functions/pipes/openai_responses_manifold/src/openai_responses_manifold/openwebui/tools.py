"""Open WebUI tool registry and executor wrappers."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Iterable

from openai_responses_manifold.domain.tools import ToolDefinition, ToolExecutor, ToolRegistry
from openai_responses_manifold.domain.types import ToolCall, ToolResult


def _normalize_parameters(schema: object) -> dict:
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


class OpenWebUIToolRegistry(ToolRegistry):
    """Wrap ``__tools__`` registry into ``ToolDefinition`` objects."""

    def __init__(self, registry: dict[str, Any]):
        definitions: list[ToolDefinition] = []
        for entry in (registry or {}).values():
            spec = entry.get("spec") if isinstance(entry, dict) else None
            if not isinstance(spec, dict):
                continue
            name = spec.get("name")
            if not isinstance(name, str) or not name:
                continue
            definitions.append(
                ToolDefinition(
                    name=name,
                    description=str(spec.get("description") or ""),
                    parameters=_normalize_parameters(spec.get("parameters")),
                    strict=False,
                    source="registry",
                )
            )
        self._definitions = {d.name: d for d in definitions}

    def get(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def iter_definitions(self) -> Iterable[ToolDefinition]:
        return list(self._definitions.values())


class OpenWebUIToolExecutor(ToolExecutor):
    """Execute tool calls using callables from ``__tools__``."""

    def __init__(self, registry: dict[str, Any]):
        callables: dict[str, Any] = {}
        for entry in (registry or {}).values():
            if not isinstance(entry, dict):
                continue
            name = entry.get("spec", {}).get("name") if isinstance(entry.get("spec"), dict) else None
            fn = entry.get("callable")
            if isinstance(name, str) and name and fn is not None:
                callables[name] = fn
        self._callables = callables

    async def execute(self, calls: list[ToolCall]) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            fn = self._callables.get(call.name)
            if not fn:
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        output="Tool not found",
                        status="error",
                        error_message="Tool not found",
                    )
                )
                continue

            try:
                args = json.loads(call.arguments_json or "{}")
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        output=f"Invalid JSON arguments: {exc}",
                        status="error",
                        error_message=str(exc),
                    )
                )
                continue

            try:
                if inspect.iscoroutinefunction(fn):
                    value = await fn(**args)
                else:
                    value = await asyncio.to_thread(fn, **args)
                output = json.dumps(value, default=str)
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        output=output,
                        status="ok",
                        error_message=None,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        output=f"Tool error: {exc}",
                        status="error",
                        error_message=str(exc),
                    )
                )
        return results


__all__ = ["OpenWebUIToolRegistry", "OpenWebUIToolExecutor"]
