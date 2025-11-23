import asyncio

import pytest

from openai_responses_manifold.openwebui.events import OpenWebUIRuntimeEvents


@pytest.mark.asyncio
async def test_event_shapes():
    emitted: list[dict] = []

    async def emitter(payload):
        emitted.append(payload)

    events = OpenWebUIRuntimeEvents(emitter)

    await events.status("Thinking", done=False)
    await events.delta("hello")
    await events.replace("world")
    await events.citation({"title": "Logs"})
    await events.source({"url": "https://example.com"})
    await events.chat_completion({"done": True})
    await events.notification("note", level="warning")

    kinds = [e["type"] for e in emitted]
    assert kinds == [
        "status",
        "chat:message:delta",
        "chat:message",
        "citation",
        "source",
        "chat:completion",
        "notification",
    ]

    status_event = emitted[0]
    assert status_event["data"]["description"] == "Thinking"
    delta_event = emitted[1]
    assert delta_event["data"]["role"] == "assistant"
    assert delta_event["data"]["content"] == "hello"
    replace_event = emitted[2]
    assert replace_event["data"]["role"] == "assistant"
    assert replace_event["data"]["content"] == "world"
