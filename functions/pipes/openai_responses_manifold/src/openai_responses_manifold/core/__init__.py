"""Core primitives used across the OpenAI Responses manifold."""

from .api_models import CompletionsBody, ResponsesBody
from .capabilities import MODEL_ALIASES, MODEL_FEATURES, alias_defaults, features, supports
from .errors import (
    ManifoldError,
    OpenAIStreamError,
    PersistenceError,
    RoutingError,
    ToolExecutionError,
)
from .ids import base_model, normalize
from .markers import (
    ULID_LENGTH,
    contains_marker,
    create_marker,
    extract_markers,
    generate_item_id,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from .events import (
    BaseStreamEvent,
    ErrorEvent,
    EventType,
    StreamEvent,
    UnknownStreamEventType,
    parse_event,
)

__all__ = [
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "ULID_LENGTH",
    "alias_defaults",
    "base_model",
    "CompletionsBody",
    "ManifoldError",
    "OpenAIStreamError",
    "PersistenceError",
    "RoutingError",
    "ToolExecutionError",
    "features",
    "normalize",
    "ResponsesBody",
    "contains_marker",
    "create_marker",
    "extract_markers",
    "generate_item_id",
    "parse_marker",
    "supports",
    "split_text_by_markers",
    "wrap_marker",
    "BaseStreamEvent",
    "ErrorEvent",
    "EventType",
    "StreamEvent",
    "UnknownStreamEventType",
    "parse_event",
]
