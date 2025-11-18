"""Tool declaration and execution helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from ..core.openai_requests import ResponseCreateParams
from ..core.errors import ToolExecutionError
from ..model_catalog import supports
from ..utils import get_logger, truncate_for_log

logger = get_logger(__name__)


async def resolve_tools(
    responses_body: ResponseCreateParams,
    valves: Any,
    provided_tools: list[dict[str, Any]] | dict[str, Any] | asyncio.Future | None,
    *,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Normalize OpenWebUI tool inputs and build the Responses tool spec list.

    Returns (tools, tool_registry) where tool_registry is an executable mapping for ResultsEngine.
    """

    resolved = await provided_tools if inspect.isawaitable(provided_tools) else provided_tools
    tool_registry: dict[str, dict[str, Any]] | None = resolved if isinstance(resolved, dict) else None
    tools = build_tools(
        responses_body,
        valves,
        openwebui_tools=tool_registry,
        features=features,
        extra_tools=extra_tools,
    )
    return tools, tool_registry or {}


def build_tools(
    responses_body: ResponseCreateParams,
    valves: Any,
    openwebui_tools: dict[str, Any] | None = None,
    *,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI Responses-API tool spec list for this request."""

    features = features or {}
    if not supports("function_calling", responses_body.model):
        return []

    tools: list[dict[str, Any]] = []
    tools.extend(
        _transform_owui_tools(
            openwebui_tools, strict=getattr(valves, "ENABLE_STRICT_TOOL_CALLING", False)
        )
    )

    allow_web = (
        supports("web_search_tool", responses_body.model)
        and (getattr(valves, "ENABLE_WEB_SEARCH_TOOL", False) or features.get("web_search", False))
        and ((responses_body.reasoning or {}).get("effort", "").lower() != "minimal")
    )
    if allow_web:
        web_search_tool: dict[str, Any] = {"type": "web_search"}
        user_location = getattr(valves, "WEB_SEARCH_USER_LOCATION", None)
        if user_location:
            try:
                web_search_tool["user_location"] = json.loads(user_location)
            except Exception as exc:
                preview, truncated = truncate_for_log(user_location, limit=300)
                logger.warning(
                    "WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring. truncated=%s value=%s error=%s",
                    truncated,
                    preview,
                    exc,
                )
        tools.append(web_search_tool)

    remote_mcp = getattr(valves, "REMOTE_MCP_SERVERS_JSON", None)
    if remote_mcp:
        tools.extend(_build_mcp_tools(remote_mcp))

    if isinstance(extra_tools, list) and extra_tools:
        tools.extend(extra_tools)

    return _dedupe_tools(tools)


async def execute_tool_calls(
    calls: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute tool calls and return Responses-ready outputs."""

    if logger.isEnabledFor(logging.INFO):
        logger.info("tool.calls_started count=%d", len(calls))

    async def _invoke(call: dict[str, Any]) -> tuple[dict[str, Any], str]:
        name = call.get("name")
        arguments_json = call.get("arguments", "{}")
        try:
            args = json.loads(arguments_json)
        except Exception as exc:  # pragma: no cover - defensive
            raise ToolExecutionError(f"Invalid JSON arguments for tool {name}: {exc}") from exc

        if logger.isEnabledFor(logging.DEBUG):
            args_preview, args_truncated = truncate_for_log(
                json.dumps(args, ensure_ascii=False), limit=400
            )
            logger.debug(
                "tool.call name=%s args_truncated=%s args=%s",
                name,
                args_truncated,
                args_preview,
            )

        tool_cfg = registry.get(name)
        if not tool_cfg:
            return call, f"Tool '{name}' not found"

        fn = tool_cfg.get("callable")
        if not callable(fn):
            return call, f"Tool '{name}' is not callable"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("tool.call name=%s status=started", name)

        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.to_thread(fn, **args)
        except Exception as exc:
            logger.warning("Tool %s raised an exception: %s", name, exc)
            return call, f"{type(exc).__name__}: {exc}"

        output_str = str(result)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("tool.call name=%s status=completed output_len=%d", name, len(output_str))
        return call, output_str

    results = await asyncio.gather(*(_invoke(call) for call in calls))
    outputs: list[dict[str, Any]] = []
    for call, output in results:
        outputs.append(
            {
                "type": "function_call_output",
                "call_id": call.get("call_id"),
                "output": output,
            }
        )
    return outputs


def _transform_owui_tools(
    openwebui_tools: dict[str, dict[str, Any]] | None,
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    if not openwebui_tools:
        return []

    tools: list[dict[str, Any]] = []
    for item in openwebui_tools.values():
        spec = item.get("spec") or {}
        name = spec.get("name")
        if not name:
            continue

        params = spec.get("parameters") or {"type": "object", "properties": {}}
        tool = {
            "type": "function",
            "name": name,
            "description": spec.get("description") or name,
            "parameters": _strictify_schema(params) if strict else params,
        }
        if strict:
            tool["strict"] = True
        tools.append(tool)
    return tools


def _strictify_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    data = json.loads(json.dumps(schema))

    def _enforce(node: dict[str, Any]) -> None:
        node_type = node.get("type")
        is_object = (
            node_type == "object"
            or (isinstance(node_type, list) and "object" in node_type)
            or "properties" in node
        )
        if is_object:
            props = node.setdefault("properties", {})
            if not isinstance(props, dict):
                props = {}
                node["properties"] = props

            original_required = set(node.get("required") or [])
            node["additionalProperties"] = False
            node["required"] = list(props.keys())

            for name, prop in props.items():
                if not isinstance(prop, dict):
                    continue
                if name not in original_required:
                    ptype = prop.get("type")
                    if isinstance(ptype, str) and ptype != "null":
                        prop["type"] = [ptype, "null"]
                    elif isinstance(ptype, list) and "null" not in ptype:
                        prop["type"] = [*ptype, "null"]
                _enforce(prop)

        items = node.get("items")
        if isinstance(items, dict):
            _enforce(items)
        elif isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict):
                    _enforce(entry)

        for key in ("anyOf", "oneOf"):
            branches = node.get(key)
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict):
                        _enforce(branch)

    _enforce(data)
    return data


def _build_mcp_tools(mcp_json: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(mcp_json)
    except Exception as exc:  # pragma: no cover - valved bug
        preview, truncated = truncate_for_log(mcp_json, limit=300)
        logger.warning(
            "REMOTE_MCP_SERVERS_JSON is not valid JSON. truncated=%s value=%s error=%s",
            truncated,
            preview,
            exc,
        )
        return []

    entries = parsed if isinstance(parsed, list) else [parsed]
    tools: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        tool = {
            "type": "mcp",
            "server_label": item.get("server_label"),
            "server_url": item.get("server_url"),
        }
        for key in (
            "model_preference",
            "client_capabilities",
            "require_approval",
            "allowed_tools",
        ):
            if key in item:
                tool[key] = item[key]
        tools.append(tool)
    return tools


def _dedupe_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not tools:
        return []

    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    for tool in tools:
        tool_type = tool.get("type")
        if not isinstance(tool_type, str):
            continue
        identifier: str | None = None
        if tool_type == "function":
            name = tool.get("name")
            if isinstance(name, str):
                identifier = name
        seen[(tool_type, identifier)] = tool
    return list(seen.values())


__all__ = [
    "build_tools",
    "execute_tool_calls",
    "resolve_tools",
]
