import sys
import types

import pytest

from openai_responses_manifold.domain.history import HistoryManager
from openai_responses_manifold.domain.types import Citation, TurnContext, TurnResult
from openai_responses_manifold.pipe import Pipe


class _StubStore:
    def save_items(self, *args, **kwargs):
        return []

    def load_items(self, *args, **kwargs):
        return {}


class _StubHistoryManager(HistoryManager):
    def __init__(self):
        super().__init__(_StubStore())
        self.last_messages = None

    def build_input_from_messages(self, messages, chat_key, model_id, openwebui_model_id):
        self.last_messages = messages
        return ([{"role": "user", "content": messages[0].get("content")}], None)


class _StubEngine:
    def __init__(self):
        self.task_calls = 0
        self.seen_tools = None
        self.citations: list[Citation] | None = None
        self.last_task_request = None

    async def run_streaming_turn(self, **kwargs):
        request = kwargs.get("request")
        if request:
            self.seen_tools = request.tools
        citations = self.citations or []
        return TurnResult(text="streamed", citations=citations)

    async def run_task(self, request, ctx: TurnContext):
        self.task_calls += 1
        self.last_task_request = request
        return "task-result"


@pytest.mark.asyncio
async def test_pipe_streaming_with_stubs(monkeypatch):
    pipe = Pipe()
    pipe.history_manager = _StubHistoryManager()
    pipe.engine = _StubEngine()

    calls: list[dict] = []

    async def event_call(payload):
        calls.append(payload)

    result = await pipe.pipe(
        body={"messages": [{"role": "user", "content": "hi"}]},
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=event_call,
        __tools__={},
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )

    assert result == "streamed"
    assert any(payload.get("type") == "execute" for payload in calls)
    script = next(payload["data"]["code"] for payload in calls if payload.get("type") == "execute")
    assert "status-description" in script
    assert "white-space: pre-wrap" in script


@pytest.mark.asyncio
async def test_pipe_task_short_circuit(monkeypatch):
    pipe = Pipe()
    pipe.history_manager = _StubHistoryManager()
    engine = _StubEngine()
    pipe.engine = engine

    result = await pipe.pipe(
        body={},
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=None,
        __tools__={},
        __task__="title",
        __task_body__={"messages": [{"role": "user", "content": "title"}]},
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )

    assert result == "task-result"
    assert engine.task_calls == 1


@pytest.mark.asyncio
async def test_pipe_task_clears_tools_and_uses_task_body():
    pipe = Pipe()
    history = _StubHistoryManager()
    pipe.history_manager = history
    engine = _StubEngine()
    pipe.engine = engine

    task_body = {
        "messages": [{"role": "user", "content": "title"}],
        "tools": [
            {
                "type": "function",
                "name": "should_not_apply",
                "description": "tool for chat",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }

    result = await pipe.pipe(
        body={"messages": [{"role": "user", "content": "ignored"}]},
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=None,
        __tools__={},
        __task__="title",
        __task_body__=task_body,
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )

    assert result == "task-result"
    assert engine.task_calls == 1
    assert engine.last_task_request is not None
    assert engine.last_task_request.stream is False
    assert engine.last_task_request.store is False
    assert engine.last_task_request.tools is None
    assert history.last_messages == task_body["messages"]


@pytest.mark.asyncio
async def test_pipe_includes_filter_extra_tools(monkeypatch):
    pipe = Pipe()
    pipe.history_manager = _StubHistoryManager()
    engine = _StubEngine()
    pipe.engine = engine

    result = await pipe.pipe(
        body={
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "name": "weather_lookup",
                    "description": "Base tool",
                    "parameters": {"type": "object", "properties": {"base": {"type": "string"}}},
                }
            ],
            "extra_tools": [
                {
                    "type": "function",
                    "name": "weather_lookup",
                    "description": "Filter override",
                    "parameters": {
                        "type": "object",
                        "properties": {"filter": {"type": "string"}},
                    },
                }
            ],
        },
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=None,
        __tools__={
            "weather": {
                "spec": {
                    "name": "weather_lookup",
                    "description": "Registry weather",
                    "parameters": {"type": "object", "properties": {"registry": {"type": "string"}}},
                },
                "callable": lambda: None,
            }
        },
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )

    assert result == "streamed"
    assert engine.seen_tools is not None
    assert engine.seen_tools[0]["description"] == "Filter override"
    assert engine.seen_tools[0]["parameters"]["required"] == ["filter"]


@pytest.mark.asyncio
async def test_pipe_persists_url_citations(monkeypatch):
    class _FakeChats:
        payload: dict | None = None

        @classmethod
        def upsert_message_to_chat_by_id_and_message_id(cls, chat_id, message_id, payload):
            cls.payload = {"chat_id": chat_id, "message_id": message_id, "payload": payload}

    module = types.SimpleNamespace(Chats=_FakeChats)
    monkeypatch.setitem(sys.modules, "open_webui.models.chats", module)

    pipe = Pipe()
    pipe.history_manager = _StubHistoryManager()
    engine = _StubEngine()
    engine.citations = [
        Citation(
            source_name="example.com",
            url="https://example.com/page",
            document=["Example"],
            metadata={"source": "https://example.com/page", "ordinal": 1},
        )
    ]
    pipe.engine = engine

    await pipe.pipe(
        body={"messages": [{"role": "user", "content": "hi"}]},
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=None,
        __tools__={},
        __metadata__={
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "model": {"id": "openai_responses.gpt-5.1"},
        },
    )

    assert _FakeChats.payload is not None
    sources = _FakeChats.payload["payload"].get("sources")
    assert sources and sources[0]["source"]["url"] == "https://example.com/page"
