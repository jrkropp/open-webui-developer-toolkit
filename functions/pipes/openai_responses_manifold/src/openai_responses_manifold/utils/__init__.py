"""Utility helpers shared across the manifold."""

from .openwebui_events import (
    EventCall,
    EventCallerFn,
    EventEmitter,
    EventEmitterFn,
)
from .logging import (
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
    "push_logging_context",
    "pop_logging_context",
    "logging_context",
    "get_logger",
    "clear_session_logs",
    "consume_session_logs",
    "get_session_logs",
    "configure_logging",
    "OWUI_SESSION_ID",
    "OWUI_CHAT_ID",
    "OWUI_MESSAGE_ID",
    "OWUI_USER_ID",
    "OWUI_LOG_LEVEL",
    "truncate_for_log",
    "EventCallerFn",
    "EventCall",
    "EventEmitterFn",
    "EventEmitter",
]
