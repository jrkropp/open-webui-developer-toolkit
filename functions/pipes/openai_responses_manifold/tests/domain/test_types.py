from __future__ import annotations

import asyncio

from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.domain import (
    Citation,
    RuntimeEvents,
    ToolCall,
    ToolResult,
    TurnContext,
    TurnResult,
    TurnState,
)


def test_turn_context_defaults_and_isolation():
    cfg = merge_valves(PipeValves(), UserValves())

    ctx_one = TurnContext(runtime_config=cfg, model_id="gpt-5.1")
    ctx_two = TurnContext(runtime_config=cfg, model_id="gpt-5.1-mini")

    ctx_one.metadata["chat_id"] = "chat-1"
    ctx_one.features.add("tools")

    assert ctx_one.runtime_config is cfg
    assert ctx_one.model_id == "gpt-5.1"
    assert ctx_one.metadata == {"chat_id": "chat-1"}
    assert ctx_one.features == {"tools"}

    assert ctx_two.metadata == {}
    assert ctx_two.features == set()


def test_turn_state_defaults_are_isolated():
    first_state = TurnState()
    second_state = TurnState()

    first_state.citations.append(Citation(source_name="src", url=None))
    first_state.structured_items.append({"type": "function_call_output"})

    assert first_state.assistant_visible_text == ""
    assert first_state.assistant_internal_text == ""
    assert first_state.usage is None
    assert first_state.tool_calls_executed == 0
    assert first_state.error_message is None

    assert second_state.citations == []
    assert second_state.structured_items == []


def test_tool_call_and_result_containers():
    tool_call = ToolCall(call_id="call-1", name="foo", arguments_json="{}")
    tool_result = ToolResult(call_id="call-1", output="ok", status="ok")

    assert tool_call.call_id == "call-1"
    assert tool_call.name == "foo"
    assert tool_call.arguments_json == "{}"

    assert tool_result.call_id == "call-1"
    assert tool_result.output == "ok"
    assert tool_result.status == "ok"
    assert tool_result.error_message is None


def test_citation_and_turn_result_defaults():
    citation = Citation(source_name="example.com", url="https://example.com")
    result = TurnResult(text="hello", usage={"total_tokens": 5}, citations=[citation])

    assert citation.document == []
    assert citation.metadata == {}

    assert result.text == "hello"
    assert result.usage == {"total_tokens": 5}
    assert result.citations == [citation]
    assert result.error is None


class _DummyEvents(RuntimeEvents):
    async def status(self, description: str, *, done: bool = False, **extra):
        return None

    async def delta(self, content: str):
        return None

    async def replace(self, content: str):
        return None

    async def citation(self, data: dict):
        return None

    async def source(self, data: dict):
        return None

    async def chat_completion(self, data: dict):
        return None

    async def notification(self, content: str, *, level: str = "info"):
        return None


def test_runtime_events_protocol_recognizes_implementations():
    events = _DummyEvents()

    assert isinstance(events, RuntimeEvents)
    assert asyncio.iscoroutinefunction(events.status)
    assert asyncio.iscoroutinefunction(events.chat_completion)
