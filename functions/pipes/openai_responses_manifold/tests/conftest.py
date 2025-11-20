"""Ensure tests import the package modules under src/."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"


def _install_open_webui_stubs() -> None:
    """Create lightweight stand-ins for the open_webui modules used during import."""

    def _ensure_module(name: str) -> ModuleType:
        if name in sys.modules:
            return sys.modules[name]  # type: ignore[return-value]
        module = ModuleType(name)
        sys.modules[name] = module
        return module

    open_webui_pkg = _ensure_module("open_webui")
    models_pkg = _ensure_module("open_webui.models")
    chats_mod = _ensure_module("open_webui.models.chats")
    models_mod = _ensure_module("open_webui.models.models")
    utils_pkg = _ensure_module("open_webui.utils")
    misc_mod = _ensure_module("open_webui.utils.misc")

    class _Chats:
        @staticmethod
        def get_chat_by_id(chat_id: str) -> SimpleNamespace | None:  # pragma: no cover - stub
            return None

        @staticmethod
        def update_chat_by_id(
            chat_id: str, payload: dict[str, Any]
        ) -> None:  # pragma: no cover - stub
            return None

        @staticmethod
        def upsert_message_to_chat_by_id_and_message_id(
            chat_id: str, message_id: str, payload: dict[str, Any]
        ) -> None:  # pragma: no cover - stub
            return None

    class _Models:
        @staticmethod
        def get_model_by_id(model_id: str) -> None:  # pragma: no cover - stub
            return None

        @staticmethod
        def update_model_by_id(model_id: str, form: Any) -> None:  # pragma: no cover - stub
            return None

    class _ModelForm:
        def __init__(self, **kwargs: Any) -> None:
            self._kwargs = kwargs

        def model_dump(self) -> dict[str, Any]:  # pragma: no cover - stub
            return dict(self._kwargs)

    def _get_last_user_message(
        messages: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:  # pragma: no cover - stub
        return (messages or [{}])[-1]

    chats_mod.Chats = _Chats
    models_mod.Models = _Models
    models_mod.ModelForm = _ModelForm
    misc_mod.get_last_user_message = _get_last_user_message

    open_webui_pkg.models = models_pkg
    models_pkg.chats = chats_mod
    models_pkg.models = models_mod
    open_webui_pkg.utils = utils_pkg
    utils_pkg.misc = misc_mod

    aiohttp_mod = _ensure_module("aiohttp")

    class _DummyContent:
        async def iter_chunked(self, _: int) -> Any:
            if False:  # pragma: no cover - placeholder generator
                yield b""

    class _DummyResponse:
        def __init__(self) -> None:
            self.content = _DummyContent()

        async def __aenter__(self) -> _DummyResponse:  # pragma: no cover - stub
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - stub
            return None

        def raise_for_status(self) -> None:  # pragma: no cover - stub
            return None

        async def json(self) -> dict[str, Any]:
            return {}

    class _ClientSession:
        def __init__(self, *_, **__) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        def post(self, *_, **__) -> _DummyResponse:
            return _DummyResponse()

    class _TCPConnector:
        def __init__(self, *_, **__) -> None:  # pragma: no cover - stub
            return None

    class _ClientTimeout:
        def __init__(self, *_, **__) -> None:  # pragma: no cover - stub
            return None

    aiohttp_mod.ClientSession = _ClientSession
    aiohttp_mod.TCPConnector = _TCPConnector
    aiohttp_mod.ClientTimeout = _ClientTimeout


def _ensure_src_on_path() -> None:
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def _reload_package_module() -> None:
    """Force imports to resolve to src/openai_responses_manifold/."""

    sys.modules.pop("openai_responses_manifold", None)


_install_open_webui_stubs()
_ensure_src_on_path()
_reload_package_module()

from .fakes import FakeResponsesClient, InMemoryChats, SpyEventEmitter  # noqa: E402
import openai_responses_manifold as orm  # noqa: E402  # pylint: disable=wrong-import-position
import openai_responses_manifold.application.engine as orm_engine  # noqa: E402
import openai_responses_manifold.infrastructure.openwebui_store as orm_store  # noqa: E402
import openai_responses_manifold.interface.openwebui_pipe as orm_main  # noqa: E402


@pytest.fixture()
def session_logger_scope() -> str:
    """Provide a unique logging context per test."""

    session_id = f"test-session-{orm.generate_item_id()}"
    tokens = orm.push_logging_context(session_id, logging.DEBUG)
    try:
        yield session_id
    finally:
        orm.clear_session_logs(session_id)
        orm.pop_logging_context(tokens)


@pytest.fixture()
def chat_store(monkeypatch: pytest.MonkeyPatch) -> InMemoryChats:
    """Use the in-memory Chats store for tests."""

    InMemoryChats.reset()
    for module in (orm_engine, orm_store):
        monkeypatch.setattr(module, "Chats", InMemoryChats)
    return InMemoryChats


@pytest.fixture()
def fake_responses_client() -> FakeResponsesClient:
    """Scriptable Responses client double."""

    return FakeResponsesClient()


@pytest.fixture()
def spy_event_emitter() -> SpyEventEmitter:
    """Capture emitted Open WebUI events."""

    return SpyEventEmitter()


@pytest.fixture()
def valves() -> orm.Pipe.Valves:
    """Default valves configuration for tests."""

    return orm.Pipe.Valves()


@pytest.fixture()
def metadata_factory() -> Callable[[str, str, str], dict[str, Any]]:
    """Factory for metadata dicts."""

    def _build(chat_id: str = "chat-1", message_id: str = "msg-1", model_id: str = "gpt-4o") -> dict[str, Any]:
        return {"chat_id": chat_id, "message_id": message_id, "model": {"id": model_id}}

    return _build


@pytest.fixture()
def responses_body_factory() -> Callable[..., orm.ResponseCreateParams]:
    """Factory for ResponseCreateParams instances."""

    def _make(
        *,
        model: str = "gpt-4o",
        stream: bool = True,
        input_items: list[dict[str, Any]] | None = None,
        store: bool | None = True,
    ) -> orm.ResponseCreateParams:
        if input_items is None:
            input_items = [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}]
        return orm.ResponseCreateParams(model=model, input=input_items, stream=stream, store=store)

    return _make


@pytest.fixture()
def clear_session_logs(session_logger_scope: str) -> None:
    """Ensure log buffer exists/cleared for tests that mutate it."""

    orm.clear_session_logs(session_logger_scope)
