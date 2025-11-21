"""Tool declaration and execution helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any

from openai_responses_manifold.core.logging import get_logger, truncate_for_log
from openai_responses_manifold.core.errors import ToolExecutionError
from openai_responses_manifold.core.model_catalog import supports
from openai_responses_manifold.adapters.openai.requests import ResponseCreateParams
from openai_responses_manifold.domain.web_search import build_web_search_tool

logger = get_logger(__name__)
TOOL_CALL_TIMEOUT_SEC = 30


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

    strict_mode = getattr(valves, "ENABLE_STRICT_TOOL_CALLING", False)
    tools: list[dict[str, Any]] = []
    tools.extend(
        _transform_owui_tools(
            openwebui_tools, strict=strict_mode
        )
    )

    # web_search
    tools.extend(build_web_search_tool(responses_body, valves, features))

    allow_code_interpreter = (
        supports("code_interpreter_tool", responses_body.model)
        and (getattr(valves, "ENABLE_CODE_INTERPRETER_TOOL", False) or features.get("code_interpreter", False))
    )
    if allow_code_interpreter:
        code_tool: dict[str, Any] = {"type": "code_interpreter"}

        feature_cfg = features.get("code_interpreter") if isinstance(features, dict) else None
        container_from_features = feature_cfg.get("container") if isinstance(feature_cfg, dict) else None
        container_json = getattr(valves, "CODE_INTERPRETER_CONTAINER_JSON", None)

        if container_from_features is not None:
            code_tool["container"] = container_from_features
        elif container_json:
            try:
                code_tool["container"] = json.loads(container_json)
            except Exception as exc:
                preview, truncated = truncate_for_log(container_json, limit=300)
                logger.warning(
                    "CODE_INTERPRETER_CONTAINER_JSON is not valid JSON; ignoring. truncated=%s value=%s error=%s",
                    truncated,
                    preview,
                    exc,
                )
        else:
            code_tool["container"] = {"type": "auto"}

        tools.append(code_tool)

    remote_mcp = getattr(valves, "REMOTE_MCP_SERVERS_JSON", None)
    if remote_mcp:
        tools.extend(_build_mcp_tools(remote_mcp))

    if isinstance(extra_tools, list) and extra_tools:
        tools.extend(_maybe_strictify_extra_tools(extra_tools, strict_mode))

    deduped = _dedupe_tools(tools)
    if logger.isEnabledFor(logging.DEBUG):
        summaries = tool_summaries_for_log(deduped)
        logger.debug(
            "tools.built count=%d summary=%s",
            len(deduped),
            "; ".join(summaries) if summaries else "none",
        )
    return deduped


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
                coro = fn(**args)
            else:
                coro = asyncio.to_thread(fn, **args)
            result = await asyncio.wait_for(coro, timeout=TOOL_CALL_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %s seconds", name, TOOL_CALL_TIMEOUT_SEC)
            return call, f"TimeoutError: tool '{name}' exceeded {TOOL_CALL_TIMEOUT_SEC}s"
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

            original_required = [
                item for item in node.get("required") or [] if isinstance(item, str)
            ]
            merged_required: list[str] = []
            for name in original_required:
                if name not in merged_required:
                    merged_required.append(name)
            for name in props.keys():
                if isinstance(name, str) and name not in merged_required:
                    merged_required.append(name)
            node["required"] = merged_required
            node["additionalProperties"] = False

            for name, prop in props.items():
                if not isinstance(prop, dict) or not isinstance(name, str):
                    continue
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


def _maybe_strictify_extra_tools(
    extra_tools: list[dict[str, Any]],
    strict: bool,
) -> list[dict[str, Any]]:
    """Apply strict schemas to extra function tools when strict mode is enabled."""

    if not strict:
        return [tool for tool in extra_tools if isinstance(tool, dict)]

    strictified: list[dict[str, Any]] = []
    for tool in extra_tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            strictified.append(tool)
            continue

        clone: dict[str, Any] = json.loads(json.dumps(tool))
        params = clone.get("parameters")
        if isinstance(params, dict):
            clone["parameters"] = _strictify_schema(params)
        else:
            clone["parameters"] = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        clone.setdefault("strict", True)
        strictified.append(clone)

    return strictified


def tool_summaries_for_log(tools: list[dict[str, Any]]) -> list[str]:
    """Return compact, index-aware summaries for log output."""

    summaries: list[str] = []
    for idx, tool in enumerate(tools or []):
        if not isinstance(tool, dict):
            summaries.append(f"[{idx}] <invalid tool>")
            continue

        tool_type = tool.get("type") or "unknown"
        parts = [f"[{idx}] type={tool_type}"]
        name = tool.get("name")
        if isinstance(name, str) and name:
            parts.append(f"name={name}")

        if tool_type == "function":
            if tool.get("strict"):
                parts.append("strict=True")
            params = tool.get("parameters")
            if isinstance(params, dict):
                props = params.get("properties")
                if isinstance(props, dict) and props:
                    parts.append(f"params={','.join(sorted(props.keys()))}")
        elif tool_type == "web_search":
            context = tool.get("context")
            if isinstance(context, dict):
                size = context.get("size")
                if isinstance(size, str) and size:
                    parts.append(f"context.size={size}")
            filters = tool.get("filters")
            if isinstance(filters, dict):
                allowed = filters.get("allowed_domains")
                if isinstance(allowed, list) and allowed:
                    parts.append(f"filters.allowed_domains={len(allowed)}")
            external = tool.get("external_web_access")
            if isinstance(external, bool):
                parts.append(f"external_web_access={external}")
        elif tool_type == "mcp":
            server_label = tool.get("server_label") or tool.get("server_name")
            if isinstance(server_label, str) and server_label:
                parts.append(f"server_label={server_label}")
            server_url = tool.get("server_url")
            if isinstance(server_url, str) and server_url:
                parts.append(f"server_url={server_url}")
        else:
            extra_keys = [key for key in sorted(tool.keys()) if key != "type"]
            if extra_keys:
                parts.append(f"keys={','.join(extra_keys)}")

        summary = " ".join(parts)
        preview, truncated = truncate_for_log(summary, limit=240)
        summaries.append(f"{preview}{'…' if truncated else ''}")

    return summaries


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
        elif tool_type == "mcp":
            label = tool.get("server_label") or tool.get("server_url")
            if isinstance(label, str):
                identifier = label
        seen[(tool_type, identifier)] = tool
    return list(seen.values())


__all__ = [
    "build_tools",
    "execute_tool_calls",
    "resolve_tools",
]
