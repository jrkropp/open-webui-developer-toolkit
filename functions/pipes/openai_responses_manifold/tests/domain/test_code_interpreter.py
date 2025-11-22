import asyncio
import logging

import pytest

from openai_responses_manifold.domain.code_interpreter import (
    emit_pending_code_interpreter_result,
    handle_code_interpreter_event,
    handle_code_interpreter_item,
)
from openai_responses_manifold.domain.types import TurnState


class _Events:
    def __init__(self):
        self.citations: list[dict] = []

    async def citation(self, data: dict):
        self.citations.append(data)


@pytest.mark.asyncio
async def test_event_flow_tracks_code_and_statuses():
    state = TurnState()
    statuses: list[tuple[str, dict]] = []

    async def emit_status(message: str, **extra):
        statuses.append((message, extra))

    logger = logging.getLogger("test.code_interpreter")

    await handle_code_interpreter_event(
        {"type": "response.code_interpreter_call.in_progress", "output_index": 3},
        state,
        emit_status,
        logger,
    )
    await handle_code_interpreter_event(
        {"type": "response.code_interpreter_call.code.done", "output_index": 3, "code": "print('hi')"},
        state,
        emit_status,
        logger,
    )
    await handle_code_interpreter_event(
        {"type": "response.code_interpreter_call.completed", "output_index": 3},
        state,
        emit_status,
        logger,
    )

    assert state.last_code_output_index == 3
    assert state.code_snippets[3] == "print('hi')"

    assert statuses == [
        ("Starting code interpreter…", {}),
        (
            "Executed Python:\n```python\nprint('hi')\n```",
            {"hidden": True, "require_previous": True},
        ),
        ("Code interpreter run finished.", {"require_previous": True}),
    ]


@pytest.mark.asyncio
async def test_item_builds_citation_and_clears_pending_when_result_present():
    state = TurnState(assistant_visible_text="done")
    events = _Events()
    statuses: list[tuple[str, dict]] = []

    async def emit_status(message: str, **extra):  # pragma: no cover - no calls here
        statuses.append((message, extra))

    logger = logging.getLogger("test.code_interpreter")

    item = {
        "code_interpreter_call": {
            "code": "print('hi')",
            "outputs": [
                {"type": "logs", "logs": "log1"},
                {"type": "file", "file_id": "file-1", "filename": "out.txt"},
                {"type": "text", "text": "hello"},
            ],
        }
    }

    await handle_code_interpreter_item(
        item,
        state,
        events,
        logger,
        emit_status,
        output_index=5,
    )

    assert not state.pending_ci_results
    assert len(events.citations) == 1
    citation = events.citations[0]
    assert "Logs:\nlog1" in citation["document"][0]
    assert "Outputs:\n- file: file_id=file-1 (out.txt)" in citation["document"][0]
    assert "Result:\ndone" in citation["document"][0]
    assert citation["metadata"][0]["output_index"] == 5


@pytest.mark.asyncio
async def test_pending_result_emits_follow_up_citation():
    state = TurnState()
    events = _Events()
    logger = logging.getLogger("test.code_interpreter")

    async def emit_status(message: str, **extra):  # pragma: no cover - unused
        return None

    # No assistant result text yet, so this should register a pending run.
    await handle_code_interpreter_item(
        {"code": "x=1+1", "outputs": []},
        state,
        events,
        logger,
        emit_status,
        output_index=1,
    )

    assert state.pending_ci_results == {1}
    assert len(events.citations) == 1
    first_meta = events.citations[0]["metadata"][0]
    assert first_meta["pending_result_text"] is True

    # Emit the assistant message and ensure a follow-up citation is generated.
    await emit_pending_code_interpreter_result(
        state,
        events,
        logger,
        assistant_text="the result is 2",
    )

    assert not state.pending_ci_results
    assert len(events.citations) == 2
    follow_up = events.citations[1]
    assert "Result:\nthe result is 2" in follow_up["document"][0]
    assert follow_up["metadata"][0]["kind"] == "result"
    assert follow_up["metadata"][0]["output_index"] == 1
