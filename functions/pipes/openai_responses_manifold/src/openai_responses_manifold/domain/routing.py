"""Routing helpers for GPT-5 pseudo-models.

This module provides a small helper that resolves Open WebUI router
pseudo-models (e.g. ``.gpt-5-auto-dev``) into concrete OpenAI models.
See ``docs/routing_and_model_catalog.md`` for behavior details.
"""

from __future__ import annotations

import json
from typing import Any

from ..core import base_model, normalize, supports
from ..core.logging import get_logger
from ..openai_api.client import OpenAIClient
from ..openai_api.types import ResponsesRequest
from .types import RuntimeEvents, TurnContext

logger = get_logger("openai_responses_manifold.routing")


def _extract_output_text(response: dict[str, Any]) -> str:
    for item in reversed(response.get("output", [])):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str):
                    return text
    return ""


def _parse_decision(raw: str) -> dict[str, Any]:
    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return {}
    except Exception:  # pragma: no cover - defensive
        return {}
    return {}


async def route_auto_model(
    client: OpenAIClient,
    request: ResponsesRequest,
    ctx: TurnContext,
    tools: list[dict],
    events: RuntimeEvents,
) -> ResponsesRequest:
    """Route GPT-5 auto pseudo-models to concrete models.

    * ``.gpt-5-auto`` is treated as a temporary alias to
      ``gpt-5.1-chat-latest`` with a notification.
    * ``.gpt-5-auto-dev`` triggers a router call using a fast model and
      applies the router's chosen model/reasoning effort when valid.
    * On any error, the original request is returned unchanged.
    """

    owui_model_id = ctx.metadata.get("owui_model_id")
    if not isinstance(owui_model_id, str):
        return request

    request.model = base_model(request.model)
    normalized = normalize(owui_model_id)

    if normalized.endswith("gpt-5-auto"):
        request.model = "gpt-5.1-chat-latest"
        await events.notification(
            "Model router coming soon — using gpt‑5.1‑chat‑latest for now.",
            level="info",
        )
        return request

    if not normalized.endswith("gpt-5-auto-dev"):
        return request

    router_request = ResponsesRequest(
        model="gpt-5-mini",
        input=request.input,
        instructions=(
            "You are a routing assistant. Choose the best GPT-5 model for the "
            "user request and available tools. Prefer gpt-5.1-chat-latest for "
            "general chat, gpt-5 for complex reasoning, and gpt-5-mini for "
            "simple or tool-heavy tasks."
        ),
        reasoning={"effort": "minimal"},
        text={
            "format": {
                "type": "json_schema",
                "name": "gpt5_router",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "enum": ["gpt-5.1-chat-latest", "gpt-5", "gpt-5-mini"],
                        },
                        "reasoning_effort": {
                            "type": "string",
                            "enum": ["minimal", "low", "medium", "high"],
                        },
                        "explanation": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 500,
                        },
                    },
                    "required": ["model", "reasoning_effort", "explanation"],
                    "additionalProperties": False,
                },
                "verbosity": "medium",
            }
        },
    )

    try:
        router_response = await client.create_response(
            router_request,
            base_url=ctx.runtime_config.BASE_URL,
            api_key=ctx.runtime_config.API_KEY,
        )
    except Exception:
        logger.warning("Model router request failed", exc_info=True)
        return request

    decision = _parse_decision(_extract_output_text(router_response))
    model = decision.get("model") if isinstance(decision, dict) else None
    effort = decision.get("reasoning_effort") if isinstance(decision, dict) else None
    explanation = decision.get("explanation") if isinstance(decision, dict) else None

    if not (isinstance(model, str) and isinstance(effort, str) and isinstance(explanation, str)):
        return request

    request.model = model

    if supports("reasoning", model):
        reasoning = dict(request.reasoning or {})
        reasoning["effort"] = effort
        request.reasoning = reasoning

    request.model_router_result = {
        "model": model,
        "reasoning_effort": effort,
        "explanation": explanation,
    }

    await events.status(
        (
            f"Routing to {model} (effort: {effort})\n"
            f"Explanation: {explanation}"
        )
    )

    return request


__all__ = ["route_auto_model"]
