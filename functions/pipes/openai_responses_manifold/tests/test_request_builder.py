from openai_responses_manifold.adapters.openwebui.store import ItemStore
from openai_responses_manifold.adapters.openwebui.request_builder import build_responses_body
import pytest


@pytest.mark.asyncio()
async def test_build_responses_body_from_owui_messages_with_model() -> None:
    owui_request = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
    }
    store = ItemStore()
    body = await build_responses_body(
        owui_request, valves=type("V", (), {})(), metadata={}, item_store=store
    )

    assert body.model == "gpt-4o"
    assert body.stream is True
    assert body.input == [
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
    ]
    assert body.tools in (None, [])


@pytest.mark.asyncio()
async def test_build_responses_body_from_responses_like_payload() -> None:
    owui_request = {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        "stream": True,
    }
    body = await build_responses_body(
        owui_request, valves=type("V", (), {})(), metadata={}, item_store=ItemStore()
    )

    assert body.model == "gpt-4o"
    assert isinstance(body.input, list)
    assert body.tools in (None, [])


@pytest.mark.asyncio()
async def test_build_responses_body_prefers_explicit_instructions_over_system() -> None:
    valves = type("V", (), {"TRUNCATION": "auto", "PARALLEL_TOOL_CALLS": True})()
    owui_request = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "system message"},
            {"role": "user", "content": "hi"},
        ],
        "instructions": "explicit instructions",
    }
    store = ItemStore()
    body = await build_responses_body(
        owui_request, valves=valves, metadata={}, item_store=store
    )

    assert body.instructions == "explicit instructions"
    assert body.truncation == "auto"
    assert body.tools in (None, [])


@pytest.mark.asyncio()
async def test_build_responses_body_passes_through_tool_choice_and_include() -> None:
    valves = type("V", (), {"TRUNCATION": "auto", "PARALLEL_TOOL_CALLS": True})()
    owui_request = {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        "tool_choice": "required",
        "include": ["code_interpreter_call.outputs"],
        "store": True,
        "metadata": {"foo": "bar"},
    }
    body = await build_responses_body(
        owui_request, valves=valves, metadata={}, item_store=ItemStore()
    )

    assert body.tool_choice == "required"
    assert body.include == ["code_interpreter_call.outputs"]
    assert body.store is True
    assert body.metadata == {"foo": "bar"}
