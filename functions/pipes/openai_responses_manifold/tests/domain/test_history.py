import pytest

from openai_responses_manifold.core.markers import (
    build_marker_payload,
    extract_markers,
    generate_ulid,
    parse_marker,
    wrap_marker,
)
from openai_responses_manifold.domain.history import HistoryManager


class FakeHistoryStore:
    def __init__(self, items_by_id: dict[str, dict] | None = None, ulids: list[str] | None = None):
        self.items_by_id = items_by_id or {}
        self.saved: list[tuple[dict, str, list[dict], str]] = []
        self.loaded: list[tuple[dict, list[str], str | None]] = []
        self._ulids = list(ulids or [])

    def save_items(self, chat_key: dict, message_id: str, items: list[dict], model_id: str) -> list[str]:
        self.saved.append((chat_key, message_id, items, model_id))
        ulids: list[str] = []
        if self._ulids:
            ulids = self._ulids[: len(items)]
            self._ulids = self._ulids[len(items) :]
        elif self.items_by_id:
            ulids = list(self.items_by_id.keys())
        if not ulids:
            ulids = [generate_ulid() for _ in range(len(items))]
        return ulids[: len(items)]

    def load_items(self, chat_key: dict, item_ids: list[str], model_id: str | None = None) -> dict[str, dict]:
        self.loaded.append((chat_key, item_ids, model_id))
        result: dict[str, dict] = {}
        for ulid in item_ids:
            item = self.items_by_id.get(ulid)
            if item is None:
                continue
            stored_model = item.get("model")
            if model_id is not None and stored_model is not None and stored_model != model_id:
                continue
            payload = item.get("payload") if "payload" in item else item
            result[ulid] = payload
        return result


def _marker_for(item_type: str, ulid: str, model: str) -> str:
    payload = build_marker_payload(item_type=item_type, ulid=ulid, metadata={"model": model})
    return wrap_marker(payload)


def test_build_input_basic_mapping_and_instructions():
    store = FakeHistoryStore()
    manager = HistoryManager(store)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello there"},
    ]

    input_items, instructions = manager.build_input_from_messages(
        messages=messages,
        chat_key=None,
        model_id="gpt-4o",
        openwebui_model_id=None,
    )

    assert instructions == "sys"
    assert input_items == [
        {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Hello there"}]},
    ]
    assert store.loaded == []  # persistence skipped when chat_key missing


def test_build_input_with_markers_and_ordering():
    openwebui_model_id = "openai_responses.gpt-4o"
    stored_items = {
        "A" * 16: {"payload": {"type": "function_call", "name": "call"}, "model": openwebui_model_id},
        "B" * 16: {"payload": {"type": "function_call_output", "content": "result"}, "model": openwebui_model_id},
    }
    store = FakeHistoryStore(stored_items)
    manager = HistoryManager(store)

    assistant_content = (
        "Before"
        + _marker_for("function_call", "A" * 16, openwebui_model_id)
        + "Between"
        + _marker_for("function_call_output", "B" * 16, openwebui_model_id)
        + "Tail"
    )
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": assistant_content},
    ]

    input_items, instructions = manager.build_input_from_messages(
        messages=messages,
        chat_key={"chat_id": "chat-1"},
        model_id="gpt-4o",
        openwebui_model_id=openwebui_model_id,
    )

    assert instructions is None
    assert input_items == [
        {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Before"}]},
        {"type": "function_call", "name": "call"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Between"}]},
        {"type": "function_call_output", "content": "result"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Tail"}]},
    ]
    assert len(store.loaded) == 1
    loaded_chat_key, loaded_ids, loaded_model = store.loaded[0]
    assert loaded_chat_key == {"chat_id": "chat-1"}
    assert set(loaded_ids) == {"A" * 16, "B" * 16}
    assert loaded_model == openwebui_model_id


def test_build_input_skips_mismatched_models_from_store():
    store = FakeHistoryStore(
        {
            "A" * 16: {"payload": {"type": "function_call", "name": "call"}, "model": "different"},
            "B" * 16: {"payload": {"type": "function_call_output", "content": "result"}, "model": "expected"},
        }
    )
    manager = HistoryManager(store)

    messages = [
        {
            "role": "assistant",
            "content": _marker_for("function_call", "A" * 16, "different")
            + _marker_for("function_call_output", "B" * 16, "expected"),
        }
    ]

    input_items, _ = manager.build_input_from_messages(
        messages=messages,
        chat_key={"chat_id": "chat-1"},
        model_id="gpt-4o",
        openwebui_model_id="expected",
    )

    assert input_items == [
        {"type": "function_call_output", "content": "result"},
    ]


def test_persist_items_appends_wrapped_markers_and_uses_model_id():
    store = FakeHistoryStore()
    manager = HistoryManager(store)

    items = [{"type": "function_call", "name": "do"}, {"type": "reasoning", "content": "why"}]
    updated = manager.persist_items_for_message(
        chat_key={"chat_id": "chat-1"},
        message_id="msg-1",
        items=items,
        model_id="gpt-4o",
        openwebui_model_id="owui-model",
        current_assistant_text="Visible",
    )

    assert store.saved == [({"chat_id": "chat-1"}, "msg-1", items, "owui-model")]
    marker_payloads = extract_markers(updated)
    assert len(marker_payloads) == len(items)
    for marker_payload in marker_payloads:
        parsed = parse_marker(marker_payload)
        assert parsed["metadata"].get("model") == "owui-model"


def test_persist_items_noop_when_missing_context():
    store = FakeHistoryStore()
    manager = HistoryManager(store)

    updated = manager.persist_items_for_message(
        chat_key=None,
        message_id="msg-1",
        items=[{"type": "function_call"}],
        model_id="gpt-4o",
        openwebui_model_id=None,
        current_assistant_text="Visible",
    )

    assert updated == "Visible"
    assert store.saved == []


def test_persist_items_replaces_placeholders_and_preserves_order():
    placeholders = "--PLACEHOLDER--"
    store = FakeHistoryStore(ulids=["A" * 16, "B" * 16])
    manager = HistoryManager(store)

    items = [
        {"type": "function_call", "name": "do"},
        {"type": "reasoning", "content": "why"},
    ]
    text = f"Intro {placeholders} middle {placeholders} tail"
    updated = manager.persist_items_for_message(
        chat_key={"chat_id": "chat-1"},
        message_id="msg-1",
        items=items,
        model_id="gpt-4o",
        openwebui_model_id="owui-model",
        current_assistant_text=text,
        marker_placeholder=placeholders,
    )

    markers = extract_markers(updated)
    assert len(markers) == 2
    first_index = updated.index(markers[0])
    second_index = updated.index(markers[1])
    assert first_index < updated.index("middle") < second_index
    assert "--PLACEHOLDER--" not in updated
