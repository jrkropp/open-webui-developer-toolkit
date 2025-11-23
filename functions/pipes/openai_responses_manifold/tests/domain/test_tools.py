import pytest

from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.core.model_catalog import features
from openai_responses_manifold.domain.tools import ToolDefinition, ToolPolicy


class _StubRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        self._definitions = definitions

    def iter_definitions(self):
        return list(self._definitions)


def _default_cfg():
    return merge_valves(PipeValves(), UserValves())


def test_tool_policy_merge_order_and_deduplication():
    cfg = _default_cfg()
    registry = _StubRegistry(
        [
            ToolDefinition(
                name="weather_lookup",
                description="Registry weather",
                parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                strict=False,
                source="registry",
            )
        ]
    )

    body_tools = [
        {
            "type": "function",
            "name": "weather_lookup",
            "description": "Body tool",
            "parameters": {"type": "object", "properties": {"body": {"type": "string"}}},
        }
    ]
    extra_tools = [
        {
            "type": "function",
            "name": "weather_lookup",
            "description": "Filter override",
            "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}},
        }
    ]
    mcp_tools = [
        {"type": "mcp", "server_label": "remote", "server_url": "https://example.com"}
    ]
    web_search_tools = [{"type": "web_search", "search_context_size": "low"}]

    tools = ToolPolicy.build_responses_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
        registry=registry,
        body_tools=body_tools,
        extra_tools=extra_tools,
        mcp_tools=mcp_tools,
        web_search_tools=web_search_tools,
    )

    assert len(tools) == 3
    assert (tools[0].get("type"), tools[0].get("name")) == ("function", "weather_lookup")
    assert tools[1].get("type") == "mcp"
    assert tools[1].get("server_label") == "remote"
    assert tools[2].get("type") == "web_search"
    assert tools[2].get("search_context_size") == "low"
    assert tools[0]["parameters"]["required"] == ["filter"]


def test_tool_policy_respects_function_capability_gate():
    cfg = _default_cfg()
    registry = _StubRegistry(
        [
            ToolDefinition(
                name="example",
                description="Should be gated",
                parameters={},
                strict=False,
                source="registry",
            )
        ]
    )

    mcp_tools = [{"type": "mcp", "server_label": "remote", "server_url": "https://example.com"}]

    tools = ToolPolicy.build_responses_tools(
        model_id="chatgpt-4o-latest",
        features=features("chatgpt-4o-latest"),
        cfg=cfg,
        registry=registry,
        body_tools=None,
        extra_tools=None,
        mcp_tools=mcp_tools,
        web_search_tools=None,
    )

    assert len(tools) == 1
    assert tools[0].get("type") == "mcp"
    assert tools[0].get("server_label") == "remote"


def test_tool_policy_applies_strict_schema_defaults():
    cfg = _default_cfg()
    registry = _StubRegistry(
        [
            ToolDefinition(
                name="adder",
                description="Adds numbers",
                parameters={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a"],
                },
                strict=False,
                source="registry",
            )
        ]
    )

    tools = ToolPolicy.build_responses_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
        registry=registry,
        body_tools=None,
        extra_tools=None,
        mcp_tools=None,
        web_search_tools=None,
    )

    assert tools[0]["strict"] is True
    parameters = tools[0]["parameters"]
    assert parameters["additionalProperties"] is False
    assert set(parameters["required"]) == {"a", "b"}
    assert parameters["properties"]["b"]["type"] == ["number", "null"]
