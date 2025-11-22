"""Minimal smoke tests against the Pipe contract expected by Open WebUI."""

from __future__ import annotations

from typing import Any

import pytest

import openai_responses_manifold as orm


@pytest.mark.asyncio()
async def test_pipes_listing_and_pipe_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure Pipe advertises models and delegates streaming to the runner hook."""
    pipe = orm.Pipe()

    async def fake_streaming_loop(
        self: orm.ResponsesEngine,
        body: orm.ResponseCreateParams,
        *,
        ctx: orm.TurnContext,
        events: orm.RuntimeEvents,
        tool_registry=None,
        **_: Any,
    ) -> orm.TurnResult:
        await events.replace("stub")
        return orm.TurnResult(text="final-output", usage=None, citations=[])

    monkeypatch.setattr(orm.ResponsesEngine, "run_streaming_turn", fake_streaming_loop, raising=False)

    events: list[dict[str, Any]] = []
    css_patches: list[dict[str, Any]] = []

    async def fake_event_emitter(event: dict[str, Any]) -> None:
        events.append(event)

    async def fake_event_call(payload: dict[str, Any]) -> None:
        css_patches.append(payload)

    user = {"id": "user-1", "email": "u@example.com", "valves": {}}
    metadata = {
        "session_id": "sess-1",
        "chat_id": "chat-1",
        "message_id": "msg-1",
        "features": {"openai_responses": {}},
        "model": {"id": "openai_responses.gpt-4o"},
    }
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    models = await pipe.pipes()
    assert all("id" in m and "name" in m for m in models)

    result = await pipe.pipe(
        body,
        user,
        __event_emitter__=fake_event_emitter,
        __event_call__=fake_event_call,
        __metadata__=metadata,
        __tools__={},
    )

    assert result == "final-output"
    assert events and events[0]["type"] == "chat:message"
    assert css_patches  # CSS helper injected exactly once
