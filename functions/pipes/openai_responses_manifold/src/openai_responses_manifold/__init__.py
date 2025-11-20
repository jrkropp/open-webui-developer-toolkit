"""Top-level package for the OpenAI Responses manifold."""

from __future__ import annotations

from openai_responses_manifold.application.engine import ResponsesEngine
from openai_responses_manifold.application.routing import route_auto_model
from openai_responses_manifold.application.tools import build_tools, execute_tool_calls, resolve_tools
from openai_responses_manifold.config.settings import PipeValves, UserValves
from openai_responses_manifold.domain.errors import (
    ManifoldError,
    OpenAIStreamError,
    PersistenceError,
    RoutingError,
    ToolExecutionError,
)
from openai_responses_manifold.domain.markers import (
    ULID_LENGTH,
    contains_marker,
    create_marker,
    extract_markers,
    generate_item_id,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from openai_responses_manifold.domain.model_catalog import (
    EMPTY_FEATURES,
    MODEL_ALIASES,
    MODEL_FEATURES,
    alias_defaults,
    base_model,
    features,
    normalize,
    supports,
)
from openai_responses_manifold.domain.openai_events import (
    BaseStreamEvent,
    ErrorEvent,
    EventType,
    StreamEvent,
    UnknownStreamEventType,
    parse_event,
)
from openai_responses_manifold.domain.openai_requests import (
    CompletionCreateParams,
    ResponseCreateParams,
)
from openai_responses_manifold.infrastructure.logging import (
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
from openai_responses_manifold.infrastructure.openai_client import OpenAIResponsesClient
from openai_responses_manifold.infrastructure.openwebui_events import EventEmitter, EventEmitterFn
from openai_responses_manifold.infrastructure.openwebui_store import ItemStore
from openai_responses_manifold.interface.openwebui_pipe import Pipe

__all__ = [
    "EMPTY_FEATURES",
    "MODEL_FEATURES",
    "MODEL_ALIASES",
    "alias_defaults",
    "features",
    "supports",
    "normalize",
    "base_model",
    "ULID_LENGTH",
    "contains_marker",
    "create_marker",
    "extract_markers",
    "generate_item_id",
    "parse_marker",
    "split_text_by_markers",
    "wrap_marker",
    "ManifoldError",
    "OpenAIStreamError",
    "PersistenceError",
    "RoutingError",
    "ToolExecutionError",
    "BaseStreamEvent",
    "CompletionCreateParams",
    "ResponseCreateParams",
    "ErrorEvent",
    "EventType",
    "StreamEvent",
    "UnknownStreamEventType",
    "parse_event",
    "Pipe",
    "ResponsesEngine",
    "EventEmitter",
    "EventEmitterFn",
    "ItemStore",
    "build_tools",
    "execute_tool_calls",
    "resolve_tools",
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
]
