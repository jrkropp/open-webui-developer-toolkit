"""Top-level package for the OpenAI Responses manifold."""

from __future__ import annotations

from . import core as _core
from .core import *  # noqa: F401, F403
from .engine import EventEmitter, ResponsesEngine
from .infra import ItemStore, OpenAIResponsesClient
from .main import Pipe
from .services import build_tools, execute_tool_calls, route_auto_model
from .utils import SessionLogger

__all__ = [
    "EventEmitter",
    "Pipe",
    "ResponsesEngine",
    "ItemStore",
    "build_tools",
    "execute_tool_calls",
    "route_auto_model",
    "OpenAIResponsesClient",
    "SessionLogger",
    *_core.__all__,
]
