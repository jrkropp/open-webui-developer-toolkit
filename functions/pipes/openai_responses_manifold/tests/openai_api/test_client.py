import asyncio
import json
from typing import Any

import pytest
from aiohttp import web

from openai_responses_manifold.openai_api.client import OpenAIClient
from openai_responses_manifold.openai_api.types import (
    ResponseCompletedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponsesRequest,
)


@pytest.fixture
async def test_server():
    app = web.Application()

    async def handle_response(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        auth = request.headers.get("Authorization")
        assert auth == "Bearer test-key"

        if body.get("stream"):
            response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)

            events: list[dict[str, Any]] = [
                {"type": "response.output_text.delta", "delta": "Hello"},
                {
                    "type": "response.output_item.added",
                    "item": {"type": "message", "role": "assistant", "content": []},
                },
                {"type": "response.completed", "response": {"id": "resp_123"}},
            ]
            for payload in events:
                message = f"data: {json.dumps(payload)}\n\n"
                await response.write(message.encode())
                await asyncio.sleep(0)

            await response.write(b": comment\n\n")
            await response.write_eof()
            return response

        return web.json_response({"output": body.get("input", []), "model": body.get("model")})

    app.router.add_post("/responses", handle_response)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield base_url
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_stream_responses_yields_typed_events(test_server: str):
    client = OpenAIClient()
    request = ResponsesRequest(model="gpt-4o", stream=True)

    events = []
    async for event in client.stream_responses(request, base_url=test_server, api_key="test-key"):
        events.append(event)

    await client.close()

    assert [type(e) for e in events] == [
        ResponseOutputTextDeltaEvent,
        ResponseOutputItemAddedEvent,
        ResponseCompletedEvent,
    ]
    assert events[0].delta == "Hello"


@pytest.mark.asyncio
async def test_create_response_returns_json_payload(test_server: str):
    client = OpenAIClient()
    request = ResponsesRequest(model="gpt-4o", stream=False, input=[{"type": "message"}])

    response = await client.create_response(request, base_url=test_server, api_key="test-key")
    await client.close()

    assert response["output"] == [{"type": "message"}]
    assert response["model"] == "gpt-4o"
