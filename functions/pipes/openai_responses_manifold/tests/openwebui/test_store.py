import time

import pytest

from openai_responses_manifold.openwebui.store import OpenWebUIHistoryStore


class _FakeChat:
    def __init__(self) -> None:
        self.chat: dict = {}


class _FakeChats:
    chat: _FakeChat | None = _FakeChat()
    updated_payload: dict | None = None

    @classmethod
    def get_chat_by_id(cls, chat_id: str):
        return cls.chat

    @classmethod
    def update_chat_by_id(cls, chat_id: str, payload: dict) -> None:
        cls.updated_payload = payload


def test_save_and_load_items_roundtrip(monkeypatch):
    store = OpenWebUIHistoryStore(chats_model=_FakeChats)
    now = int(time.time())

    created = store.save_items(
        chat_key={"chat_id": "123"},
        message_id="m-1",
        items=[{"type": "function_call_output", "output": "ok"}],
        model_id="openai_responses.gpt-5.1",
    )

    assert len(created) == 1
    ulid = created[0]

    loaded = store.load_items({"chat_id": "123"}, created, model_id="openai_responses.gpt-5.1")
    assert loaded[ulid]["type"] == "function_call_output"
    assert _FakeChats.updated_payload["openai_responses_pipe"]["messages_index"]["m-1"]["item_ids"] == [ulid]
    assert _FakeChats.updated_payload["openai_responses_pipe"]["items"][ulid]["created_at"] >= now


def test_load_items_filters_model():
    chat = _FakeChat()
    chat.chat = {
        "openai_responses_pipe": {
            "items": {
                "A": {"model": "model_a", "payload": {"value": 1}},
                "B": {"model": "model_b", "payload": {"value": 2}},
            }
        }
    }
    _FakeChats.chat = chat
    store = OpenWebUIHistoryStore(chats_model=_FakeChats)

    loaded = store.load_items({"chat_id": "123"}, ["A", "B"], model_id="model_a")
    assert "A" in loaded
    assert "B" not in loaded
