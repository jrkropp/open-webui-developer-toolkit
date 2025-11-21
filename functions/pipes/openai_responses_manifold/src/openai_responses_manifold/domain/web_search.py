"""Helpers for web_search tool construction and request policy."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai_responses_manifold.core.logging import get_logger, truncate_for_log
from openai_responses_manifold.core.model_catalog import supports

logger = get_logger(__name__)


def build_web_search_tool(
    responses_body: Any,
    valves: Any,
    features: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a list with a web_search tool if enabled/supported, otherwise []."""

    features = features or {}
    reasoning = responses_body.reasoning if isinstance(responses_body.reasoning, dict) else {}
    effort = reasoning.get("effort")
    effort_level = effort.lower() if isinstance(effort, str) else ""
    allow_web = (
        supports("web_search_tool", responses_body.model)
        and (getattr(valves, "ENABLE_WEB_SEARCH_TOOL", False) or features.get("web_search", False))
        and effort_level != "minimal"
    )
    if not allow_web:
        return []

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
    allowed_domains = _parse_allowed_domains(getattr(valves, "WEB_SEARCH_ALLOWED_DOMAINS", None))
    if allowed_domains:
        web_search_tool["filters"] = {"allowed_domains": allowed_domains}
    external_web_access = getattr(valves, "WEB_SEARCH_EXTERNAL_WEB_ACCESS", None)
    if isinstance(external_web_access, bool):
        web_search_tool["external_web_access"] = external_web_access

    return [web_search_tool]


def apply_web_search_policy(responses_body: Any, valves: Any) -> bool:
    """
    Enforce parallel/tool include policy for web_search.

    Returns True if web_search is present and policy applied.
    """

    has_web_search = any(
        isinstance(tool, dict) and tool.get("type") == "web_search"
        for tool in (responses_body.tools or [])
    )
    if not has_web_search:
        return False

    responses_body.parallel_tool_calls = False
    if getattr(valves, "WEB_SEARCH_INCLUDE_SOURCES", True):
        responses_body.include = responses_body.include or []
        if "web_search_call.action.sources" not in responses_body.include:
            responses_body.include.append("web_search_call.action.sources")
    return True


def _parse_allowed_domains(raw: Any) -> list[str]:
    """
    Normalize allowed domain inputs for the web_search tool.

    Accepts JSON (list or string) or comma-separated strings. Removes protocols and trailing slashes.
    Caps the allow-list at 20 entries, preserving order.
    """

    if raw is None:
        return []

    candidates: list[Any] = []
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, str):
            candidates = [parsed]
        elif parsed is None:
            candidates = raw.split(",")
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []

    normalized: list[str] = []
    for cand in candidates:
        if not isinstance(cand, str):
            continue
        domain = _normalize_domain(cand)
        if not domain or domain in normalized:
            continue
        normalized.append(domain)
        if len(normalized) >= 20:
            break
    return normalized


def _normalize_domain(domain: str) -> str:
    """Strip protocol/path and whitespace from a domain string."""

    cleaned = domain.strip()
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split("/")[0]
    return cleaned.rstrip("/")


__all__ = ["build_web_search_tool", "apply_web_search_policy"]
