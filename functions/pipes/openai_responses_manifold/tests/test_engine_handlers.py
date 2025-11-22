import pytest

import openai_responses_manifold as orm
import openai_responses_manifold.domain.engine as orm_engine
from openai_responses_manifold.adapters.openai.events import (
    ResponseCodeInterpreterCallCodeDoneEvent,
    ResponseCodeInterpreterCallCompletedEvent,
    ResponseCodeInterpreterCallInProgressEvent,
    ResponseCodeInterpreterCallInterpretingEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)


def _ctx(valves: orm.Pipe.Valves) -> orm.TurnContext:
    meta = {"chat_id": "chat-1", "message_id": "msg-1", "model": {"id": "gpt-4o"}}
    return orm.TurnContext(valves=valves, metadata=meta, user_identifier=None, owui_model_id="gpt-4o", features={})


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

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
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

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
    )

    tool_calls = [
        {
            "type": "function_call",
            "name": "echo",
            "arguments": "{}",
        }
    ]

    executor = orm.ToolExecutor(engine.logger)
    outputs = await executor.run(tool_calls, {}, emit_status=handler.emit_status, valves=valves)
    assert outputs == []
    assert spy_event_emitter.types() == ["status"]

    appended = await handler.append_tool_outputs([
        {"type": "function_call", "output": "ok"}
    ])

    assert appended is True
    assert handler.state.response_text.endswith("[hidden]")
    assert body.input[-1]["output"] == "ok"


@pytest.mark.asyncio()
async def test_code_interpreter_items_emit_citation_and_status(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
    )

    item = {
        "type": "code_interpreter_call",
        "code_interpreter_call": {
            "code": "print('hi')",
            "outputs": [{"type": "logs", "logs": "hello"}],
        },
    }
    await handler._handle_item_done(
        ResponseOutputItemDoneEvent(
            item=item,
            type="response.output_item.done",
            output_index=0,
            item_id="ci_123",
        )
    )

    assert any(ev for ev in spy_event_emitter.events if ev["type"] == "status")
    assert handler.state.citations


@pytest.mark.asyncio()
async def test_code_interpreter_item_uses_fallback_code_when_no_outputs(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
    )

    # simulate code_done event before item arrives
    await handler.handle_event(
        ResponseCodeInterpreterCallCodeDoneEvent(output_index=0, item_id="ci_123", code="print('hi')")
    )

    item = {
        "type": "code_interpreter_call",
        "code_interpreter_call": {
            # no code or outputs -> should fallback to stored snippet
        },
    }
    await handler._handle_item_done(
        ResponseOutputItemDoneEvent(
            item=item,
            type="response.output_item.done",
            output_index=0,
            item_id="ci_123",
        )
    )

    # citation should exist even though outputs were empty
    assert any(cit.get("provider") == "openai:code_interpreter" for cit in handler.state.citations)


@pytest.mark.asyncio()
async def test_code_interpreter_result_citation_uses_final_text(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
    )

    # simulate code_interpreter_call with no outputs/logs
    await handler._handle_item_done(
        ResponseOutputItemDoneEvent(
            item={"type": "code_interpreter_call", "code_interpreter_call": {}},
            type="response.output_item.done",
            output_index=0,
            item_id="ci_456",
        )
    )

    assert 0 in handler.state.pending_ci_results

    # when the final assistant text arrives, a result citation should be emitted
    await handler._handle_text_done(ResponseOutputTextDoneEvent(text="Result is 2.0"))

    assert handler.state.pending_ci_results == set()
    assert any(cit.get("title") == "Code interpreter result" for cit in handler.state.citations)
    assert any("Result is 2.0" in cit.get("snippet", "") for cit in handler.state.citations)
    # Ensure we didn't pick up hidden markers as the result text.
    assert not any("openai_responses:v2" in cit.get("snippet", "") for cit in handler.state.citations)


@pytest.mark.asyncio()
async def test_event_handler_emits_statuses_for_code_interpreter(
    monkeypatch: pytest.MonkeyPatch,
    responses_body_factory,
    valves,
    spy_event_emitter,
):
    body = responses_body_factory()
    engine = orm.ResponsesEngine()
    monkeypatch.setattr(engine, "_schedule_reasoning_statuses", lambda *_, **__: [])

    runtime_events = orm.OpenWebUIRuntimeEvents(orm.EventEmitter(spy_event_emitter))
    handler = orm_engine._StreamSession(
        engine,
        body,
        _ctx(valves),
        runtime_events,
    )

    await handler.handle_event(
        ResponseCodeInterpreterCallInProgressEvent(
            output_index=0, item_id="ci_status", code_interpreter_call={}
        )
    )
    await handler.handle_event(
        ResponseCodeInterpreterCallInterpretingEvent(
            output_index=0, item_id="ci_status", code_interpreter_call={}
        )
    )
    await handler.handle_event(
        ResponseCodeInterpreterCallCodeDoneEvent(
            output_index=0, item_id="ci_status", code="print('hi')"
        )
    )
    await handler.handle_event(
        ResponseCodeInterpreterCallCompletedEvent(
            output_index=0, item_id="ci_status", code_interpreter_call={}
        )
    )

    assert spy_event_emitter.types() == ["status", "status", "status", "status"]
