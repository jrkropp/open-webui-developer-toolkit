"""Basic tests for marker helpers and history services."""

from __future__ import annotations

import openai_responses_manifold as orm
from openai_responses_manifold.application.history import HistoryBuilder, HistoryPersistence
from openai_responses_manifold.infrastructure.openwebui_store import ItemStore

from .fakes import InMemoryChats


def test_marker_roundtrip() -> None:
    """create_marker, wrap_marker, extract_markers, and split_text_by_markers align."""
    raw_marker = orm.create_marker(
        "function_call",
        ulid="A1B2C3D4E5F6G7H8",
        metadata={"tool": "search"},
    )
    wrapped = orm.wrap_marker(raw_marker)
    sample = f"before{wrapped}after"

    assert orm.contains_marker(sample)

    parsed = orm.extract_markers(sample, parsed=True)
    assert parsed[0]["metadata"]["tool"] == "search"

    segments = orm.split_text_by_markers(sample)
    assert segments[0]["type"] == "text" and segments[0]["text"].strip() == "before"
    assert segments[1]["type"] == "marker"


def test_history_persistence_and_builder(chat_store: InMemoryChats) -> None:
    """Persisted response items can be restored via HistoryBuilder."""

    chat_store.ensure("chat-123")
    store = ItemStore()
    persistence = HistoryPersistence(store)
    items = [
        {"type": "reasoning", "content": [{"type": "output_text", "text": "thinking"}]},
    ]
    marker_blob = persistence.persist_items_for_message(
        "chat-123",
        "msg-1",
        items,
        model_id="openai_responses.gpt-4o",
    )

    assert orm.contains_marker(marker_blob)

    builder = HistoryBuilder(
        resolve_items=lambda item_ids, chat_id, model_id: store.load_items(
            chat_id or "chat-123", item_ids, model_id=model_id
        )
    )
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": f"I did this{marker_blob}"},
    ]
    rebuilt = builder.build_input_from_messages(
        messages,
        chat_id="chat-123",
        openwebui_model_id="openai_responses.gpt-4o",
    )

    assert any(item.get("type") == "reasoning" for item in rebuilt)
