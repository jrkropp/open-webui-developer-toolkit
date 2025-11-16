"""Top-level package for the OpenAI Responses manifold."""

from __future__ import annotations

from . import core as _core
from .core import *  # noqa: F401, F403
from .features import build_tools, route_gpt5_auto
from .infra import OpenAIResponsesClient, fetch_openai_response_items, persist_openai_response_items
from .pipe import EventEmitter, Pipe, ResponseRunner

__all__ = [
    "EventEmitter",
    "Pipe",
    "ResponseRunner",
    "build_tools",
    "route_gpt5_auto",
    "OpenAIResponsesClient",
    "fetch_openai_response_items",
    "persist_openai_response_items",
    *_core.__all__,
]
