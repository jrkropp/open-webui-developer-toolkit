import pytest

import openai_responses_manifold as orm
import openai_responses_manifold.application.engine as orm_engine
from openai_responses_manifold.domain.openai_events import (
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)


@pytest.mark.asyncio()
async def test_event_handler_tracks_text_and_completion(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])

    handler = orm_engine._StreamSession(
        engine,
        body,
        valves,
        {"chat_id": "chat-1", "message_id": "msg-1", "model": {"id": "gpt-4o"}},
        spy_event_emitter,
        openwebui_tools=None,
    )

    await handler.handle_event(ResponseOutputTextDeltaEvent(delta="Hello"))
    await handler.handle_event(ResponseOutputTextDoneEvent(text="Hello world"))

    assert handler.state.response_text == "Hello"
    assert spy_event_emitter.types()[:2] == ["chat:message:delta", "chat:message"]


@pytest.mark.asyncio()
async def test_event_handler_executes_tools_with_registry(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])
    monkeypatch.setattr(engine.history_persistence, "persist_items_for_message", lambda *_, **__: "[hidden]")

    handler = orm_engine._StreamSession(
        engine,
        body,
        valves,
        {"chat_id": "chat-1", "message_id": "msg-1", "model": {"id": "gpt-4o"}},
        spy_event_emitter,
        openwebui_tools={},
    )

    tool_calls = [
        {
            "type": "function_call",
            "name": "echo",
            "arguments": "{}",
        }
    ]

    outputs = await handler.execute_tool_calls(tool_calls)
    assert outputs == []
    assert spy_event_emitter.types() == ["status"]

    appended = await handler.append_tool_outputs([
        {"type": "function_call", "output": "ok"}
    ])

    assert appended is True
    assert handler.state.response_text.endswith("[hidden]")
    assert body.input[-1]["output"] == "ok"
