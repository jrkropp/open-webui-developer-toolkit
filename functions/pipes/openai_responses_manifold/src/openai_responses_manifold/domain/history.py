"""History reconstruction and persistence helpers.

This module provides a small persistence protocol (`HistoryStore`) and a
pure domain helper (`HistoryManager`) that converts Open WebUI-style
``messages`` into the OpenAI Responses ``input`` shape, and appends
markers for newly persisted items.
"""

from __future__ import annotations

from typing import Iterable, Protocol, Tuple

from openai_responses_manifold.core.markers import (
    build_marker_payload,
    contains_marker,
    extract_markers,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)


MARKER_PLACEHOLDER = "<!--openai_responses:marker-->"


class HistoryStore(Protocol):
    def save_items(
        self,
        chat_key: dict,
        message_id: str,
        items: list[dict],
        model_id: str,
    ) -> list[str]:
        """Persist items and return their ULIDs."""

    def load_items(
        self,
        chat_key: dict,
        item_ids: list[str],
        model_id: str | None = None,
    ) -> dict[str, dict]:
        """Return {ulid: payload} for requested items (filtered by model if given)."""


def _render_system_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Iterable):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return " ".join(part for part in parts if part).strip()
    return str(content)


def _to_input_block(block: dict) -> dict:
    kind = block.get("type")
    if kind == "text":
        return {"type": "input_text", "text": block.get("text", "")}
    if kind == "image_url":
        url = (block.get("image_url") or {}).get("url")
        return {"type": "input_image", "image_url": url}
    if kind == "input_file":
        return {"type": "input_file", "file_id": block.get("file_id")}
    return block


class HistoryManager:
    """Bridge between Open WebUI messages and Responses API history."""

    def __init__(self, store: HistoryStore):
        self._store = store

    def _collect_required_item_ids(self, messages: list[dict]) -> set[str]:
        required_item_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if not contains_marker(content):
                continue
            for marker in extract_markers(content, parsed=True):
                ulid = marker.get("ulid")
                if isinstance(ulid, str):
                    required_item_ids.add(ulid)
        return required_item_ids

    def build_input_from_messages(
        self,
        *,
        messages: list[dict],
        chat_key: dict | None,
        model_id: str | None,
        openwebui_model_id: str | None,
    ) -> Tuple[list[dict], str | None]:
        """Build Responses ``input`` items plus instructions from messages."""

        items_lookup: dict[str, dict] = {}
        target_model_id = openwebui_model_id or model_id

        if chat_key and target_model_id:
            required_item_ids = self._collect_required_item_ids(messages)
            if required_item_ids:
                try:
                    items_lookup = self._store.load_items(
                        chat_key=chat_key,
                        item_ids=list(required_item_ids),
                        model_id=target_model_id,
                    )
                except Exception:  # pragma: no cover - defensive fallback
                    items_lookup = {}

        input_items: list[dict] = []
        instructions: str | None = None

        for msg in messages:
            role = msg.get("role")
            if role == "system":
                instructions = _render_system_content(msg.get("content"))
                continue

            if role == "user":
                blocks = msg.get("content") or []
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]
                content_blocks = [_to_input_block(b) for b in blocks if b is not None]
                if content_blocks:
                    input_items.append({"role": "user", "content": content_blocks})
                continue

            if role == "developer":
                blocks = msg.get("content") or []
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]
                content_blocks = [_to_input_block(b) for b in blocks if b is not None]
                if content_blocks:
                    input_items.append({"role": "developer", "content": content_blocks})
                continue

            if role != "assistant":
                continue

            raw = msg.get("content", "") or ""
            if not isinstance(raw, str):
                raw = str(raw)

            if not contains_marker(raw):
                text = raw.strip()
                if text:
                    input_items.append(
                        {"role": "assistant", "content": [{"type": "output_text", "text": text}]}
                    )
                continue

            for segment in split_text_by_markers(raw):
                if segment.get("type") == "marker":
                    payload = segment.get("marker") or ""
                    try:
                        parsed = parse_marker(payload)
                    except Exception:
                        continue
                    ulid = parsed.get("ulid")
                    if isinstance(ulid, str):
                        item = items_lookup.get(ulid)
                        if item is not None:
                            input_items.append(item)
                    continue

                if segment.get("type") == "text":
                    text = (segment.get("text") or "").strip()
                    if text:
                        input_items.append(
                            {
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": text}],
                            }
                        )

        return input_items, instructions

    def persist_items_for_message(
        self,
        *,
        chat_key: dict | None,
        message_id: str,
        items: list[dict],
        model_id: str,
        openwebui_model_id: str | None,
        current_assistant_text: str,
        marker_placeholder: str = MARKER_PLACEHOLDER,
    ) -> str:
        """Persist items and append wrapped markers to assistant text."""

        if not items:
            return current_assistant_text
        if not chat_key or not openwebui_model_id:
            return current_assistant_text

        try:
            ulids = self._store.save_items(
                chat_key=chat_key,
                message_id=message_id,
                items=items,
                model_id=openwebui_model_id,
            )
        except Exception:  # pragma: no cover - defensive fallback
            return current_assistant_text

        updated_text = current_assistant_text or ""
        for ulid, payload in zip(ulids, items):
            item_type = str(payload.get("type", "unknown"))
            raw_payload = build_marker_payload(
                item_type=item_type,
                ulid=ulid,
                metadata={"model": openwebui_model_id},
            )
            marker_text = wrap_marker(raw_payload)
            if marker_placeholder and marker_placeholder in updated_text:
                updated_text = updated_text.replace(marker_placeholder, marker_text, 1)
            else:
                updated_text += marker_text

        if marker_placeholder and marker_placeholder in updated_text:
            updated_text = updated_text.replace(marker_placeholder, "")

        return updated_text


__all__ = ["HistoryManager", "HistoryStore", "MARKER_PLACEHOLDER"]
