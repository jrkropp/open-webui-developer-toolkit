from openai_responses_manifold.infra import ItemStore
from openai_responses_manifold.services.history import HistoryPersistence, HistoryRepository
from openai_responses_manifold.services.request_builder import build_responses_body
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
async def test_build_responses_body_hydrates_history_and_system_instructions(
    chat_store,
) -> None:
    chat_store.ensure("chat-77")
    store = ItemStore()
    persistence = HistoryPersistence(HistoryRepository.from_item_store(store))

    stored_items = persistence.store_items(
        "chat-77",
        "msg-77",
        [{"type": "reasoning", "content": [{"type": "output_text", "text": "compute"}]}],
        model_id="gpt-4o",
    )
    marker_blob = persistence.render_hidden_markers(stored_items, model_id="gpt-4o")

    owui_request = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "be thorough"},
            {"role": "assistant", "content": f"result {marker_blob}"},
        ],
    }

    body = await build_responses_body(
        owui_request,
        valves=type("V", (), {})(),
        metadata={"chat_id": "chat-77", "model": {"id": "gpt-4o"}},
        item_store=store,
    )

    assert body.instructions == "be thorough"
    assert any(item.get("type") == "reasoning" for item in body.input)
