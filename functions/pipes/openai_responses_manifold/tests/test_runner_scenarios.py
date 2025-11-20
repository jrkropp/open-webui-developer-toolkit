"""Scenario tests for the Responses engine orchestration."""

from __future__ import annotations

import json
import asyncio
import logging

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
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "item_id": "msg1",
                "content_index": 0,
                "delta": "Hello world",
            },
            {
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": "msg1",
                "content_index": 0,
                "text": "Hello world",
            },
            {
                "type": "response.completed",
                "response": {"output": []},
            },
        ]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client,
        item_store=orm.ItemStore(),
        logger=orm.get_logger(__name__),
    )

    chat_store.ensure("chat-1", {"id": "chat-1"})
    metadata = metadata_factory()

    result = await runner.run_streaming_turn(
        responses_body_factory(),
        valves=valves,
        metadata=metadata,
        event_emitter=spy_event_emitter,
        openwebui_tools={},
    )

    assert result.text == "Hello world"
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
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "id": "rs_drop_me",
                            "summary": [],
                        },
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
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "item_id": "msg2",
                "content_index": 0,
                "delta": "Result",
            },
            {
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": "msg2",
                "content_index": 0,
                "text": "Result",
            },
            {
                "type": "response.completed",
                "response": {"output": []},
            },
        ]
    )
    logger = orm.get_logger("openai_responses_manifold.runner")
    runner = orm.ResponsesEngine(
        client=fake_responses_client,
        item_store=orm.ItemStore(),
        logger=logger,
    )
    chat_store.ensure("chat-9", {"id": "chat-9"})
    metadata = metadata_factory(chat_id="chat-9", message_id="msg-9")

    def echo(value: str) -> str:
        return f"echo:{value}"

    await runner.run_streaming_turn(
        responses_body_factory(model="gpt-4o", store=False),
        valves=valves,
        metadata=metadata,
        event_emitter=spy_event_emitter,
        openwebui_tools={"echo": {"callable": echo}},
    )

    assert len(fake_responses_client.stream_calls) == 2, "runner should retry after tool output"
    _, _, _ = fake_responses_client.stream_calls[0]
    second_request, _, _ = fake_responses_client.stream_calls[1]
    reasoning_items = [item for item in second_request["input"] if item.get("type") == "reasoning"]
    assert reasoning_items and all("id" not in item for item in reasoning_items)
    assert second_request["input"][-2]["type"] == "function_call"
    assert second_request["input"][-2]["call_id"] == "call-1"
    appended = second_request["input"][-1]
    assert appended["type"] == "function_call_output"
    assert appended["call_id"] == "call-1"
    assert appended["output"] == "echo:hi"

    messages = [evt for evt in spy_event_emitter.events if evt["type"] == "chat:message"]
    final_content = messages[-1]["data"]["content"]
    assert final_content.strip().endswith("Result")
    assert orm.contains_marker(final_content)


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
        [{"type": "error", "code": "ERR", "message": "boom", "param": None}]
    )
    logger = orm.get_logger("openai_responses_manifold.runner")
    runner = orm.ResponsesEngine(
        client=fake_responses_client,
        item_store=orm.ItemStore(),
        logger=logger,
    )
    chat_store.ensure("chat-err", {"id": "chat-err"})
    metadata = metadata_factory(chat_id="chat-err", message_id="msg-err")

    tokens = orm.push_logging_context(session_logger_scope, logging.DEBUG)
    try:
        logger.debug("debug line")

        await runner.run_streaming_turn(
            responses_body_factory(),
            valves=valves,
            metadata=metadata,
            event_emitter=spy_event_emitter,
            openwebui_tools={},
        )
    finally:
        orm.pop_logging_context(tokens)

    types = spy_event_emitter.types()
    assert "citation" in types, "Log citation should be emitted when logs exist"
    assert orm.get_session_logs(session_logger_scope) == []

    completion_events = [
        event for event in spy_event_emitter.events if event["type"] == "chat:completion"
    ]
    assert len(completion_events) == 2  # error notification + terminal done event
    assert completion_events[0]["data"]["error"]["message"] == "boom"


@pytest.mark.asyncio()
async def test_usage_backfills_from_final_response(
    fake_responses_client: FakeResponsesClient,
    spy_event_emitter: SpyEventEmitter,
    metadata_factory,
    responses_body_factory,
    valves: orm.Pipe.Valves,
) -> None:
    usage_payload = {"prompt_tokens": 1, "completion_tokens": 2}
    fake_responses_client.enqueue_stream(
        [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "item_id": "msg3",
                "content_index": 0,
                "delta": "Hi",
            },
            {
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": "msg3",
                "content_index": 0,
                "text": "Hi",
            },
            {"type": "response.completed", "response": {"usage": usage_payload, "output": []}},
        ]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client,
        item_store=orm.ItemStore(),
        logger=orm.get_logger("runner"),
    )

    await runner.run_streaming_turn(
        responses_body_factory(),
        valves=valves,
        metadata=metadata_factory(),
        event_emitter=spy_event_emitter,
        openwebui_tools={},
    )

    completion_events = [
        event for event in spy_event_emitter.events if event["type"] == "chat:completion"
    ]
    assert any(
        event.get("data", {}).get("usage") == usage_payload for event in completion_events
    )


@pytest.mark.asyncio()
async def test_function_call_arguments_delta_handles_bad_json(
    fake_responses_client: FakeResponsesClient,
    spy_event_emitter: SpyEventEmitter,
    metadata_factory,
    responses_body_factory,
    valves: orm.Pipe.Valves,
) -> None:
    fake_responses_client.enqueue_stream(
        [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "item_id": "msg4",
                "content_index": 0,
                "delta": "Done",
            },
            {
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": "msg4",
                "content_index": 0,
                "text": "Done",
            },
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-err",
                            "name": "broken_tool",
                            "arguments": "{not-json}",
                        }
                    ]
                },
            },
        ]
    )
    runner = orm.ResponsesEngine(
        client=fake_responses_client,
        item_store=orm.ItemStore(),
        logger=orm.get_logger("runner"),
    )

    result = await runner.run_streaming_turn(
        responses_body_factory(),
        valves=valves,
        metadata=metadata_factory(),
        event_emitter=spy_event_emitter,
        openwebui_tools={"broken_tool": {"callable": lambda **_: None}},
    )

    assert result.text == "Done"
    status_events = [event for event in spy_event_emitter.events if event["type"] == "status"]
    assert any(
        event.get("data", {}).get("description") == "Skipping malformed tool arguments."
        for event in status_events
    )


@pytest.mark.asyncio()
async def test_cancelled_tasks_are_awaited() -> None:
    runner = orm.ResponsesEngine(logger=orm.get_logger("runner"))
    tasks = [asyncio.create_task(asyncio.sleep(0.01)) for _ in range(2)]
    original_tasks = list(tasks)

    await runner._cancel_tasks(tasks)

    assert not tasks
    assert all(task.cancelled() or task.done() for task in original_tasks)
