"""Persistence and reconstruction services for Responses items."""

from __future__ import annotations

from typing import Any, Callable

from ..core.markers import (
    contains_marker,
    create_marker,
    extract_markers,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from ..core.messages import (
    assistant_text_item,
    developer_message,
    normalize_user_blocks,
    user_blocks_to_responses_items,
)
from ..infra.openwebui_store import ItemStore

Resolver = Callable[[list[str], str | None, str | None], dict[str, dict[str, Any]]]


class HistoryPersistence:
    """Persist structured output items and emit hidden markers."""

    def __init__(self, store: ItemStore) -> None:
        self.store = store

    def persist_items_for_message(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        *,
        model_id: str,
    ) -> str:
        if not items:
            return ""

        ulids = self.store.save_items(chat_id, message_id, items, model_id)
        hidden_markers: list[str] = []
        for ulid, payload in zip(ulids, items):
            marker = create_marker(payload.get("type", "unknown"), ulid=ulid, model_id=model_id)
            hidden_markers.append(wrap_marker(marker))
        return "".join(hidden_markers)


class HistoryBuilder:
    """Rebuild Responses input items from OpenWebUI messages."""

    def __init__(self, resolve_items: Resolver | None = None) -> None:
        self._resolve_items = resolve_items

    def build_input_from_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        chat_id: str | None = None,
        openwebui_model_id: str | None = None,
    ) -> list[dict[str, Any]]:
        required_item_ids: list[str] = []
        for message in messages:
            content = message.get("content")
            if message.get("role") == "assistant" and isinstance(content, str) and contains_marker(content):
                for marker in extract_markers(content, parsed=True):
                    required_item_ids.append(marker["ulid"])

        resolved: dict[str, dict[str, Any]] = {}
        if required_item_ids and self._resolve_items:
            resolved = self._resolve_items(required_item_ids, chat_id, openwebui_model_id)

        openai_input: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                continue
            if role == "user":
                blocks = user_blocks_to_responses_items(normalize_user_blocks(content))
                if blocks:
                    openai_input.append({"role": "user", "content": blocks})
                continue
            if role == "developer":
                if isinstance(content, str) and content:
                    openai_input.append(developer_message(content))
                continue
            if role == "assistant" and isinstance(content, str):
                if not contains_marker(content):
                    if content.strip():
                        openai_input.append(assistant_text_item(content.strip()))
                    continue
                for segment in split_text_by_markers(content):
                    if segment["type"] == "marker":
                        marker = parse_marker(segment["marker"])
                        payload = resolved.get(marker["ulid"])
                        if payload:
                            openai_input.append(payload)
                    elif segment["type"] == "text":
                        text_segment = segment.get("text", "").strip()
                        if text_segment:
                            openai_input.append(assistant_text_item(text_segment))

        return openai_input


__all__ = ["HistoryBuilder", "HistoryPersistence"]
