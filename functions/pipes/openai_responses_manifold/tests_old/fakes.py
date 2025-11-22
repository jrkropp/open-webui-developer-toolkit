"""Reusable fakes and fixtures for the Responses manifold test suite."""

from __future__ import annotations

import json
from collections import deque
from types import SimpleNamespace
from typing import Any, AsyncIterator

from openai_responses_manifold.adapters.openai.events import UnknownStreamEventType, parse_event
from openai_responses_manifold.adapters.openai.requests import ResponseCreateParams
from openai_responses_manifold.adapters.openwebui.events import EventEmitterFn


class InMemoryChats:
    """Simple stand-in for ``open_webui.models.chats.Chats``."""

    _store: dict[str, SimpleNamespace] = {}

    @classmethod
    def reset(cls) -> None:
        cls._store.clear()

    @classmethod
    def ensure(
        cls, chat_id: str, initial_chat: dict[str, Any] | None = None
    ) -> SimpleNamespace:
        model = cls._store.setdefault(chat_id, SimpleNamespace(chat={"id": chat_id}))
        if initial_chat is not None:
            model.chat = dict(initial_chat)
        return model

    @classmethod
    def get_chat_by_id(cls, chat_id: str) -> SimpleNamespace | None:
        return cls._store.get(chat_id)

    @classmethod
    def update_chat_by_id(cls, chat_id: str, payload: dict[str, Any]) -> None:
        cls.ensure(chat_id, payload)

    @classmethod
    def upsert_message_to_chat_by_id_and_message_id(
        cls, chat_id: str, message_id: str, payload: dict[str, Any]
    ) -> None:
        model = cls.ensure(chat_id)
        messages = model.chat.setdefault("messages", {})
        messages[message_id] = payload


class FakeResponsesClient:
    """Scriptable Responses API client replacement."""

    def __init__(self) -> None:
        self._stream_scripts: deque[list[dict[str, Any]]] = deque()
        self._responses: deque[dict[str, Any]] = deque()
        self.stream_calls: list[tuple[dict[str, Any], str, str]] = []
        self.request_calls: list[tuple[dict[str, Any], str, str]] = []

    def enqueue_stream(self, events: list[dict[str, Any]]) -> None:
        """Schedule a sequence of SSE events for the next stream."""

        self._stream_scripts.append([json.loads(json.dumps(evt)) for evt in events])

    def enqueue_response(self, payload: dict[str, Any]) -> None:
        """Schedule the next non-streaming response payload."""

        self._responses.append(json.loads(json.dumps(payload)))

    async def stream(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
        typed: bool = False,
    ) -> AsyncIterator[Any]:
        validated_body = (
            ResponseCreateParams.model_validate(request_body)
            if isinstance(request_body, dict)
            else ResponseCreateParams.model_validate(request_body.model_dump())
        )
        self.stream_calls.append((validated_body.model_dump(exclude_none=True), api_key, base_url))
        if not self._stream_scripts:
            raise AssertionError("No queued stream events for FakeResponsesClient")
        script = self._stream_scripts.popleft()
        for event in script:
            clone = json.loads(json.dumps(event))
            if typed:
                yield parse_event(clone)
                continue
            yield clone

    async def stream_events(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> AsyncIterator[dict[str, Any]]:
        return self.stream(request_body, api_key=api_key, base_url=base_url)

    async def create(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> dict[str, Any]:
        return await self.request(request_body, api_key=api_key, base_url=base_url)

    async def request(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> dict[str, Any]:
        validated_body = (
            ResponseCreateParams.model_validate(request_body)
            if isinstance(request_body, dict)
            else ResponseCreateParams.model_validate(request_body.model_dump())
        )
        self.request_calls.append((validated_body.model_dump(exclude_none=True), api_key, base_url))
        if not self._responses:
            raise AssertionError("No queued responses for FakeResponsesClient")
        return json.loads(json.dumps(self._responses.popleft()))


class SpyEventEmitter:
    """Captures emitted Open WebUI events for assertions."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [event.get("type", "") for event in self.events]


EventEmitter = EventEmitterFn
