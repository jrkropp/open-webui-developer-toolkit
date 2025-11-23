from dataclasses import dataclass
from typing import Any, AsyncIterator

import logging
import pytest

from openai_responses_manifold.core.config import RuntimeConfig
from openai_responses_manifold.core.logging import get_logger, logging_context
from openai_responses_manifold.domain.engine import ResponsesEngine
from openai_responses_manifold.domain.history import HistoryManager, HistoryStore
from openai_responses_manifold.domain.types import (
    RuntimeEvents,
    ToolCall,
    ToolResult,
    TurnContext,
    TurnState,
)
from openai_responses_manifold.openai_api import (
    ResponseCompletedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponsesRequest,
    OpenAIClient,
)


class _FakeHistoryStore(HistoryStore):
    def __init__(self) -> None:
        self.saved: list[tuple[dict, str, list[dict], str]] = []

    def save_items(self, chat_key: dict, message_id: str, items: list[dict], model_id: str) -> list[str]:
        self.saved.append((chat_key, message_id, items, model_id))
        return [f"{i:016d}" for i in range(1, len(items) + 1)]

    def load_items(self, chat_key: dict, item_ids: list[str], model_id: str | None = None) -> dict[str, dict]:
        return {}


class _FakeEvents(RuntimeEvents):
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.statuses: list[str] = []
        self.chat_completions: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []

    async def status(self, description: str, *, done: bool = False, **extra: Any) -> None:  # type: ignore[override]
        self.statuses.append(description)

    async def delta(self, content: str) -> None:  # type: ignore[override]
        self.deltas.append(content)

    async def replace(self, content: str) -> None:  # type: ignore[override]
        self.deltas.append(content)

    async def citation(self, data: dict[str, Any]) -> None:  # type: ignore[override]
        self.citations.append(data)

    async def source(self, data: dict[str, Any]) -> None:  # type: ignore[override]
        self.sources.append(data)

    async def chat_completion(self, data: dict[str, Any]) -> None:  # type: ignore[override]
        self.chat_completions.append(data)

    async def notification(self, content: str, *, level: str = "info") -> None:  # type: ignore[override]
        return None


@dataclass
class _StreamedCall:
    request: ResponsesRequest
    base_url: str
    api_key: str


class _FakeClient(OpenAIClient):
    def __init__(self, responses: list[list[Any]], task_response: dict | None = None) -> None:
        # Each call to stream_responses consumes one response list
        self._responses = responses
        self.calls: list[_StreamedCall] = []
        self.task_requests: list[tuple[ResponsesRequest, str, str]] = []
        self.task_response = task_response or {}

    async def stream_responses(self, request: ResponsesRequest, *, base_url: str, api_key: str) -> AsyncIterator[Any]:  # type: ignore[override]
        self.calls.append(_StreamedCall(request, base_url, api_key))
        events = self._responses.pop(0)
        for event in events:
            yield event

    async def create_response(self, request: ResponsesRequest, *, base_url: str, api_key: str) -> dict:  # type: ignore[override]
        self.task_requests.append((request, base_url, api_key))
        return self.task_response


class _FakeToolExecutor:
    def __init__(self, results: list[ToolResult]):
        self.results = results
        self.calls: list[list[ToolCall]] = []

    async def execute(self, calls: list[ToolCall]) -> list[ToolResult]:  # type: ignore[override]
        self.calls.append(calls)
        return self.results


@pytest.fixture()
def runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        BASE_URL="http://base",
        API_KEY="sk-123",
        MODEL_ID="gpt-5.1-chat",
        REASONING_SUMMARY="disabled",
        PERSIST_REASONING_TOKENS="disabled",
        PERSIST_TOOL_RESULTS=True,
        PARALLEL_TOOL_CALLS=True,
        ENABLE_STRICT_TOOL_CALLING=True,
        MAX_TOOL_CALLS=None,
        MAX_FUNCTION_CALL_LOOPS=3,
        ENABLE_WEB_SEARCH_TOOL=False,
        WEB_SEARCH_CONTEXT_SIZE="medium",
        WEB_SEARCH_USER_LOCATION=None,
        REMOTE_MCP_SERVERS_JSON=None,
        TRUNCATION="auto",
        PROMPT_CACHE_KEY="id",
        LOG_LEVEL="INFO",
    )


def _ctx(runtime_config: RuntimeConfig) -> TurnContext:
    return TurnContext(
        runtime_config=runtime_config,
        model_id="gpt-5.1-chat",
        metadata={
            "message_id": "msg-1",
            "owui_model_id": "gpt-5.1-chat",
            "session_id": "session-1",
        },
    )


@pytest.mark.asyncio
async def test_streaming_without_tools(runtime_config: RuntimeConfig) -> None:
    req = ResponsesRequest(model="gpt-5.1-chat", stream=True)
    fake_client = _FakeClient(
        responses=[
            [
                ResponseOutputTextDeltaEvent(delta="hello"),
                ResponseCompletedEvent(response={"output": [], "usage": {"prompt_tokens": 1}}),
            ]
        ]
    )
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(fake_client, HistoryManager(history_store))
    events = _FakeEvents()

    result = await engine.run_streaming_turn(
        request=req,
        ctx=_ctx(runtime_config),
        events=events,
        history_key={"chat_id": "c1"},
        tool_executor=_FakeToolExecutor([]),
    )

    assert result.text.startswith("hello")
    assert events.deltas == ["hello"]
    assert events.chat_completions and events.chat_completions[-1]["done"] is True
    assert history_store.saved == []


def test_merges_usage_from_nested_payload(runtime_config: RuntimeConfig) -> None:
    state = TurnState()
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(_FakeClient(responses=[]), HistoryManager(history_store))

    engine._merge_usage(state, {"response": {"usage": {"input_tokens": 5}}})
    engine._merge_usage(state, {"usage": {"output_tokens": 3}})

    assert state.usage == {"input_tokens": 5, "output_tokens": 3}


@pytest.mark.asyncio
async def test_tool_call_loop(runtime_config: RuntimeConfig) -> None:
    req = ResponsesRequest(model="gpt-5.1-chat", stream=True, input=[])
    fake_client = _FakeClient(
        responses=[
            [
                ResponseOutputItemAddedEvent(item={"type": "function_call", "call_id": "c1", "name": "echo", "arguments": {"text": "hi"}}),
                ResponseCompletedEvent(response={"output": [{"type": "function_call", "call_id": "c1", "name": "echo", "arguments": {"text": "hi"}}]}),
            ],
            [
                ResponseOutputTextDeltaEvent(delta="done"),
                ResponseCompletedEvent(response={"output": [{"type": "output_text", "content": [{"type": "output_text", "text": "done"}]}]}),
            ],
        ]
    )
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(fake_client, HistoryManager(history_store))
    events = _FakeEvents()

    tool_executor = _FakeToolExecutor([ToolResult(call_id="c1", output="tool-output", status="ok")])
    result = await engine.run_streaming_turn(
        request=req,
        ctx=_ctx(runtime_config),
        events=events,
        history_key={"chat_id": "c1"},
        tool_executor=tool_executor,
    )

    assert tool_executor.calls and tool_executor.calls[0][0].name == "echo"
    assert "openai_responses" in result.text  # marker injected
    saved_types = [item["type"] for item in history_store.saved[0][2]]
    assert saved_types == ["function_call", "function_call_output"]
    assert events.deltas and events.deltas[-1] == "done"


@pytest.mark.asyncio
async def test_persists_reasoning_items_when_conversation(runtime_config: RuntimeConfig) -> None:
    cfg = runtime_config.model_copy(update={"PERSIST_REASONING_TOKENS": "conversation"})
    req = ResponsesRequest(model="gpt-5.1-chat", stream=True, input=[])
    fake_client = _FakeClient(
        responses=[
            [
                ResponseOutputItemAddedEvent(
                    item={"type": "reasoning", "reasoning": {"encrypted_content": "abc"}}
                ),
                ResponseCompletedEvent(
                    response={"output": [{"type": "reasoning", "reasoning": {"encrypted_content": "abc"}}]}
                ),
            ]
        ]
    )
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(fake_client, HistoryManager(history_store))
    events = _FakeEvents()

    result = await engine.run_streaming_turn(
        request=req,
        ctx=_ctx(cfg),
        events=events,
        history_key={"chat_id": "c1"},
        tool_executor=_FakeToolExecutor([]),
    )

    assert history_store.saved
    assert history_store.saved[0][2][0]["type"] == "reasoning"
    assert "openai_responses" in result.text


@pytest.mark.asyncio
async def test_emits_log_citation(runtime_config: RuntimeConfig) -> None:
    req = ResponsesRequest(model="gpt-5.1-chat", stream=True)
    fake_client = _FakeClient(
        responses=[[ResponseOutputTextDeltaEvent(delta="hi"), ResponseCompletedEvent(response={"output": []})]]
    )
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(fake_client, HistoryManager(history_store))
    events = _FakeEvents()

    with logging_context("session-1", logging.INFO):
        logger = get_logger("openai_responses_manifold.tests.log_citation")
        logger.info("line one")
        logger.warning("line two")
        await engine.run_streaming_turn(
            request=req,
            ctx=_ctx(runtime_config),
            events=events,
            history_key={"chat_id": "c1"},
            tool_executor=_FakeToolExecutor([]),
        )

    assert events.citations, "expected log citation to be emitted"
    citation = events.citations[-1]
    assert citation.get("source", {}).get("name") == "Logs"
    assert "line one" in citation.get("document", [""])[0]
    assert citation.get("metadata", [{}])[0].get("total_lines") == 2


@pytest.mark.asyncio
async def test_url_citation_handling(runtime_config: RuntimeConfig) -> None:
    req = ResponsesRequest(model="gpt-5.1-chat", stream=True)
    fake_client = _FakeClient(
        responses=[
            [
                ResponseOutputTextAnnotationAddedEvent(
                    annotation={
                        "type": "url_citation",
                        "url": "https://example.com/page?utm_source=openai",
                        "title": "Example Article",
                    }
                ),
                ResponseCompletedEvent(response={"output": []}),
            ]
        ]
    )
    history_store = _FakeHistoryStore()
    engine = ResponsesEngine(fake_client, HistoryManager(history_store))
    events = _FakeEvents()

    result = await engine.run_streaming_turn(
        request=req,
        ctx=_ctx(runtime_config),
        events=events,
        history_key={"chat_id": "c1"},
        tool_executor=_FakeToolExecutor([]),
    )

    assert result.citations and result.citations[0].url == "https://example.com/page"
    assert result.citations[0].metadata.get("ordinal") == 1
    assert events.sources and events.sources[0]["source"]["name"] == "example.com"
    assert events.citations and events.citations[0]["source"]["url"] == "https://example.com/page"


@pytest.mark.asyncio
async def test_run_task_extracts_text_blocks(runtime_config: RuntimeConfig) -> None:
    task_response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Hello"},
                    {"type": "text", "text": " world"},
                ],
            },
            {
                "type": "output_text",
                "content": [
                    {"type": "output_text", "text": "!"},
                ],
            },
        ]
    }
    fake_client = _FakeClient(responses=[], task_response=task_response)
    engine = ResponsesEngine(fake_client, HistoryManager(_FakeHistoryStore()))

    text = await engine.run_task(ResponsesRequest(model="gpt-5.1-chat", stream=False), _ctx(runtime_config))

    assert text == "Hello world!"
    assert fake_client.task_requests
    request, base_url, api_key = fake_client.task_requests[-1]
    assert request.stream is False
    assert request.store is False
    assert base_url == runtime_config.BASE_URL
    assert api_key == runtime_config.API_KEY
