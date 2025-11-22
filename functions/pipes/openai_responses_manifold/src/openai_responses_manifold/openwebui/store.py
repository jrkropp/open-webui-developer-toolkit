"""Open WebUI-backed history store implementation.

This adapter owns the ``chat.chat["openai_responses_pipe"]`` layout and
implements the :class:`~openai_responses_manifold.domain.history.HistoryStore`
protocol so the domain layer can persist and reload structured items.
"""

from __future__ import annotations

import time
from typing import Any

from openai_responses_manifold.core.markers import generate_ulid
from openai_responses_manifold.domain.history import HistoryStore


class OpenWebUIHistoryStore(HistoryStore):
    """Persist history items using Open WebUI's ``Chats`` model."""

    VERSION = 3

    def __init__(self, chats_model: Any | None = None):
        if chats_model is not None:
            self._Chats = chats_model
        else:
            try:
                self._Chats = self._import_chats()
            except Exception:  # pragma: no cover - defensive fallback for missing deps
                self._Chats = None

    def _import_chats(self):  # pragma: no cover - exercised via injection in tests
        from open_webui.models.chats import Chats

        return Chats

    def save_items(
        self,
        chat_key: dict,
        message_id: str,
        items: list[dict],
        model_id: str,
    ) -> list[str]:
        if not self._Chats:
            return []
        chat_id = chat_key.get("chat_id") if isinstance(chat_key, dict) else None
        if not chat_id:
            return []

        chat = self._Chats.get_chat_by_id(chat_id)
        if not chat:
            return []

        pipe_root = chat.chat.setdefault("openai_responses_pipe", {"__v": self.VERSION})
        items_store = pipe_root.setdefault("items", {})
        messages_index = pipe_root.setdefault("messages_index", {})
        bucket = messages_index.setdefault(
            message_id, {"role": "assistant", "done": True, "item_ids": []}
        )

        now = int(time.time())
        created: list[str] = []
        for payload in items:
            ulid = generate_ulid()
            items_store[ulid] = {
                "model": model_id,
                "created_at": now,
                "payload": payload,
                "message_id": message_id,
            }
            bucket.setdefault("item_ids", []).append(ulid)
            created.append(ulid)

        self._Chats.update_chat_by_id(chat_id, chat.chat)
        return created

    def load_items(
        self, chat_key: dict, item_ids: list[str], model_id: str | None = None
    ) -> dict[str, dict]:
        if not self._Chats:
            return {}
        chat_id = chat_key.get("chat_id") if isinstance(chat_key, dict) else None
        if not chat_id:
            return {}

        chat = self._Chats.get_chat_by_id(chat_id)
        if not chat:
            return {}

        items_store = chat.chat.get("openai_responses_pipe", {}).get("items", {})
        result: dict[str, dict] = {}
        for ulid in item_ids:
            item = items_store.get(ulid)
            if not item:
                continue
            if model_id is not None and item.get("model") != model_id:
                continue
            result[ulid] = item.get("payload") or {}
        return result


__all__ = ["OpenWebUIHistoryStore"]
