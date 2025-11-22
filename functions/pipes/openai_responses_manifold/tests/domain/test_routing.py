import pytest

from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.domain import TurnContext, route_auto_model
from openai_responses_manifold.openai_api.types import ResponsesRequest


class _DummyEvents:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.notifications: list[tuple[str, str]] = []

    async def status(self, description: str, *, done: bool = False, **extra):
        self.statuses.append(description)

    async def delta(self, content: str):
        pass

    async def replace(self, content: str):
        pass

    async def citation(self, data: dict):
        pass

    async def source(self, data: dict):
        pass

    async def chat_completion(self, data: dict):
        pass

    async def notification(self, content: str, *, level: str = "info"):
        self.notifications.append((content, level))


class _DummyClient:
    def __init__(self, response: dict | Exception):
        self.response = response
        self.calls: list[ResponsesRequest] = []

    async def create_response(self, request: ResponsesRequest, *, base_url: str, api_key: str):
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_route_auto_alias_defaults_to_chat_latest():
    cfg = merge_valves(PipeValves(), UserValves())
    ctx = TurnContext(
        runtime_config=cfg,
        model_id="openai_responses.gpt-5-auto",
        metadata={"owui_model_id": "openai_responses.gpt-5-auto"},
    )

    req = ResponsesRequest(model="openai_responses.gpt-5-auto", input="hi")
    events = _DummyEvents()

    result = await route_auto_model(_DummyClient({}), req, ctx, [], events)

    assert result.model == "gpt-5.1-chat-latest"
    assert events.notifications == [
        ("Model router coming soon — using gpt‑5.1‑chat‑latest for now.", "info")
    ]


@pytest.mark.asyncio
async def test_route_auto_dev_applies_router_decision():
    cfg = merge_valves(PipeValves(), UserValves())
    ctx = TurnContext(
        runtime_config=cfg,
        model_id="openai_responses.gpt-5-auto-dev",
        metadata={"owui_model_id": "openai_responses.gpt-5-auto-dev"},
    )

    req = ResponsesRequest(model="openai_responses.gpt-5-auto-dev", input="hi")
    events = _DummyEvents()

    router_payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"model": "gpt-5-mini", "reasoning_effort": "low", "explanation": "Simple task"}',
                    }
                ],
            }
        ]
    }

    result = await route_auto_model(_DummyClient(router_payload), req, ctx, [], events)

    assert result.model == "gpt-5-mini"
    assert result.reasoning.get("effort") == "low"
    assert result.model_router_result == {
        "model": "gpt-5-mini",
        "reasoning_effort": "low",
        "explanation": "Simple task",
    }
    assert any("Routing to gpt-5-mini" in status for status in events.statuses)


@pytest.mark.asyncio
async def test_route_auto_dev_handles_router_failure_gracefully():
    cfg = merge_valves(PipeValves(), UserValves())
    ctx = TurnContext(
        runtime_config=cfg,
        model_id="openai_responses.gpt-5-auto-dev",
        metadata={"owui_model_id": "openai_responses.gpt-5-auto-dev"},
    )

    req = ResponsesRequest(model="openai_responses.gpt-5-auto-dev", input="hi")
    events = _DummyEvents()

    result = await route_auto_model(_DummyClient(Exception("boom")), req, ctx, [], events)

    assert result.model == "gpt-5-auto-dev"
    assert result.reasoning is None
    assert result.model_router_result is None
    assert events.statuses == []
