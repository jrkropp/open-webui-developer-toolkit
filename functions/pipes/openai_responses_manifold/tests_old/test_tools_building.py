"""Tests for tool construction helpers."""

from __future__ import annotations

import json

import pytest

import openai_responses_manifold as orm
from openai_responses_manifold import ResponseCreateParams


def _responses_body(model: str = "gpt-4o") -> ResponseCreateParams:
    return ResponseCreateParams(model=model, input=[], stream=True)


def test_build_tools_includes_web_search_when_enabled() -> None:
    valves = orm.Pipe.Valves(
        ENABLE_WEB_SEARCH_TOOL=True,
        WEB_SEARCH_USER_LOCATION='{"country":"US"}',
    )
    tools = orm.build_tools(_responses_body(), valves)

    web_search = next(tool for tool in tools if tool["type"] == "web_search")
    assert web_search["user_location"]["country"] == "US"


def test_build_tools_applies_domains_and_external_web_access() -> None:
    valves = orm.Pipe.Valves(
        ENABLE_WEB_SEARCH_TOOL=True,
        WEB_SEARCH_ALLOWED_DOMAINS="https://openai.com, example.org, openai.com/docs",
        WEB_SEARCH_EXTERNAL_WEB_ACCESS=False,
    )
    tools = orm.build_tools(_responses_body(), valves)

    web_search = next(tool for tool in tools if tool["type"] == "web_search")
    assert web_search["filters"]["allowed_domains"] == ["openai.com", "example.org"]
    assert web_search["external_web_access"] is False


def test_build_tools_adds_remote_mcp_servers() -> None:
    valves = orm.Pipe.Valves(
        REMOTE_MCP_SERVERS_JSON=json.dumps(
            {
                "server_label": "Docs",
                "server_url": "https://example.com/mcp",
                "model_preference": {"gpt-4o": 1.0},
            }
        )
    )
    tools = orm.build_tools(_responses_body(), valves)

    mcp = next(tool for tool in tools if tool["type"] == "mcp")
    assert mcp["server_label"] == "Docs"
    assert mcp["server_url"] == "https://example.com/mcp"
    assert mcp["model_preference"]["gpt-4o"] == 1.0


def test_build_tools_dedupes_function_specs() -> None:
    owui_tools = {
        "a": {
            "spec": {
                "name": "duplicate",
                "description": "First",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        "b": {
            "spec": {
                "name": "duplicate",
                "description": "Second",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    }
    valves = orm.Pipe.Valves(ENABLE_STRICT_TOOL_CALLING=True)
    tools = orm.build_tools(_responses_body(), valves, openwebui_tools=owui_tools)

    function_tools = [tool for tool in tools if tool["type"] == "function"]
    assert len(function_tools) == 1
    assert function_tools[0]["name"] == "duplicate"


def test_build_tools_allows_extra_tools_and_override() -> None:
    owui_tools = {
        "custom": {
            "spec": {
                "name": "custom",
                "description": "Registry version",
                "parameters": {"type": "object", "properties": {"a": {"type": "string"}}},
            }
        }
    }
    extra_tools = [
        {
            "type": "function",
            "name": "custom",
            "description": "Override from extra_tools",
            "parameters": {"type": "object", "properties": {"a": {"type": "integer"}}},
        }
    ]
    valves = orm.Pipe.Valves(ENABLE_STRICT_TOOL_CALLING=False)
    tools = orm.build_tools(
        _responses_body(),
        valves,
        openwebui_tools=owui_tools,
        extra_tools=extra_tools,
    )

    function_tools = [tool for tool in tools if tool.get("type") == "function" and tool.get("name") == "custom"]
    assert len(function_tools) == 1
    tool = function_tools[0]
    assert tool["description"] == "Override from extra_tools"
    assert tool["parameters"]["properties"]["a"]["type"] == "integer"


def test_strictifies_extra_function_tools_when_strict_enabled() -> None:
    extra_tools = [
        {
            "type": "function",
            "name": "strict_me",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
        }
    ]
    valves = orm.Pipe.Valves(ENABLE_STRICT_TOOL_CALLING=True)
    tools = orm.build_tools(_responses_body(), valves, extra_tools=extra_tools)

    fn = next(tool for tool in tools if tool.get("name") == "strict_me")
    assert fn["strict"] is True
    params = fn["parameters"]
    assert params["additionalProperties"] is False
    assert sorted(params.get("required") or []) == ["count", "text"]
    assert params["properties"]["text"]["type"] == "string"
    assert params["properties"]["count"]["type"] == "integer"


def test_tool_summaries_for_log_captures_web_search_details() -> None:
    tools = [
        {
            "type": "web_search",
            "context": {"size": "high"},
            "filters": {"allowed_domains": ["openai.com", "example.com"]},
            "external_web_access": False,
        },
        {
            "type": "function",
            "name": "do_it",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"foo": {"type": "string"}},
            },
        },
    ]

    summaries = orm.tool_summaries_for_log(tools)
    assert len(summaries) == 2
    summary_web = summaries[0]
    assert summary_web.startswith("[0] type=web_search")
    assert "context.size=high" in summary_web
    assert "filters.allowed_domains=2" in summary_web
    assert "external_web_access=False" in summary_web

    summary_fn = summaries[1]
    assert summary_fn.startswith("[1] type=function name=do_it")
    assert "strict=True" in summary_fn
    assert "params=foo" in summary_fn


@pytest.mark.asyncio()
async def test_execute_tool_calls_supports_sync_and_async() -> None:
    calls = [
        {"type": "function_call", "name": "echo", "call_id": "1", "arguments": json.dumps({"text": "hi"})},
        {"type": "function_call", "name": "add", "call_id": "2", "arguments": json.dumps({"a": 1, "b": 2})},
    ]

    async def add(a: int, b: int) -> int:
        return a + b

    registry = {
        "echo": {"callable": lambda text: f"echo:{text}"},
        "add": {"callable": add},
    }

    outputs = await orm.execute_tool_calls(calls, registry)
    assert outputs[0]["output"] == "echo:hi"
    assert outputs[1]["output"] == "3"


def test_apply_parallel_tool_policy_requests_sources_include() -> None:
    pipe = orm.Pipe()
    valves = pipe.Valves(WEB_SEARCH_INCLUDE_SOURCES=True)
    body = _responses_body()
    body.tools = [{"type": "web_search"}]

    pipe._apply_parallel_tool_policy(body, valves)

    assert body.parallel_tool_calls is False
    assert "web_search_call.action.sources" in (body.include or [])


def test_apply_parallel_tool_policy_allows_opt_out_of_sources() -> None:
    pipe = orm.Pipe()
    valves = pipe.Valves(WEB_SEARCH_INCLUDE_SOURCES=False)
    body = _responses_body()
    body.tools = [{"type": "web_search"}]

    pipe._apply_parallel_tool_policy(body, valves)

    assert body.include is None


def test_apply_parallel_tool_policy_adds_code_interpreter_outputs() -> None:
    pipe = orm.Pipe()
    valves = pipe.Valves()
    body = _responses_body()
    body.tools = [{"type": "code_interpreter"}]

    pipe._apply_parallel_tool_policy(body, valves)

    assert body.parallel_tool_calls is True
    assert "code_interpreter_call.outputs" in (body.include or [])


def test_build_tools_includes_code_interpreter_when_enabled() -> None:
    valves = orm.Pipe.Valves(ENABLE_CODE_INTERPRETER_TOOL=True)
    tools = orm.build_tools(_responses_body(), valves)

    ci_tool = next(tool for tool in tools if tool["type"] == "code_interpreter")
    assert ci_tool["container"] == {"type": "auto"}


def test_build_tools_respects_container_override_and_features() -> None:
    valves = orm.Pipe.Valves(
        ENABLE_CODE_INTERPRETER_TOOL=True,
        CODE_INTERPRETER_CONTAINER_JSON='{"type": "legacy"}',
    )
    tools = orm.build_tools(_responses_body(), valves, features={"code_interpreter": {"container": {"type": "feat"}}})

    ci_tool = next(tool for tool in tools if tool["type"] == "code_interpreter")
    assert ci_tool["container"] == {"type": "feat"}
