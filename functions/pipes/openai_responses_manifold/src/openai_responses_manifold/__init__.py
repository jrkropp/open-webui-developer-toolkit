"""Top-level package for the OpenAI Responses manifold."""

from __future__ import annotations

from . import core as _core
from .core import *  # noqa: F401, F403
from .engine import EventEmitter, ResponsesEngine
from .infra import ItemStore, OpenAIResponsesClient
from .main import Pipe
from .services import build_tools, execute_tool_calls, route_auto_model
from .utils import (
    OWUI_CHAT_ID,
    OWUI_LOG_LEVEL,
    OWUI_MESSAGE_ID,
    OWUI_SESSION_ID,
    OWUI_USER_ID,
    clear_session_logs,
    configure_logging,
    consume_session_logs,
    get_logger,
    get_session_logs,
    logging_context,
    pop_logging_context,
    push_logging_context,
    truncate_for_log,
)

__all__ = [
    "EventEmitter",
    "Pipe",
    "ResponsesEngine",
    "ItemStore",
    "build_tools",
    "execute_tool_calls",
    "route_auto_model",
    "OpenAIResponsesClient",
    "get_logger",
    "push_logging_context",
    "pop_logging_context",
    "logging_context",
    "configure_logging",
    "clear_session_logs",
    "consume_session_logs",
    "get_session_logs",
    "truncate_for_log",
    "OWUI_SESSION_ID",
    "OWUI_CHAT_ID",
    "OWUI_MESSAGE_ID",
    "OWUI_USER_ID",
    "OWUI_LOG_LEVEL",
    *_core.__all__,
]
