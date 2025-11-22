"""OpenAI Responses API adapters and types."""

from .client import OpenAIClient
from .types import (
    ResponseEvent,
    ResponsesEvent,
    ResponsesRequest,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    StreamOptions,
    dump_responses_request,
    parse_responses_event,
    validate_responses_request,
)

__all__ = [
    "ResponseEvent",
    "ResponsesEvent",
    "ResponsesRequest",
    "ResponseCompletedEvent",
    "ResponseFailedEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextAnnotationAddedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningSummaryTextDoneEvent",
    "StreamOptions",
    "dump_responses_request",
    "parse_responses_event",
    "validate_responses_request",
    "OpenAIClient",
]
