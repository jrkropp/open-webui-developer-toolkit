"""Build ResponseCreateParams from OpenWebUI-style inputs."""

from __future__ import annotations

from typing import Any

from openai_responses_manifold.core.logging import get_logger
from openai_responses_manifold.adapters.openai.requests import ResponseCreateParams
from openai_responses_manifold.adapters.openwebui.store import ItemStore
from openai_responses_manifold.domain.history import HistoryService

logger = get_logger(__name__)


async def build_responses_body(
    owui_request: dict[str, Any],
    *,
    valves: Any,
    metadata: dict[str, Any],
    user_identifier: str | None = None,
    item_store: ItemStore,
) -> ResponseCreateParams:
    """
    Convert an OpenWebUI-style payload plus valves/metadata into a validated ResponsesBody.
    """

    payload: dict[str, Any] = {"stream": True, "store": False}

    default_model = getattr(valves, "MODEL_ID", "") or ""
    default_model = default_model.split(",")[0].strip() if default_model else ""
    model_id = owui_request.get("model") or (default_model or None)
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

    passthrough_keys = [
        "tool_choice",
        "store",
        "background",
        "include",
        "metadata",
        "text",
        "service_tier",
        "prompt_cache_key",
        "prompt_cache_retention",
        "previous_response_id",
        "conversation",
        "prompt",
        "stream_options",
        "include_obfuscation",
    ]
    for key in passthrough_keys:
        if key in owui_request:
            payload[key] = owui_request[key]

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

    if instructions and instructions.strip():
        payload["instructions"] = instructions

    effort = owui_request.get("reasoning_effort")
    if effort:
        reasoning = payload.get("reasoning") or {}
        reasoning["effort"] = effort
        payload["reasoning"] = reasoning

    if "max_tool_calls" in owui_request:
        payload["max_tool_calls"] = owui_request.get("max_tool_calls")
    elif getattr(valves, "MAX_TOOL_CALLS", None) is not None:
        payload["max_tool_calls"] = valves.MAX_TOOL_CALLS

    if user_identifier:
        payload["user"] = user_identifier
    elif metadata.get("user_id"):
        payload["user"] = metadata["user_id"]

    try:
        responses_body = ResponseCreateParams.model_validate(payload)
    except Exception as exc:
        logger.error("Failed to build ResponseCreateParams: %s payload_keys=%s", exc, list(payload.keys()))
        raise

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
