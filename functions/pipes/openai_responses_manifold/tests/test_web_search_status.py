import sys
import types
import pytest

# Stub minimal open_webui modules required for import
owui_root = types.ModuleType("open_webui")
models_pkg = types.ModuleType("open_webui.models")
sys.modules.setdefault("open_webui", owui_root)
sys.modules.setdefault("open_webui.models", models_pkg)
sys.modules.setdefault("open_webui.models.chats", types.SimpleNamespace(Chats=object))
sys.modules.setdefault(
    "open_webui.models.models",
    types.SimpleNamespace(ModelForm=object, Models=object),
)
sys.modules.setdefault("open_webui.models.users", types.SimpleNamespace(Users=object))
sys.modules.setdefault("open_webui.utils", types.ModuleType("open_webui.utils"))
sys.modules.setdefault(
    "open_webui.utils.misc",
    types.SimpleNamespace(get_last_user_message=lambda messages: messages[-1] if messages else {}),
)

from functions.pipes.openai_responses_manifold.openai_responses_manifold import Pipe, ResponsesBody


@pytest.mark.asyncio
async def test_web_search_status_updates(monkeypatch):
    pipe = Pipe()
    body = ResponsesBody(model="gpt-4o", input=[{"role": "user", "content": "hi"}])
    valves = pipe.Valves()
    valves.PERSIST_TOOL_RESULTS = False

    async def fake_stream(params, api_key, base_url):
        events = [
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "web_search_call",
                    "id": "ws1",
                    "status": "in_progress",
                    "action": {"type": "search", "query": "widget"},
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "web_search_call",
                    "id": "ws1",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "widget",
                        "sources": [{"type": "url", "url": "https://example.com"}],
                    },
                },
            },
            {"type": "response.completed", "response": {"output": [], "usage": {}}},
        ]
        for e in events:
            yield e

    monkeypatch.setattr(pipe, "send_openai_responses_streaming_request", fake_stream)

    captured = []

    async def emitter(event):
        if event["type"] == "status":
            captured.append(event["data"])

    await pipe._run_streaming_loop(body, valves, emitter, metadata={}, tools={})

    actions = [e.get("action") for e in captured if e.get("action")]
    assert "web_search_queries_generated" in actions
    assert "sources_retrieved" in actions
    assert "web_search" in actions

    web_event = next(e for e in captured if e.get("action") == "web_search")
    assert web_event["urls"] == ["https://example.com"]
    assert web_event["query"] == "widget"
