"""Persistence and reconstruction services for Responses items.

Layers at a glance:
* ``HistoryRepository`` wraps ``ItemStore`` for storage/retrieval.
* ``HistoryPersistence`` cleans and stores items, then renders hidden markers.
* ``HistoryBuilder`` / ``HistoryService`` replay stored items into Responses input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from copy import deepcopy

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

MarkerResolver = Callable[[list[str]], dict[str, dict[str, Any]]]


@dataclass
class StoredItem:
    """Persisted item reference returned from the repository."""

    id: str
    item: dict[str, Any]


def extract_system_instructions(messages: list[dict[str, Any]]) -> str | None:
    """Return the most recent system message content, if present."""

    for message in reversed(messages):
        if message.get("role") == "system":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return None


def _deep_clone_item(item: dict[str, Any]) -> dict[str, Any]:
    """Deep copy an item to detach it from any upstream mutations."""

    return deepcopy(item)


def collect_marker_item_ids(messages: list[dict[str, Any]]) -> list[str]:
    """Return ULIDs referenced by assistant markers within the messages."""

    required_item_ids: list[str] = []
    seen: set[str] = set()
    for message in messages:
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str) and contains_marker(content):
            for marker in extract_markers(content, parsed=True):
                ulid = marker["ulid"]
                if ulid not in seen:
                    required_item_ids.append(ulid)
                    seen.add(ulid)
    return required_item_ids


def resolve_marked_items(
    messages: list[dict[str, Any]],
    *,
    resolve_items: MarkerResolver | None,
) -> dict[str, dict[str, Any]]:
    """Resolve persisted items referenced by markers in the provided messages."""

    required_item_ids = collect_marker_item_ids(messages)
    if required_item_ids and resolve_items:
        return resolve_items(required_item_ids)
    return {}


class HistoryRepository:
    """Minimal adapter over ``ItemStore`` for persisting history items."""

    def __init__(self, store: ItemStore) -> None:
        self.store = store

    @classmethod
    def from_item_store(cls, store: ItemStore) -> "HistoryRepository":
        return cls(store)

    def save_history_items(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        *,
        model_id: str,
    ) -> list[str]:
        return self.store.save_items(chat_id, message_id, items, model_id)

    def load_history_items(
        self,
        chat_id: str,
        item_ids: list[str],
        *,
        model_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return self.store.load_items(chat_id, item_ids, model_id=model_id)


class HistoryPersistence:
    """Persist structured output items and emit hidden markers."""

    def __init__(self, repository: HistoryRepository) -> None:
        self.repository = repository

    @classmethod
    def from_item_store(cls, store: ItemStore) -> "HistoryPersistence":
        return cls(HistoryRepository.from_item_store(store))

    def store_items(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        *,
        model_id: str,
    ) -> list[StoredItem]:
        """Store cleaned items and return persisted ids alongside items."""

        cleaned = self._clean_items(items)
        if not cleaned:
            return []

        stored_ids = self.repository.save_history_items(
            chat_id, message_id, cleaned, model_id=model_id
        )
        return [StoredItem(id=ulid, item=item) for ulid, item in zip(stored_ids, cleaned)]

    def render_hidden_markers(
        self, stored_items: list[StoredItem], *, model_id: str
    ) -> str:
        """Render hidden marker strings for previously stored items."""

        hidden_markers: list[str] = []
        for stored in stored_items:
            marker = create_marker(
                stored.item.get("type", "unknown"), ulid=stored.id, model_id=model_id
            )
            hidden_markers.append(wrap_marker(marker))
        return "".join(hidden_markers)

    def persist_items_for_message(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        *,
        model_id: str,
    ) -> str:
        """Store items and return rendered hidden markers for downstream emission."""

        stored = self.store_items(chat_id, message_id, items, model_id=model_id)
        if not stored:
            return ""
        return self.render_hidden_markers(stored, model_id=model_id)

    @staticmethod
    def _clean_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            clone = _deep_clone_item(item)
            # Drop server-side IDs so we never depend on OpenAI-side persistence when store=False.
            clone.pop("id", None)
            cleaned.append(clone)
        return cleaned


def _build_assistant_items(
    content: str, resolved_items: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if not contains_marker(content):
        text = content.strip()
        if text:
            items.append(assistant_text_item(text))
        return items

    for segment in split_text_by_markers(content):
        if segment["type"] == "marker":
            marker = parse_marker(segment["marker"])
            item = resolved_items.get(marker["ulid"])
            if item:
                items.append(item)
        elif segment["type"] == "text":
            text_segment = segment.get("text", "").strip()
            if text_segment:
                items.append(assistant_text_item(text_segment))

    return items


def build_history_input(
    messages: list[dict[str, Any]],
    *,
    resolver: MarkerResolver | None = None,
) -> list[dict[str, Any]]:
    """Rebuild Responses input items from OpenWebUI messages."""

    resolved = resolve_marked_items(messages, resolve_items=resolver)

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
            openai_input.extend(_build_assistant_items(content, resolved))

    return openai_input


class HistoryBuilder:
    """Rebuild Responses input items from OpenWebUI messages."""

    def __init__(self, resolve_items: MarkerResolver | None = None) -> None:
        self._resolve_items = resolve_items

    def build_input_from_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return build_history_input(messages, resolver=self._resolve_items)


class HistoryService:
    """Facade for reconstructing Responses input items and instructions from stored chat history."""

    def __init__(self, repository: HistoryRepository) -> None:
        self.repository = repository

    @classmethod
    def from_item_store(cls, store: ItemStore) -> "HistoryService":
        return cls(HistoryRepository.from_item_store(store))

    def build_input_and_instructions(
        self,
        messages: list[dict[str, Any]],
        *,
        metadata: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        resolver = self._marker_resolver(metadata)
        builder = HistoryBuilder(resolve_items=resolver)
        input_items = builder.build_input_from_messages(messages)
        instructions = extract_system_instructions(messages)
        return input_items, instructions

    def _marker_resolver(self, metadata: dict[str, Any]) -> MarkerResolver:
        chat_id = metadata.get("chat_id")
        openwebui_model_id = metadata.get("model", {}).get("id")

        def _resolve(item_ids: list[str]) -> dict[str, dict[str, Any]]:
            if not chat_id:
                return {}
            return self.repository.load_history_items(
                chat_id, item_ids, model_id=openwebui_model_id
            )

        return _resolve


__all__ = [
    "HistoryBuilder",
    "HistoryPersistence",
    "HistoryRepository",
    "HistoryService",
    "StoredItem",
    "build_history_input",
    "collect_marker_item_ids",
    "extract_system_instructions",
    "resolve_marked_items",
]
