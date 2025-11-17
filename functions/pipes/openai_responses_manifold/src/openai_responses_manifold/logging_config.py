"""Centralized logging configuration for the Responses manifold.

This module configures a package-scoped logger hierarchy that:
- Attaches console + in-memory handlers once per process.
- Uses ContextVars to scope session identifiers and effective log levels.
- Exposes helpers to manage session context and access buffered logs.
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import DefaultDict, Deque, Iterator, Tuple

# Context-aware state
current_session_id: ContextVar[str | None] = ContextVar(
    "openai_responses_session_id", default=None
)
current_log_level: ContextVar[int] = ContextVar(
    "openai_responses_log_level", default=logging.INFO
)


# Per-session buffered logs
SESSION_LOGS: DefaultDict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=2000))


class _SessionFilter(logging.Filter):
    """Attach session context and enforce the current log level."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.session_id = current_session_id.get()
        return record.levelno >= current_log_level.get()


class _SessionConsoleHandler(logging.StreamHandler):
    """Dedicated console handler marker for session-aware filtering."""


class _SessionMemoryHandler(logging.Handler):
    """Buffer log lines per session for later citation emission."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - tiny wrapper
        session = getattr(record, "session_id", None)
        if not session:
            return
        SESSION_LOGS[session].append(self.format(record))


_configured = False
_session_filter = _SessionFilter()


def configure_logging() -> None:
    """Attach handlers/filters to the package logger once."""

    global _configured
    if _configured:
        return

    logger = logging.getLogger("openai_responses_manifold")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not any(isinstance(flt, _SessionFilter) for flt in logger.filters):
        logger.addFilter(_session_filter)

    console_handler = next(
        (h for h in logger.handlers if isinstance(h, _SessionConsoleHandler)), None
    )
    if console_handler is None:
        console_handler = _SessionConsoleHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s")
        )
        logger.addHandler(console_handler)
    if not any(isinstance(flt, _SessionFilter) for flt in console_handler.filters):
        console_handler.addFilter(_session_filter)

    memory_handler = next(
        (h for h in logger.handlers if isinstance(h, _SessionMemoryHandler)), None
    )
    if memory_handler is None:
        memory_handler = _SessionMemoryHandler()
        memory_handler.setLevel(logging.DEBUG)
        memory_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(memory_handler)
    if not any(isinstance(flt, _SessionFilter) for flt in memory_handler.filters):
        memory_handler.addFilter(_session_filter)

    _configured = True


def set_session(session_id: str | None, level: int) -> Tuple[Token[str | None], Token[int]]:
    """Set session/log-level ContextVars and return reset tokens."""

    configure_logging()
    token_id = current_session_id.set(session_id)
    token_level = current_log_level.set(level)
    return token_id, token_level


def reset_session(tokens: Tuple[Token[str | None], Token[int]]) -> None:
    """Reset ContextVars using tokens from ``set_session``."""

    token_id, token_level = tokens
    current_session_id.reset(token_id)
    current_log_level.reset(token_level)


def get_session_logs(session_id: str | None) -> list[str]:
    """Return buffered log lines for the given session id."""

    if not session_id:
        return []
    return list(SESSION_LOGS.get(session_id, ()))


def clear_session_logs(session_id: str | None) -> None:
    """Clear buffered logs for the given session id, if any."""

    if not session_id:
        return
    SESSION_LOGS.pop(session_id, None)


def consume_session_logs(session_id: str | None) -> list[str]:
    """Return and clear buffered logs for ``session_id``."""

    lines = get_session_logs(session_id)
    clear_session_logs(session_id)
    return lines


@contextmanager
def session_logging(session_id: str | None, level: int) -> Iterator[None]:
    """Context manager to scope logging to a session."""

    tokens = set_session(session_id, level)
    try:
        yield
    finally:
        reset_session(tokens)


# Configure at import so child loggers propagate to the package logger.
configure_logging()


__all__ = [
    "SESSION_LOGS",
    "clear_session_logs",
    "configure_logging",
    "consume_session_logs",
    "current_log_level",
    "current_session_id",
    "get_session_logs",
    "reset_session",
    "session_logging",
    "set_session",
]
