"""Minimal Open WebUI event helpers matching the documented event catalog."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict

EventEmitterFn = Callable[[dict[str, Any]], Awaitable[Any] | Any]
EventCallerFn = Callable[[dict[str, Any]], Awaitable[Any] | Any]


# -------------------------
# Event payload definitions
# -------------------------


class StatusEventData(BaseModel):
    """Status/progress updates shown in the chat UI."""

    model_config = ConfigDict(extra="allow")

    description: str
    done: bool = False
    hidden: bool = False


class NotificationEventData(BaseModel):
    """Toast notification payload consumed by the UI."""

    type: Literal["info", "success", "error", "warning"]
    content: str


class FileModelResponse(BaseModel):
    """Open WebUI file object (mirrors backend FileModelResponse used by the UI)."""

    model_config = ConfigDict(extra="allow")

    id: str
    user_id: str
    hash: str | None = None

    filename: str
    data: dict[str, Any] | None = None
    meta: dict[str, Any]

    created_at: int
    updated_at: int


class MessageDeltaEventData(BaseModel):
    """Streaming/append content for an in-progress message."""

    model_config = ConfigDict(extra="allow")

    content: str


class ChatMessageEventData(BaseModel):
    """Complete replacement content for a message."""

    model_config = ConfigDict(extra="allow")

    content: str


class FilesEventData(BaseModel):
    """Files attached to a message; UI expects a list of FileModelResponse objects."""

    files: list[FileModelResponse]


class ChatTitleEventData(BaseModel):
    """Conversation title update."""

    title: str


class ChatTagsEventData(BaseModel):
    """Conversation tags update."""

    tags: list[str]


class SourceEventData(BaseModel):
    """Source/citation payload; UI appends to message sources."""

    model_config = ConfigDict(extra="allow")


class ChatCompletionEventData(BaseModel):
    """
    Payload for ``chat:completion`` events (custom/implementation-defined).

    Frontend reads ``done`` and optionally ``content``/``title`` when ``done`` is true
    to trigger toasts/notifications; other fields are passed through.
    """

    model_config = ConfigDict(extra="allow")

    done: bool | None = None
    content: str | None = None
    title: str | None = None
    usage: dict[str, Any] | None = None


class ConfirmationEventData(BaseModel):
    """Confirmation dialog payload returned via __event_call__."""

    title: str
    message: str


class InputEventData(BaseModel):
    """Input dialog payload returned via __event_call__."""

    title: str
    message: str
    placeholder: str | None = None
    value: str | None = None


class ExecuteEventData(BaseModel):
    """Client-side code execution payload returned via __event_call__."""

    code: str


class ExecutePythonEventData(BaseModel):
    """
    Non-documented type used via ``__event_call__``: ``execute:python``.

    Backend (`utils/middleware.py`) invokes __event_call__ with ``id``, ``code``, and
    optional ``session_id``; the frontend runs the code client-side.
    """

    id: str
    code: str
    session_id: str


class ExecuteToolEventData(BaseModel):
    """
    Non-documented type used via ``__event_call__``: ``execute:tool``.

    Backend (`utils/middleware.py`) invokes __event_call__ with these fields to run a tool in the frontend.
    """

    id: str
    name: str
    params: dict[str, Any] = {}
    server: dict[str, Any] = {}
    session_id: str
    model_config = ConfigDict(extra="allow")


class RequestChatCompletionEventData(BaseModel):
    """
    Non-documented type used via ``__event_call__``: ``request:chat:completion``.

    Backend (`utils/chat.py`) calls __event_call__ with this so the frontend performs a chat completion
    (direct connection flow). The frontend issues the completion request and streams over the provided channel.
    """

    session_id: str
    channel: str
    form_data: dict[str, Any]
    model: dict[str, Any]


def _to_dict(obj: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return obj


async def _maybe_await(value: Any) -> Any:
    if asyncio.isfuture(value) or inspect.isawaitable(value):
        return await value
    return value


# ---------------
# Event emitting
# ---------------


class EventEmitter:
    """Thin wrapper around ``__event_emitter__`` for documented chat events."""

    def __init__(self, event_emitter: EventEmitterFn | None) -> None:
        self.event_emitter = event_emitter

    async def _emit(self, event_type: str, data: BaseModel | dict[str, Any]) -> dict[str, Any]:
        payload = {"type": event_type, "data": _to_dict(data)}
        if self.event_emitter:
            await _maybe_await(self.event_emitter(payload))
        return payload

    # docs: type = "status"
    async def status(self, description: str, *, done: bool = False, hidden: bool = False) -> dict[str, Any]:
        return await self._emit("status", StatusEventData(description=description, done=done, hidden=hidden))

    # docs: type = "chat:message:delta"
    async def delta(self, content: str) -> dict[str, Any]:
        return await self._emit("chat:message:delta", MessageDeltaEventData(content=content))

    # docs: type = "message"
    async def message(self, content: str) -> dict[str, Any]:
        return await self._emit("message", MessageDeltaEventData(content=content))

    # docs: type = "chat:message"
    async def replace(self, content: str) -> dict[str, Any]:
        return await self._emit("chat:message", ChatMessageEventData(content=content))

    # docs: type = "files" (alias: "chat:message:files")
    async def files(self, files: list[FileModelResponse] | list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [f if isinstance(f, FileModelResponse) else FileModelResponse(**f) for f in files]
        return await self._emit("files", FilesEventData(files=normalized))

    # docs: type = "chat:title"
    async def title(self, title: str | ChatTitleEventData) -> dict[str, Any]:
        payload = title.model_dump() if isinstance(title, ChatTitleEventData) else {"title": title}
        return await self._emit("chat:title", payload)

    # docs: type = "chat:tags"
    async def tags(self, tags: list[str] | ChatTagsEventData) -> dict[str, Any]:
        payload = tags.model_dump() if isinstance(tags, ChatTagsEventData) else {"tags": tags}
        return await self._emit("chat:tags", payload)

    # docs: type = "source"
    async def source(self, data: SourceEventData | dict[str, Any]) -> dict[str, Any]:
        payload = data if isinstance(data, SourceEventData) else SourceEventData(**data)
        return await self._emit("source", payload)

    # docs: type = "citation"
    async def citation(self, data: SourceEventData | dict[str, Any]) -> dict[str, Any]:
        payload = data if isinstance(data, SourceEventData) else SourceEventData(**data)
        return await self._emit("citation", payload)

    # docs: type = "notification"
    async def notification(
        self,
        content: str,
        *,
        level: Literal["info", "success", "error", "warning"] = "info",
    ) -> dict[str, Any]:
        return await self._emit("notification", NotificationEventData(type=level, content=content))

    # docs: type = "chat:completion"
    async def chat_completion(self, data: ChatCompletionEventData) -> dict[str, Any]:
        return await self._emit("chat:completion", data)


# -----------------
# Interactive calls
# -----------------


class EventCall:
    """Wrapper around ``__event_call__`` for documented and non-documented interactive events."""

    def __init__(self, event_call: EventCallerFn | None = None) -> None:
        self._call = event_call

    async def _send(self, event_type: str, data: BaseModel | dict[str, Any]) -> Any:
        if not self._call:
            raise RuntimeError("__event_call__ not provided")
        payload = {"type": event_type, "data": _to_dict(data)}
        result = self._call(payload)
        return await _maybe_await(result)

    # docs: type = "input"
    async def input(
        self,
        title: str,
        message: str,
        *,
        placeholder: str | None = None,
        default: str | None = None,
    ) -> Any:
        data = InputEventData(title=title, message=message, placeholder=placeholder, value=default)
        result = await self._send("input", data)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return result

    # docs: type = "confirmation"
    async def confirmation(self, title: str, message: str) -> Any:
        data = ConfirmationEventData(title=title, message=message)
        result = await self._send("confirmation", data)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return result

    # docs: type = "execute"
    async def execute(self, code: str) -> Any:
        data = ExecuteEventData(code=code)
        return await self._send("execute", data)

    # Undocumented: type = "execute:python"
    async def execute_python(self, data: ExecutePythonEventData | dict[str, Any]) -> Any:
        payload = data if isinstance(data, ExecutePythonEventData) else ExecutePythonEventData(**data)
        return await self._send("execute:python", payload)

    # Undocumented: type = "execute:tool"
    async def execute_tool(
        self,
        data: ExecuteToolEventData | dict[str, Any],
    ) -> Any:
        payload = data if isinstance(data, ExecuteToolEventData) else ExecuteToolEventData(**data)
        return await self._send("execute:tool", payload)

    # Undocumented: type = "request:chat:completion"
    async def request_chat_completion(
        self,
        data: RequestChatCompletionEventData | dict[str, Any],
    ) -> Any:
        payload = data if isinstance(data, RequestChatCompletionEventData) else RequestChatCompletionEventData(**data)
        return await self._send("request:chat:completion", payload)


__all__ = [
    "EventEmitterFn",
    "EventCallerFn",
    "EventEmitter",
    "EventCall",
    "StatusEventData",
    "NotificationEventData",
    "FileModelResponse",
    "MessageDeltaEventData",
    "ChatMessageEventData",
    "FilesEventData",
    "ChatTitleEventData",
    "ChatTagsEventData",
    "SourceEventData",
    "ChatCompletionEventData",
    "ConfirmationEventData",
    "InputEventData",
    "ExecuteEventData",
    # Non-documented frontend-handled types (used via __event_call__)
    "ExecutePythonEventData",
    "ExecuteToolEventData",
    "RequestChatCompletionEventData",
]
