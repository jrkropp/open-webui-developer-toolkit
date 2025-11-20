"""Persistence helpers for storing Responses items in OpenWebUI."""

from __future__ import annotations

import datetime
import secrets
from typing import Any

from open_webui.models.chats import Chats

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class ItemStore:
    """Adapter around ``open_webui.models.chats.Chats``."""

    def __init__(self, *, store_key: str = "openai_responses_pipe") -> None:
        self.store_key = store_key

    def save_items(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        model_id: str,
    ) -> list[str]:
        """
        Persist items and return the generated ULIDs.

        Note: ``model_id`` is the OpenWebUI model identifier (not the underlying OpenAI model id).
        Items are filtered by this id on retrieval.
        """

        if not items:
            return []

        chat_model = Chats.get_chat_by_id(chat_id)
        if not chat_model:
            return []

        pipe_root = chat_model.chat.setdefault(self.store_key, {"__v": 3})
        items_store = pipe_root.setdefault("items", {})
        messages_index = pipe_root.setdefault("messages_index", {})
        message_bucket = messages_index.setdefault(
            message_id,
            {"role": "assistant", "done": True, "item_ids": []},
        )

        now = int(datetime.datetime.now(datetime.UTC).timestamp())
        stored_ids: list[str] = []
        for payload in items:
            item_id = _generate_item_id()
            items_store[item_id] = {
                "model": model_id,
                "created_at": now,
                "payload": payload,
                "message_id": message_id,
            }
            message_bucket["item_ids"].append(item_id)
            stored_ids.append(item_id)

        Chats.update_chat_by_id(chat_id, chat_model.chat)
        return stored_ids

    def load_items(
        self,
        chat_id: str,
        item_ids: list[str],
        *,
        model_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch persisted items by ULID, optionally filtered by model id."""

        if not item_ids:
            return {}
        chat_model = Chats.get_chat_by_id(chat_id)
        if not chat_model:
            return {}

        items_store = chat_model.chat.get(self.store_key, {}).get("items", {})
        lookup: dict[str, dict[str, Any]] = {}
        for item_id in item_ids:
            item = items_store.get(item_id)
            if not item:
                continue
            if model_id and item.get("model") != model_id:
                continue
            payload = item.get("payload")
            if isinstance(payload, dict):
                lookup[item_id] = payload
        return lookup


def _generate_item_id(length: int = 16) -> str:
    return "".join(secrets.choice(_CROCKFORD) for _ in range(length))


__all__ = ["ItemStore"]
