"""Session-scoped logger facade backed by ``logging_config``."""

from __future__ import annotations

import logging

from ..logging_config import (
    SESSION_LOGS,
    clear_session_logs,
    configure_logging,
    consume_session_logs,
    current_log_level,
    current_session_id,
    get_session_logs,
    reset_session,
    session_logging,
    set_session,
)


class SessionLogger:
    """Compatibility shim exposing session-aware logging helpers."""

    session_id = current_session_id
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
        return logging.getLogger(name)


__all__ = [
    "SessionLogger",
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
