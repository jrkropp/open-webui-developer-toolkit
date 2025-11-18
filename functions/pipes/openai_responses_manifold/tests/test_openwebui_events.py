"""Tests for the Open WebUI event helpers."""

from __future__ import annotations

import pytest

from openai_responses_manifold.utils import EventCall, EventEmitter


@pytest.mark.asyncio()
async def test_event_emitter_builds_payload_and_invokes_handler() -> None:
    observed: list[dict[str, object]] = []

    async def handler(event: dict[str, object]) -> None:
        observed.append(event)

    emitter = EventEmitter(handler)

    payload = await emitter.status("Working", done=True)

    assert payload == {
        "type": "status",
        "data": {"description": "Working", "done": True, "hidden": False},
    }
    assert observed == [payload]


@pytest.mark.asyncio()
async def test_event_call_input_unwraps_value_field() -> None:
    observed: list[dict[str, object]] = []

    async def handler(event: dict[str, object]) -> dict[str, object]:
        observed.append(event)
        return {"value": "user-stubbed-value"}

    event_call = EventCall(handler)

    value = await event_call.input("Title", "Message", placeholder="optional", default="starting-value")

    assert value == "user-stubbed-value"
    assert observed == [
        {
            "type": "input",
            "data": {
                "title": "Title",
                "message": "Message",
                "placeholder": "optional",
                "value": "starting-value",
            },
        }
    ]
