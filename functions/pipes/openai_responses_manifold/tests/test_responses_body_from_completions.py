"""Baseline tests for mapping OpenWebUI chat payloads to ResponseCreateParams."""

from __future__ import annotations

import pytest

from openai_responses_manifold import CompletionCreateParams
from openai_responses_manifold.openwebui.store import ItemStore
from openai_responses_manifold.services.request_builder import build_responses_body


@pytest.mark.asyncio()
async def test_responses_body_from_completions_maps_reasoning_and_tokens() -> None:
    """Ensure reasoning effort and max_tokens are mapped to the new schema."""
    completions = CompletionCreateParams(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Act helpful"},
            {"role": "user", "content": "hi"},
        ],
        max_tokens=128,
        reasoning_effort="minimal",
    )

    responses = await build_responses_body(
        completions.model_dump(),
        valves=type("V", (), {"TRUNCATION": "auto", "PARALLEL_TOOL_CALLS": True})(),
        metadata={},
        item_store=ItemStore(),
    )

    assert responses.max_output_tokens == 128
    assert responses.reasoning is not None
    assert responses.reasoning.effort == "minimal"
    assert responses.instructions == "Act helpful"
    assert responses.truncation == "auto"
    assert responses.include_obfuscation is False
    assert responses.tools in (None, [])


@pytest.mark.asyncio()
async def test_responses_body_from_completions_converts_messages() -> None:
    """Validate that messages become the structured Responses API input."""
    messages = [
        {"role": "system", "content": "System prompt"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": {"url": "https://example.com/pic.png"}},
            ],
        },
        {"role": "assistant", "content": "intermediate result"},
    ]

    completions = CompletionCreateParams(
        model="gpt-4o",
        messages=messages,
    )

    responses = await build_responses_body(
        completions.model_dump(),
        valves=type("V", (), {})(),
        metadata={},
        item_store=ItemStore(),
    )

    assert isinstance(responses.input, list)
    assert len(responses.input) == 2  # system message is removed

    user_block = responses.input[0]
    assert user_block["role"] == "user"
    block_types = [block["type"] for block in user_block["content"]]  # type: ignore[index]
    assert block_types == ["input_text", "input_image"]

    assistant_block = responses.input[1]
    assert assistant_block["role"] == "assistant"
    content = assistant_block["content"][0]  # type: ignore[index]
    assert content["type"] == "output_text"
    assert content["text"] == "intermediate result"
    assert responses.tools in (None, [])


@pytest.mark.asyncio()
async def test_responses_body_prefers_history_input_when_provided() -> None:
    history_input = [
        {"role": "assistant", "content": [{"type": "output_text", "text": "restored"}]},
    ]
    responses = await build_responses_body(
        {"model": "gpt-4o", "input": history_input},
        valves=type("V", (), {})(),
        metadata={},
        item_store=ItemStore(),
    )
    assert responses.input == history_input
    assert responses.tools in (None, [])
