"""Request-scoped logger used throughout the manifold."""

from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import ClassVar


class SessionLogger:
    """Per-request logger storing log lines in memory and stdout."""

    session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
    log_level: ContextVar[int] = ContextVar("log_level", default=logging.INFO)
    logs: ClassVar[defaultdict[str | None, deque[str]]] = defaultdict(lambda: deque(maxlen=2000))

    @classmethod
    def get_logger(cls, name: str = __name__) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        def _filter(record: logging.LogRecord) -> bool:
            record.session_id = cls.session_id.get()
            return record.levelno >= cls.log_level.get()

        logger.addFilter(_filter)

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s"))
        logger.addHandler(console)

        class _MemoryHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                session = getattr(record, "session_id", None)
                if session:
                    SessionLogger.logs[session].append(self.format(record))

        mem_handler = _MemoryHandler()
        mem_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(mem_handler)

        return logger
