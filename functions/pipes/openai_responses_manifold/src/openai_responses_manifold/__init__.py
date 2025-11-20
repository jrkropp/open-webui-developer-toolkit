"""Top-level package for the OpenAI Responses manifold."""

from __future__ import annotations

from openai_responses_manifold.config.settings import PipeValves, UserValves
from openai_responses_manifold.core.errors import (
    ManifoldError,
    OpenAIStreamError,
    PersistenceError,
    RoutingError,
    ToolExecutionError,
)
from openai_responses_manifold.core.logging import (
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
from openai_responses_manifold.core.markers import (
    ULID_LENGTH,
    contains_marker,
    create_marker,
    extract_markers,
    generate_item_id,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from openai_responses_manifold.core.model_catalog import (
    EMPTY_FEATURES,
    MODEL_ALIASES,
    MODEL_FEATURES,
    alias_defaults,
    base_model,
    features,
    normalize,
    supports,
)
from openai_responses_manifold.adapters.openai.client import OpenAIResponsesClient
from openai_responses_manifold.adapters.openai.events import (
    BaseStreamEvent,
    ErrorEvent,
    EventType,
    StreamEvent,
    UnknownStreamEventType,
    parse_event,
)
from openai_responses_manifold.adapters.openai.requests import (
    CompletionCreateParams,
    ResponseCreateParams,
)
from openai_responses_manifold.adapters.openwebui import (
    EventCall,
    EventCallerFn,
    EventEmitter,
    EventEmitterFn,
    ItemStore,
    OpenWebUIRuntimeEvents,
)
from openai_responses_manifold.adapters.openwebui.pipe import Pipe
from openai_responses_manifold.domain.engine import ResponsesEngine, TurnResult
from openai_responses_manifold.domain.events import NullRuntimeEvents, RuntimeEvents
from openai_responses_manifold.domain.routing import route_auto_model
from openai_responses_manifold.domain.tools import (
    build_tools,
    execute_tool_calls,
    resolve_tools,
)

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
    "PipeValves",
    "UserValves",
    "ResponsesEngine",
    "TurnResult",
    "RuntimeEvents",
    "NullRuntimeEvents",
    "EventEmitter",
    "EventEmitterFn",
    "EventCall",
    "EventCallerFn",
    "ItemStore",
    "OpenWebUIRuntimeEvents",
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
