"""Session-scoped logging helpers with a single namespace and context injection."""

from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, DefaultDict, Deque, Iterator, Tuple

# ---------------------------------------------------------------------------
# Context and buffering
# ---------------------------------------------------------------------------

current_session_id: ContextVar[str | None] = ContextVar(
    "openai_responses_session_id", default=None
)
current_chat_id: ContextVar[str | None] = ContextVar(
    "openai_responses_chat_id", default=None
)
current_message_id: ContextVar[str | None] = ContextVar(
    "openai_responses_message_id", default=None
)
current_user_id: ContextVar[str | None] = ContextVar(
    "openai_responses_user_id", default=None
)
current_log_level: ContextVar[int] = ContextVar(
    "openai_responses_log_level", default=logging.INFO
)

SESSION_LOGS: DefaultDict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=2000))


class _ContextFilter(logging.Filter):
    """Attach session/chat/message/user context and enforce the current log level."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.session_id = current_session_id.get()
        record.chat_id = current_chat_id.get()
        record.message_id = current_message_id.get()
        record.user_id = current_user_id.get()
        return record.levelno >= current_log_level.get()


class _MemoryHandler(logging.Handler):
    """Buffer log lines per session for later citation emission."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        session = getattr(record, "session_id", None)
        if not session:
            return
        SESSION_LOGS[session].append(self.format(record))


_configured = False
_context_filter = _ContextFilter()
_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] %(message)s "
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

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_context_filter)

    memory_handler = _MemoryHandler()
    memory_handler.setLevel(logging.DEBUG)
    memory_handler.setFormatter(formatter)
    memory_handler.addFilter(_context_filter)

    logger.addHandler(console_handler)
    logger.addHandler(memory_handler)
    logger.addFilter(_context_filter)

    _configured = True


def set_session(
    session_id: str | None,
    level: int,
    *,
    chat_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
) -> Tuple[Token[str | None], Token[str | None], Token[str | None], Token[str | None], Token[int]]:
    """Set session/log-level ContextVars and return reset tokens."""

    configure_logging()
    token_session = current_session_id.set(session_id)
    token_chat = current_chat_id.set(chat_id)
    token_message = current_message_id.set(message_id)
    token_user = current_user_id.set(user_id)
    token_level = current_log_level.set(level)
    return token_session, token_chat, token_message, token_user, token_level


def reset_session(
    tokens: Tuple[Token[str | None], Token[str | None], Token[str | None], Token[str | None], Token[int]]
) -> None:
    """Reset ContextVars using tokens from ``set_session``."""

    token_session, token_chat, token_message, token_user, token_level = tokens
    current_session_id.reset(token_session)
    current_chat_id.reset(token_chat)
    current_message_id.reset(token_message)
    current_user_id.reset(token_user)
    current_log_level.reset(token_level)


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


@contextmanager
def session_logging(
    session_id: str | None,
    level: int,
    *,
    chat_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
) -> Iterator[None]:
    tokens = set_session(
        session_id,
        level,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
    )
    try:
        yield
    finally:
        reset_session(tokens)


class SessionLogger:
    """Thin facade around the session-aware logging helpers."""

    session_id = current_session_id
    chat_id = current_chat_id
    message_id = current_message_id
    user_id = current_user_id
    log_level = current_log_level
    logs = SESSION_LOGS

    get_session_logs = staticmethod(get_session_logs)
    clear_session_logs = staticmethod(clear_session_logs)
    consume_session_logs = staticmethod(consume_session_logs)
    set_session = staticmethod(set_session)
    reset_session = staticmethod(reset_session)
    session_logging = staticmethod(session_logging)

    @classmethod
    def get_logger(cls, name: str = __name__) -> logging.Logger:
        configure_logging()
        base = "openai_responses_manifold"
        qualified = name if name.startswith(base) else f"{base}.{name}"
        return logging.getLogger(qualified)


def truncate_for_log(value: Any, limit: int = 2000) -> tuple[str, bool]:
    """Return a safe, possibly truncated string for logging."""

    if value is None:
        return "", False
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


# Configure immediately so children inherit handlers/filters.
configure_logging()


__all__ = [
    "SessionLogger",
    "clear_session_logs",
    "configure_logging",
    "consume_session_logs",
    "current_log_level",
    "current_chat_id",
    "current_message_id",
    "current_session_id",
    "current_user_id",
    "get_session_logs",
    "reset_session",
    "session_logging",
    "set_session",
    "truncate_for_log",
]
