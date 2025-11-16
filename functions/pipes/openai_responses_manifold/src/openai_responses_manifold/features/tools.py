"""Helpers for constructing OpenAI tool payloads."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..core import ResponsesBody, supports

logger = logging.getLogger(__name__)


def build_tools(
    responses_body: ResponsesBody,
    valves: Any,
    __tools__: dict[str, Any] | None = None,
    *,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI Responses-API tool spec list for this request."""

    features = features or {}
    if not supports("function_calling", responses_body.model):
        return []

    tools: list[dict[str, Any]] = []

    if isinstance(__tools__, dict) and __tools__:
        tools.extend(
            ResponsesBody.transform_owui_tools(
                __tools__,
                strict=getattr(valves, "ENABLE_STRICT_TOOL_CALLING", False),
            )
        )

    allow_web = (
        supports("web_search_tool", responses_body.model)
        and (getattr(valves, "ENABLE_WEB_SEARCH_TOOL", False) or features.get("web_search", False))
        and ((responses_body.reasoning or {}).get("effort", "").lower() != "minimal")
    )
    if allow_web:
        web_search_tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": getattr(valves, "WEB_SEARCH_CONTEXT_SIZE", "medium"),
        }
        user_location = getattr(valves, "WEB_SEARCH_USER_LOCATION", None)
        if user_location:
            try:
                web_search_tool["user_location"] = json.loads(user_location)
            except Exception as exc:
                logger.warning("WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring: %s", exc)
        tools.append(web_search_tool)

    remote_mcp = getattr(valves, "REMOTE_MCP_SERVERS_JSON", None)
    if remote_mcp:
        tools.extend(ResponsesBody._build_mcp_tools(remote_mcp))

    if isinstance(extra_tools, list) and extra_tools:
        tools.extend(extra_tools)

    return _dedupe_tools(tools)


def _dedupe_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Deduplicate tool entries by (type, name) identity."""

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
