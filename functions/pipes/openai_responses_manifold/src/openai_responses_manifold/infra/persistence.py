"""Persistence helpers for storing auxiliary Responses items in Open WebUI."""

from __future__ import annotations

import datetime
from typing import Any

from open_webui.models.chats import Chats

from ..core.markers import create_marker, generate_item_id, wrap_marker


def persist_openai_response_items(
    chat_id: str,
    message_id: str,
    items: list[dict[str, Any]],
    openwebui_model_id: str,
) -> str:
    """Persist response items and return concatenated hidden markers."""

    if not items:
        return ""

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return ""

    pipe_root = chat_model.chat.setdefault("openai_responses_pipe", {"__v": 3})
    items_store = pipe_root.setdefault("items", {})
    messages_index = pipe_root.setdefault("messages_index", {})

    message_bucket = messages_index.setdefault(
        message_id,
        {"role": "assistant", "done": True, "item_ids": []},
    )

    now = int(datetime.datetime.utcnow().timestamp())
    hidden_markers: list[str] = []
    for payload in items:
        item_id = generate_item_id()
        items_store[item_id] = {
            "model": openwebui_model_id,
            "created_at": now,
            "payload": payload,
            "message_id": message_id,
        }
        message_bucket["item_ids"].append(item_id)
        hidden_markers.append(
            wrap_marker(create_marker(payload.get("type", "unknown"), ulid=item_id))
        )

    Chats.update_chat_by_id(chat_id, chat_model.chat)
    return "".join(hidden_markers)


def fetch_openai_response_items(
    chat_id: str,
    item_ids: list[str],
    *,
    openwebui_model_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch persisted items by ULID, optionally filtering by model id."""

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return {}

    items_store = chat_model.chat.get("openai_responses_pipe", {}).get("items", {})
    lookup: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        item = items_store.get(item_id)
        if not item:
            continue
        if openwebui_model_id and item.get("model", "") != openwebui_model_id:
            continue
        lookup[item_id] = item.get("payload", {})
    return lookup
