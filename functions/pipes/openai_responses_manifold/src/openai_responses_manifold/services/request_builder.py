"""Build ResponsesBody requests from OpenWebUI-style inputs."""

from __future__ import annotations

from typing import Any

from ..core.openai_requests import ResponseCreateParams
from ..infra import ItemStore
from ..services.history import HistoryService
from ..services.tools import resolve_tools
from ..utils import get_logger

logger = get_logger(__name__)


async def build_responses_body(
    owui_request: dict[str, Any],
    *,
    valves: Any,
    metadata: dict[str, Any],
    user_identifier: str | None = None,
    item_store: ItemStore,
    provided_tools: list[dict[str, Any]] | dict[str, Any] | None = None,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict[str, Any]] | None = None,
) -> ResponseCreateParams:
    """
    Convert an OpenWebUI-style payload plus valves/metadata into a validated ResponsesBody.
    """

    payload: dict[str, Any] = {"stream": True, "store": False}

    model_id = owui_request.get("model") or getattr(valves, "MODEL_ID", None)
    if not model_id:
        raise ValueError("model is required for ResponsesBody")
    payload["model"] = model_id
    payload["truncation"] = owui_request.get("truncation", getattr(valves, "TRUNCATION", None))
    payload["parallel_tool_calls"] = owui_request.get(
        "parallel_tool_calls", getattr(valves, "PARALLEL_TOOL_CALLS", True)
    )
    if "temperature" in owui_request:
        payload["temperature"] = owui_request.get("temperature")
    if "top_p" in owui_request:
        payload["top_p"] = owui_request.get("top_p")
    if "max_output_tokens" in owui_request:
        payload["max_output_tokens"] = owui_request.get("max_output_tokens")
    elif "max_tokens" in owui_request:
        payload["max_output_tokens"] = owui_request.get("max_tokens")

    messages = owui_request.get("messages") or []
    provided_input = owui_request.get("input")
    instructions = owui_request.get("instructions") or _extract_system_instructions(messages)

    if provided_input is None and messages:
        history_service = HistoryService(item_store)
        provided_input, inferred_instructions = history_service.build_input_and_instructions(
            messages,
            metadata=metadata,
        )
        if not instructions:
            instructions = inferred_instructions

    payload["input"] = provided_input
    if payload["input"] is None:
        raise ValueError("input must be provided to build a ResponsesBody")

    if instructions:
        payload["instructions"] = instructions

    effort = owui_request.get("reasoning_effort")
    if effort:
        reasoning = payload.get("reasoning") or {}
        reasoning["effort"] = effort
        payload["reasoning"] = reasoning

    if user_identifier:
        payload["user"] = user_identifier
    elif metadata.get("user_id"):
        payload["user"] = metadata["user_id"]

    try:
        responses_body = ResponseCreateParams.model_validate(payload)
    except Exception as exc:
        logger.error("Failed to build ResponseCreateParams: %s payload_keys=%s", exc, list(payload.keys()))
        raise

    tools, _tool_registry = await resolve_tools(
        responses_body,
        valves,
        provided_tools if provided_tools is not None else owui_request.get("tools"),
        features=features or metadata.get("features", {}).get("openai_responses", {}),
        extra_tools=extra_tools or owui_request.get("extra_tools"),
    )
    if tools:
        responses_body.tools = tools
    return responses_body


def _extract_system_instructions(messages: list[dict[str, Any]]) -> str | None:
    """Return the most recent system message content, if present."""

    for message in reversed(messages):
        if message.get("role") == "system":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return None


__all__ = ["build_responses_body"]
