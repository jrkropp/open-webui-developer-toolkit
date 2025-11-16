"""Scenario tests for the Responses engine orchestration."""

from __future__ import annotations

import json
from collections import deque

import pytest

import openai_responses_manifold as orm
from .fakes import FakeResponsesClient, InMemoryChats, SpyEventEmitter


@pytest.mark.asyncio()
async def test_streaming_flow_emits_single_completion(
    fake_responses_client: FakeResponsesClient,
    spy_event_emitter: SpyEventEmitter,
    chat_store: InMemoryChats,
    metadata_factory,
    responses_body_factory,
    valves: orm.Pipe.Valves,
) -> None:
    fake_responses_client.enqueue_stream(
        [
            {"type": "response.output_text.delta", "delta": "Hello world"},
            {"type": "response.output_text.done", "output": []},
            {"type": "response.completed"},
        ]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client, logger=orm.SessionLogger.get_logger(__name__)
    )

    chat_store.ensure("chat-1", {"id": "chat-1"})
    metadata = metadata_factory()

    result = await runner.stream(
        responses_body_factory(),
        valves,
        spy_event_emitter,
        metadata,
        tools={},
    )

    assert result == "Hello world"
    assert len(fake_responses_client.stream_calls) == 1

    completion_events = [
        event for event in spy_event_emitter.events if event["type"] == "chat:completion"
    ]
    assert len(completion_events) == 1
    assert completion_events[0]["data"]["done"] is True


@pytest.mark.asyncio()
async def test_function_call_loop_executes_local_tools(
    fake_responses_client: FakeResponsesClient,
    spy_event_emitter: SpyEventEmitter,
    chat_store: InMemoryChats,
    metadata_factory,
    responses_body_factory,
    valves: orm.Pipe.Valves,
) -> None:
    fake_responses_client.enqueue_stream(
        [
            {
                "type": "response.output_items.done",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": json.dumps({"value": "hi"}),
                        }
                    ]
                },
            }
        ]
    )
    fake_responses_client.enqueue_stream(
        [
            {"type": "response.output_text.delta", "delta": "Result"},
            {"type": "response.output_text.done", "output": []},
            {"type": "response.completed"},
        ]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client, logger=orm.SessionLogger.get_logger("runner")
    )
    chat_store.ensure("chat-9", {"id": "chat-9"})
    metadata = metadata_factory(chat_id="chat-9", message_id="msg-9")

    def echo(value: str) -> str:
        return f"echo:{value}"

    await runner.stream(
        responses_body_factory(model="gpt-4o"),
        valves,
        spy_event_emitter,
        metadata,
        tools={"echo": {"callable": echo}},
    )

    assert len(fake_responses_client.stream_calls) == 2, "runner should retry after tool output"
    _, _, _ = fake_responses_client.stream_calls[0]
    second_request, _, _ = fake_responses_client.stream_calls[1]
    appended = second_request["input"][-1]
    assert appended["type"] == "function_call_output"
    assert appended["output"] == "echo:hi"

    messages = [evt for evt in spy_event_emitter.events if evt["type"] == "chat:message"]
    assert messages[-1]["data"]["content"] == "Result"


@pytest.mark.asyncio()
async def test_errors_emit_log_citation(
    fake_responses_client: FakeResponsesClient,
    spy_event_emitter: SpyEventEmitter,
    chat_store: InMemoryChats,
    metadata_factory,
    responses_body_factory,
    valves: orm.Pipe.Valves,
    session_logger_scope: str,
) -> None:
    fake_responses_client.enqueue_stream(
        [{"type": "response.error", "error": {"message": "boom"}}]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client, logger=orm.SessionLogger.get_logger("runner")
    )
    chat_store.ensure("chat-err", {"id": "chat-err"})
    metadata = metadata_factory(chat_id="chat-err", message_id="msg-err")

    orm.SessionLogger.logs[session_logger_scope] = deque(["debug line"])

    await runner.stream(
        responses_body_factory(),
        valves,
        spy_event_emitter,
        metadata,
        tools={},
    )

    types = spy_event_emitter.types()
    assert "citation" in types, "Log citation should be emitted when logs exist"

    completion_events = [
        event for event in spy_event_emitter.events if event["type"] == "chat:completion"
    ]
    assert len(completion_events) == 2  # error notification + terminal done event
    assert completion_events[0]["data"]["error"]["message"] == "boom"
