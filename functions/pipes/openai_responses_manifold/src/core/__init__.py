"""Core primitives used across the OpenAI Responses manifold."""

from .capabilities import (
    MODEL_ALIASES,
    MODEL_FEATURES,
    alias_defaults,
    base_model,
    features,
    normalize,
    supports,
)
from .markers import (
    ULID_LENGTH,
    create_marker,
    extract_markers,
    generate_item_id,
    parse_marker,
    split_text_by_markers,
    wrap_marker,
)
from .models import CompletionsBody, ResponsesBody
from .session_logger import SessionLogger
from .utils import merge_usage_stats, wrap_code_block, wrap_event_emitter

__all__ = [
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "ULID_LENGTH",
    "alias_defaults",
    "base_model",
    "CompletionsBody",
    "features",
    "normalize",
    "ResponsesBody",
    "SessionLogger",
    "create_marker",
    "extract_markers",
    "generate_item_id",
    "merge_usage_stats",
    "parse_marker",
    "supports",
    "split_text_by_markers",
    "wrap_code_block",
    "wrap_event_emitter",
    "wrap_marker",
]
