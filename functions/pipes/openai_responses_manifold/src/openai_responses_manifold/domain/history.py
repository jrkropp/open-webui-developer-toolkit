"""Persistence and reconstruction services for Responses items."""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

from openai_responses_manifold.core.logging import get_logger
from openai_responses_manifold.core.markers import (
    contains_marker,
    create_marker,
    extract_markers,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from openai_responses_manifold.core.messages import (
    assistant_blocks_to_responses_items,
    assistant_text_item,
    developer_message,
    normalize_user_blocks,
    user_blocks_to_responses_items,
)

Resolver = Callable[[list[str], str | None, str | None], dict[str, dict[str, Any]]]
logger = get_logger(__name__)


class HistoryStore(Protocol):
    def save_items(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        model_id: str,
    ) -> list[str]: ...

    def load_items(
        self,
        chat_id: str,
        item_ids: list[str],
        *,
        model_id: str | None = None,
    ) -> dict[str, dict[str, Any]]: ...


class NullHistoryStore:
    """Null object used when no backing store is provided."""

    def save_items(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict[str, Any]],
        model_id: str,
    ) -> list[str]:
        return []

    def load_items(
        self,
        chat_id: str,
        item_ids: list[str],
        *,
        model_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return {}


class HistoryPersistence:
    """
    Persist structured output items and emit hidden markers.

    Protocol overview:
    - When a structured output item (tool output, reasoning tokens, etc.) is finalized,
      persist_items_for_message():
        * deep-clones the payload and strips server-side IDs,
        * saves the payload in the store keyed by a ULID,
        * returns a concatenated string of hidden markers like
          "[openai_responses:v2:<kind>:<ulid>?model=<model_id>]: #\n".
    - Callers append that marker string to the assistant's text; the marker is invisible to end users.
    - On later turns, HistoryBuilder scans assistant messages for markers, resolves ULIDs via the store,
      and injects those stored payloads back into the Responses input list.
    """

    def __init__(self, store: HistoryStore | None = None) -> None:
        self.store = store or NullHistoryStore()

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

        cleaned: list[dict[str, Any]] = []
        for payload in items:
            if not isinstance(payload, dict):
                continue
            clone = json.loads(json.dumps(payload))
            # Drop server-side IDs so we never depend on OpenAI-side persistence when store=False.
            clone.pop("id", None)
            cleaned.append(clone)

        if not cleaned:
            return ""

        ulids = self.store.save_items(chat_id, message_id, cleaned, model_id)
        if len(ulids) != len(cleaned):
            logger.warning(
                "Item store returned %d ids for %d items; some output markers will be missing.",
                len(ulids),
                len(cleaned),
            )
        hidden_markers: list[str] = []
        for ulid, payload in zip(ulids, cleaned):
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
            if role == "assistant":
                if isinstance(content, str):
                    if not contains_marker(content):
                        if content.strip():
                            openai_input.append(assistant_text_item(content.strip()))
                        continue
                    for segment in split_text_by_markers(content):
                        if segment["type"] == "marker":
                            marker = parse_marker(segment["marker"])
                            payload = resolved.get(marker["ulid"])
                            if payload:
                                payload_copy = json.loads(json.dumps(payload))
                                payload_copy.setdefault("id", marker["ulid"])
                                openai_input.append(payload_copy)
                        elif segment["type"] == "text":
                            text_segment = segment.get("text", "").strip()
                            if text_segment:
                                openai_input.append(assistant_text_item(text_segment))
                    continue
                if isinstance(content, list):
                    blocks = assistant_blocks_to_responses_items(normalize_user_blocks(content))
                    if blocks:
                        openai_input.append({"role": "assistant", "content": blocks})
                continue

        return openai_input


class HistoryService:
    """Facade for reconstructing Responses input items and instructions from stored chat history."""

    def __init__(self, store: HistoryStore | None = None) -> None:
        self.store = store or NullHistoryStore()

    def build_input_and_instructions(
        self,
        messages: list[dict[str, Any]],
        *,
        metadata: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        resolver = self._resolver(metadata)
        builder = HistoryBuilder(resolve_items=resolver)
        input_items = builder.build_input_from_messages(
            messages,
            chat_id=metadata.get("chat_id"),
            openwebui_model_id=metadata.get("model", {}).get("id"),
        )
        instructions = self._extract_system_instructions(messages)
        return input_items, instructions

    def _resolver(self, metadata: dict[str, Any]) -> Resolver:
        chat_id = metadata.get("chat_id")
        openwebui_model_id = metadata.get("model", {}).get("id")

        def _resolve(
            item_ids: list[str],
            resolver_chat: str | None,
            model_id: str | None,
        ) -> dict[str, dict[str, Any]]:
            target_chat = resolver_chat or chat_id or ""
            target_model = model_id or openwebui_model_id
            return self.store.load_items(target_chat, item_ids, model_id=target_model)

        return _resolve

    @staticmethod
    def _extract_system_instructions(messages: list[dict[str, Any]]) -> str | None:
        """Return the most recent system message content, if present."""

        for message in reversed(messages):
            if message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        return None


__all__ = ["HistoryBuilder", "HistoryPersistence", "HistoryService", "HistoryStore", "NullHistoryStore"]
