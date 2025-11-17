"""Session-aware logging helpers in a single, readable module."""

from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, DefaultDict, Deque, Iterator, Tuple

# ---------------------------------------------------------------------------
# ContextVars: what we attach to every log record
# ---------------------------------------------------------------------------

OWUI_SESSION_ID: ContextVar[str | None] = ContextVar("owui_session_id", default=None)  # OpenWebUI session token
OWUI_CHAT_ID: ContextVar[str | None] = ContextVar("owui_chat_id", default=None)  # Chat/conversation ID
OWUI_MESSAGE_ID: ContextVar[str | None] = ContextVar("owui_message_id", default=None)  # Message ID in chat
OWUI_USER_ID: ContextVar[str | None] = ContextVar("owui_user_id", default=None)  # OpenWebUI user ID
OWUI_LOG_LEVEL: ContextVar[int] = ContextVar("owui_log_level", default=logging.INFO)

# Buffered per-session logs for citations
SESSION_LOGS: DefaultDict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=2000))


# ---------------------------------------------------------------------------
# Filters and handlers
# ---------------------------------------------------------------------------

class ContextFilter(logging.Filter):
    """Inject context fields and enforce the current log level."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.session_id = OWUI_SESSION_ID.get()
        record.chat_id = OWUI_CHAT_ID.get()
        record.message_id = OWUI_MESSAGE_ID.get()
        record.user_id = OWUI_USER_ID.get()
        return record.levelno >= OWUI_LOG_LEVEL.get()


class SessionMemoryHandler(logging.Handler):
    """Buffer log lines per session for later citation emission."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        session_id = getattr(record, "session_id", None)
        if not session_id:
            return
        SESSION_LOGS[session_id].append(self.format(record))


# ---------------------------------------------------------------------------
# Logger configuration
# ---------------------------------------------------------------------------

_configured = False
_context_filter = ContextFilter()
_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] %(name)s %(message)s "
    "session_id=%(session_id)s chat_id=%(chat_id)s message_id=%(message_id)s user_id=%(user_id)s"
)


def configure_logging() -> None:
    """Attach console + memory handlers once under the canonical namespace."""

    global _configured
    if _configured:
        return

    logger = logging.getLogger("openai_responses_manifold")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)
    console.addFilter(_context_filter)

    memory = SessionMemoryHandler()
    memory.setLevel(logging.DEBUG)
    memory.setFormatter(formatter)
    memory.addFilter(_context_filter)

    logger.addHandler(console)
    logger.addHandler(memory)
    logger.addFilter(_context_filter)

    _configured = True


def get_logger(name: str = __name__) -> logging.Logger:
    """Return a logger under the manifold namespace."""

    configure_logging()
    base = "openai_responses_manifold"
    qualified = name if name.startswith(base) else f"{base}.{name}"
    return logging.getLogger(qualified)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

LoggingTokens = Tuple[Token[str | None], Token[str | None], Token[str | None], Token[str | None], Token[int]]


def push_logging_context(
    session_id: str | None,
    level: int,
    *,
    chat_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
) -> LoggingTokens:
    """Apply session/log-level context; returns tokens to restore later."""

    configure_logging()
    return (
        OWUI_SESSION_ID.set(session_id),
        OWUI_CHAT_ID.set(chat_id),
        OWUI_MESSAGE_ID.set(message_id),
        OWUI_USER_ID.set(user_id),
        OWUI_LOG_LEVEL.set(level),
    )


def pop_logging_context(tokens: LoggingTokens) -> None:
    """Restore ContextVars from tokens returned by ``push_logging_context``."""

    t_session, t_chat, t_message, t_user, t_level = tokens
    OWUI_SESSION_ID.reset(t_session)
    OWUI_CHAT_ID.reset(t_chat)
    OWUI_MESSAGE_ID.reset(t_message)
    OWUI_USER_ID.reset(t_user)
    OWUI_LOG_LEVEL.reset(t_level)


@contextmanager
def logging_context(
    session_id: str | None,
    level: int,
    *,
    chat_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
) -> Iterator[None]:
    tokens = push_logging_context(
        session_id,
        level,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
    )
    try:
        yield
    finally:
        pop_logging_context(tokens)


# ---------------------------------------------------------------------------
# Citation buffer helpers
# ---------------------------------------------------------------------------

def get_session_logs(session_id: str | None) -> list[str]:
    if not session_id:
        return []
    return list(SESSION_LOGS.get(session_id, ()))


def clear_session_logs(session_id: str | None) -> None:
    if not session_id:
        return
    SESSION_LOGS.pop(session_id, None)


def consume_session_logs(session_id: str | None) -> list[str]:
    lines = get_session_logs(session_id)
    clear_session_logs(session_id)
    return lines


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def truncate_for_log(value: Any, limit: int = 2000) -> tuple[str, bool]:
    """Return a safe, possibly truncated string for logging."""

    if value is None:
        return "", False
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


# Configure eagerly so child loggers inherit handlers/filters.
configure_logging()


__all__ = [
    "configure_logging",
    "get_logger",
    "push_logging_context",
    "pop_logging_context",
    "logging_context",
    "OWUI_SESSION_ID",
    "OWUI_CHAT_ID",
    "OWUI_MESSAGE_ID",
    "OWUI_USER_ID",
    "OWUI_LOG_LEVEL",
    "SESSION_LOGS",
    "get_session_logs",
    "clear_session_logs",
    "consume_session_logs",
    "truncate_for_log",
]
