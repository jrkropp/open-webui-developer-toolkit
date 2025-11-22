import json

from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.domain.history import HistoryManager
from openai_responses_manifold.domain.types import TurnContext
from openai_responses_manifold.openwebui import build_mcp_tools, build_turn_context, map_completions_to_responses


class _DummyStore:
    def save_items(self, *args, **kwargs):  # pragma: no cover - not used in these tests
        return []

    def load_items(self, chat_key, item_ids, model_id=None):
        return {}


def test_build_turn_context_normalizes_model():
    cfg = merge_valves(PipeValves(), UserValves())
    ctx = build_turn_context(
        pipe_valves=cfg,
        user_valves=UserValves(),
        runtime_cfg=cfg,
        __user__={"id": "u1", "email": "me@example.com"},
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )
    assert ctx.model_id == "gpt-5.1"
    assert "function_calling" in ctx.features


def test_map_completions_to_responses_builds_request():
    cfg = merge_valves(PipeValves(), UserValves())
    ctx = TurnContext(runtime_config=cfg, model_id="gpt-5.1", features=set(), metadata={"owui_model_id": "openai_responses.gpt-5.1"})
    history_manager = HistoryManager(_DummyStore())
    request, base_tools, extra_tools = map_completions_to_responses(
        body={
            "messages": [
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "hello"},
            ],
            "max_tokens": 99,
            "reasoning_effort": "medium",
            "tools": [{"type": "function", "name": "a"}],
            "extra_tools": [{"type": "function", "name": "b"}],
        },
        ctx=ctx,
        history_manager=history_manager,
        history_key={"chat_id": "c1", "pipe_id": "p1"},
    )

    assert request.model == "gpt-5.1"
    assert request.max_output_tokens == 99
    assert request.reasoning == {"effort": "medium"}
    assert base_tools[0]["name"] == "a"
    assert extra_tools[0]["name"] == "b"


def test_build_mcp_tools_parses_json():
    cfg = merge_valves(PipeValves(REMOTE_MCP_SERVERS_JSON=json.dumps([{"server_label": "foo", "server_url": "https://x"}])), UserValves())
    tools = build_mcp_tools(cfg)
    assert tools[0]["type"] == "mcp"
    assert tools[0]["server_label"] == "foo"
