"""Helpers that translate Open WebUI inputs into Responses requests."""

from __future__ import annotations

import json
from typing import Any, Tuple

from openai_responses_manifold.core import base_model, features
from openai_responses_manifold.core.config import RuntimeConfig
from openai_responses_manifold.domain.history import HistoryManager
from openai_responses_manifold.domain.types import TurnContext
from openai_responses_manifold.openai_api.types import ResponsesRequest


def build_turn_context(
    *,
    pipe_valves,
    user_valves,
    runtime_cfg: RuntimeConfig,
    __user__: dict | None,
    __metadata__: dict | None,
) -> TurnContext:
    metadata = __metadata__ or {}
    owui_model_id = metadata.get("model", {}).get("id") if isinstance(metadata.get("model"), dict) else None
    model_id = base_model(owui_model_id or runtime_cfg.MODEL_ID)
    model_features = features(model_id)
    ctx_metadata = {
        "session_id": metadata.get("session_id"),
        "chat_id": metadata.get("chat_id"),
        "message_id": metadata.get("message_id"),
        "user_id": (__user__ or {}).get("id"),
        "user_email": (__user__ or {}).get("email"),
        "owui_model_id": owui_model_id,
    }
    return TurnContext(
        runtime_config=runtime_cfg,
        model_id=model_id,
        features=model_features,
        metadata=ctx_metadata,
    )


def map_completions_to_responses(
    *,
    body: dict,
    ctx: TurnContext,
    history_manager: HistoryManager,
    history_key: dict,
) -> Tuple[ResponsesRequest, list[dict], list[dict]]:
    messages = body.get("messages") or []
    input_items, instructions = history_manager.build_input_from_messages(
        messages=messages,
        chat_key=history_key,
        model_id=ctx.model_id,
        openwebui_model_id=ctx.metadata.get("owui_model_id"),
    )

    request = ResponsesRequest(
        model=ctx.model_id,
        input=input_items,
        instructions=instructions,
        stream=True,
        store=True,
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        top_logprobs=body.get("top_logprobs"),
        truncation=body.get("truncation"),
        max_output_tokens=body.get("max_tokens"),
        reasoning={"effort": body.get("reasoning_effort")}
        if body.get("reasoning_effort")
        else None,
        user=ctx.metadata.get("user_id") or ctx.metadata.get("user_email"),
    )

    base_tools = body.get("tools") or []
    extra_tools = body.get("extra_tools") or []
    return request, base_tools, extra_tools


def build_mcp_tools(cfg: RuntimeConfig) -> list[dict]:
    raw = cfg.REMOTE_MCP_SERVERS_JSON
    if not raw:
        return []

    try:
        entries = json.loads(raw)
    except Exception:
        return []

    tools: list[dict] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            label = entry.get("server_label")
            url = entry.get("server_url")
            if not isinstance(label, str) or not isinstance(url, str):
                continue
            tool = {"type": "mcp", "server_label": label, "server_url": url, "source": "mcp"}
            if "require_approval" in entry:
                tool["require_approval"] = entry.get("require_approval")
            if "allowed_tools" in entry:
                tool["allowed_tools"] = entry.get("allowed_tools")
            if "headers" in entry:
                tool["headers"] = entry.get("headers")
            tools.append(tool)
    return tools


__all__ = ["build_turn_context", "map_completions_to_responses", "build_mcp_tools"]
