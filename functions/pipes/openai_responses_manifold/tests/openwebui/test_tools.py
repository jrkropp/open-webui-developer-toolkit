import asyncio
import json

import pytest

from openai_responses_manifold.domain.types import ToolCall
from openai_responses_manifold.openwebui.tools import OpenWebUIToolExecutor, OpenWebUIToolRegistry


def test_registry_builds_definitions():
    registry = OpenWebUIToolRegistry(
        {
            "a": {"spec": {"name": "hello", "description": "hi", "parameters": {"type": "object"}}},
            "b": {"spec": {}},
        }
    )
    defs = list(registry.iter_definitions())
    assert defs[0].name == "hello"
    assert defs[0].parameters == {"type": "object"}
    assert registry.get("hello") is not None


@pytest.mark.asyncio
async def test_executor_runs_sync_and_async_tools():
    async def async_tool(x: int) -> dict:
        return {"value": x + 1}

    def sync_tool(y: int) -> dict:
        return {"value": y * 2}

    registry_payload = {
        "async": {"spec": {"name": "async_tool"}, "callable": async_tool},
        "sync": {"spec": {"name": "sync_tool"}, "callable": sync_tool},
    }

    executor = OpenWebUIToolExecutor(registry_payload)
    calls = [
        ToolCall(call_id="1", name="async_tool", arguments_json=json.dumps({"x": 1})),
        ToolCall(call_id="2", name="sync_tool", arguments_json=json.dumps({"y": 3})),
        ToolCall(call_id="3", name="missing", arguments_json="{}"),
    ]

    results = await executor.execute(calls)
    assert results[0].status == "ok" and json.loads(results[0].output)["value"] == 2
    assert results[1].status == "ok" and json.loads(results[1].output)["value"] == 6
    assert results[2].status == "error"
