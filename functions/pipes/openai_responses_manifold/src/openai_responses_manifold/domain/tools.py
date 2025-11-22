"""Tool definitions, registry/executor interfaces, and merge policy.

This module translates tool definitions from multiple sources into the
OpenAI Responses ``tools`` array while enforcing capability gating,
strict JSON Schema handling, and deterministic deduplication. See
``docs/tools_and_extra_tools.md`` for the authoritative contract.
"""

from __future__ import annotations

from copy import deepcopy
from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol

from openai_responses_manifold.core.config import RuntimeConfig
from openai_responses_manifold.core.model_catalog import supports

from .types import ToolCall, ToolResult


@dataclass
class ToolDefinition:
    """Internal representation of a tool definition."""

    name: str
    description: str
    parameters: dict
    strict: bool
    source: Literal["registry", "filter", "body", "mcp", "builtin"]


class ToolRegistry(Protocol):
    def get(self, name: str) -> ToolDefinition | None:
        ...

    def iter_definitions(self) -> Iterable[ToolDefinition]:
        ...


class ToolExecutor(Protocol):
    async def execute(self, calls: list[ToolCall]) -> list[ToolResult]:
        ...


def _ensure_object_schema(schema: object) -> dict:
    if isinstance(schema, dict):
        return deepcopy(schema)
    return {"type": "object", "properties": {}}


def _make_nullable(type_value: object) -> object:
    if isinstance(type_value, list):
        if "null" in type_value:
            return type_value
        return [*type_value, "null"]
    if isinstance(type_value, str):
        if type_value == "null":
            return type_value
        return [type_value, "null"]
    return type_value


def _strictify_schema(schema: dict) -> dict:
    """Recursively enforce strict JSON Schema semantics for objects."""

    schema = _ensure_object_schema(schema)
    schema_type = schema.get("type")
    if schema_type == "object" or (
        isinstance(schema_type, list) and "object" in schema_type
    ):
        properties = schema.get("properties")
        original_required = set(schema.get("required") or [])
        if not isinstance(properties, dict):
            properties = {}

        strict_props: dict[str, dict] = {}
        required: list[str] = []
        for prop_name, prop_schema in properties.items():
            strict_prop = _strictify_schema(prop_schema)
            if prop_name not in original_required:
                current_type = strict_prop.get("type")
                strict_prop["type"] = _make_nullable(current_type)
            strict_props[prop_name] = strict_prop
            required.append(prop_name)

        schema["properties"] = strict_props
        schema["required"] = required
        schema["additionalProperties"] = False

    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = _strictify_schema(items)

    return schema


def _tool_identity(tool: dict) -> tuple[str | None, str | None]:
    tool_type = tool.get("type")
    name = tool.get("name") if tool_type == "function" else None
    return (str(tool_type) if tool_type is not None else None, name)


def _sanitize_tool(tool: dict) -> dict:
    sanitized = deepcopy(tool)
    params = sanitized.get("parameters")
    if not isinstance(params, dict):
        sanitized["parameters"] = {"type": "object", "properties": {}}
    return sanitized


def _definition_to_tool(defn: ToolDefinition) -> dict:
    return {
        "type": "function",
        "name": defn.name,
        "description": defn.description,
        "parameters": _ensure_object_schema(defn.parameters),
        "strict": defn.strict,
        "source": defn.source,
    }


class ToolPolicy:
    """Policy for building the OpenAI ``tools`` array for a turn."""

    @staticmethod
    def build_responses_tools(
        model_id: str,
        features: set[str],
        cfg: RuntimeConfig,
        registry: ToolRegistry,
        body_tools: list[dict] | None,
        extra_tools: list[dict] | None,
        mcp_tools: list[dict] | None,
        web_search_tools: list[dict] | None,
    ) -> list[dict]:
        allow_function_tools = "function_calling" in features or supports(
            "function_calling", model_id
        )
        allow_web_search_tools = "web_search_tool" in features or supports(
            "web_search_tool", model_id
        )

        ordered_tools: list[dict] = []

        def extend_tools(candidates: Iterable[dict]) -> None:
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                ordered_tools.append(deepcopy(candidate))

        extend_tools(body_tools or [])
        extend_tools(_definition_to_tool(d) for d in registry.iter_definitions())
        extend_tools(extra_tools or [])
        extend_tools(mcp_tools or [])
        extend_tools(web_search_tools or [])

        deduped: dict[tuple[str | None, str | None], dict] = {}
        for raw_tool in ordered_tools:
            tool = _sanitize_tool(raw_tool)

            tool_type = tool.get("type")
            if tool_type == "function" and not allow_function_tools:
                continue
            if tool_type == "web_search" and not allow_web_search_tools:
                continue

            if tool_type == "function" and cfg.ENABLE_STRICT_TOOL_CALLING:
                tool["parameters"] = _strictify_schema(tool.get("parameters"))
                tool["strict"] = True
            identity = _tool_identity(tool)
            if identity in deduped:
                deduped.pop(identity, None)
            deduped[identity] = tool

        return list(deduped.values())


__all__ = [
    "ToolDefinition",
    "ToolRegistry",
    "ToolExecutor",
    "ToolPolicy",
]
