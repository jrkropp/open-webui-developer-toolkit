"""Typed models for the OpenAI Responses API.

See ``docs/responses_engine.md`` and ``docs/routing_and_model_catalog.md``
for the behavioral contract. The classes here intentionally model only the
fields used by the manifold so they remain lightweight and easy to parse in
tests.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ..core import alias_defaults, base_model, normalize


class StreamOptions(BaseModel):
    """Streaming options accepted by the Responses API."""

    include_obfuscation: bool | None = None

    model_config = ConfigDict(extra="forbid")


class ResponsesRequest(BaseModel):
    """Request body for the OpenAI Responses API.

    The model validator normalizes model aliases and overlays any alias
    defaults (e.g. reasoning effort) without overwriting explicit user
    choices.
    """

    model: str
    input: str | list[dict[str, Any]] | None = None
    instructions: str | None = None
    stream: bool = False
    store: bool | None = True
    background: bool | None = False
    conversation: str | dict[str, Any] | None = None
    include: list[str] | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    metadata: dict[str, str] | None = None
    parallel_tool_calls: bool | None = True
    previous_response_id: str | None = None
    prompt: dict[str, Any] | None = None
    prompt_cache_key: str | None = None
    prompt_cache_retention: str | None = None
    reasoning: dict[str, Any] | None = None
    safety_identifier: str | None = None
    service_tier: str | None = None
    stream_options: StreamOptions | None = None
    temperature: float | None = 1.0
    top_p: float | None = 1.0
    top_logprobs: int | None = None
    tool_choice: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    truncation: str | None = "disabled"
    text: dict[str, Any] | None = None
    model_router_result: dict[str, Any] | None = None
    user: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _apply_model_alias_defaults(self) -> "ResponsesRequest":
        """Normalize model aliases and merge default parameters.

        * ``model`` is normalized to the canonical base model using
          ``model_catalog.base_model``.
        * Any alias-implied defaults are deep-merged into the request **only
          when a value is not already provided**.
        """

        original_model = self.model or ""
        canonical_model = base_model(original_model)
        defaults = alias_defaults(original_model) or {}

        if canonical_model == normalize(original_model) and not defaults:
            return self

        data = json.loads(self.model_dump_json(exclude_none=False))
        data["model"] = canonical_model

        if defaults:
            _deep_overlay(data, defaults)

        for key, value in data.items():
            setattr(self, key, value)
        return self


def _deep_overlay(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Merge ``src`` onto ``dst`` without overwriting explicit values."""

    for key, value in src.items():
        if isinstance(value, dict):
            node = dst.get(key)
            if isinstance(node, dict):
                _deep_overlay(node, value)
            elif node is None:
                dst[key] = deepcopy(value)
        elif isinstance(value, list):
            existing = dst.get(key)
            if isinstance(existing, list):
                seen: set[str] = set()
                merged: list[Any] = []
                for item in existing + value:
                    marker = _stable_json_key(item)
                    if marker not in seen:
                        seen.add(marker)
                        merged.append(item)
                dst[key] = merged
            elif existing is None:
                dst[key] = list(value)
        else:
            if key not in dst or dst.get(key) is None:
                dst[key] = value
    return dst


def _stable_json_key(value: Any) -> str:
    """Produce a stable key for deduplicating list entries."""

    try:
        return json.dumps(value, sort_keys=True)
    except Exception:
        return str(id(value))


class ResponseEvent(BaseModel):
    """Base class for streaming response events."""

    type: str
    sequence_number: Optional[int] = None

    model_config = ConfigDict(extra="ignore")


class ResponseOutputTextDeltaEvent(ResponseEvent):
    type: str = "response.output_text.delta"
    output_index: Optional[int] = None
    item_id: Optional[str] = None
    content_index: Optional[int] = None
    delta: Optional[str] = None
    logprobs: list[Any] | None = None
    obfuscation: str | None = None


class ResponseReasoningSummaryTextDoneEvent(ResponseEvent):
    type: str = "response.reasoning_summary_text.done"
    output_index: Optional[int] = None
    item_id: Optional[str] = None
    summary_index: Optional[int] = None
    text: Optional[str] = None


class ResponseOutputTextAnnotationAddedEvent(ResponseEvent):
    type: str = "response.output_text.annotation.added"
    output_index: Optional[int] = None
    item_id: Optional[str] = None
    content_index: Optional[int] = None
    annotation_index: Optional[int] = None
    annotation: dict[str, Any] | None = None


class ResponseOutputItemAddedEvent(ResponseEvent):
    type: str = "response.output_item.added"
    output_index: Optional[int] = None
    item: dict[str, Any] | None = None


class ResponseOutputItemDoneEvent(ResponseEvent):
    type: str = "response.output_item.done"
    output_index: Optional[int] = None
    item: dict[str, Any] | None = None


class ResponseCodeInterpreterCallInProgressEvent(ResponseEvent):
    type: str = "response.code_interpreter_call.in_progress"
    output_index: Optional[int] = None


class ResponseCodeInterpreterCallInterpretingEvent(ResponseEvent):
    type: str = "response.code_interpreter_call.interpreting"
    output_index: Optional[int] = None


class ResponseCodeInterpreterCallCodeDeltaEvent(ResponseEvent):
    type: str = "response.code_interpreter_call.code.delta"
    output_index: Optional[int] = None
    delta: Optional[str] = None


class ResponseCodeInterpreterCallCodeDoneEvent(ResponseEvent):
    type: str = "response.code_interpreter_call.code.done"
    output_index: Optional[int] = None
    code: Optional[str] = None


class ResponseCodeInterpreterCallCompletedEvent(ResponseEvent):
    type: str = "response.code_interpreter_call.completed"
    output_index: Optional[int] = None


class ResponseCompletedEvent(ResponseEvent):
    type: str = "response.completed"
    response: dict[str, Any]


class ResponseIncompleteEvent(ResponseEvent):
    type: str = "response.incomplete"
    error_message: str | None = None
    response: dict[str, Any] | None = None


class ResponseFailedEvent(ResponseEvent):
    type: str = "response.failed"
    error_message: str | None = None
    response: dict[str, Any] | None = None


ResponsesEvent = (
    ResponseOutputTextDeltaEvent
    | ResponseReasoningSummaryTextDoneEvent
    | ResponseOutputTextAnnotationAddedEvent
    | ResponseOutputItemAddedEvent
    | ResponseOutputItemDoneEvent
    | ResponseCodeInterpreterCallInProgressEvent
    | ResponseCodeInterpreterCallInterpretingEvent
    | ResponseCodeInterpreterCallCodeDeltaEvent
    | ResponseCodeInterpreterCallCodeDoneEvent
    | ResponseCodeInterpreterCallCompletedEvent
    | ResponseCompletedEvent
    | ResponseIncompleteEvent
    | ResponseFailedEvent
)

_RESPONSES_EVENT_ADAPTER = TypeAdapter(ResponsesEvent)
_RESPONSES_REQUEST_ADAPTER = TypeAdapter(ResponsesRequest)


def parse_responses_event(payload: Mapping[str, Any] | ResponsesEvent) -> ResponsesEvent:
    """Coerce a raw payload into a typed ``ResponsesEvent``."""

    if isinstance(payload, ResponseEvent):
        return payload
    return _RESPONSES_EVENT_ADAPTER.validate_python(payload)


def validate_responses_request(payload: ResponsesRequest | Mapping[str, Any]) -> ResponsesRequest:
    """Coerce/validate a payload into a ``ResponsesRequest`` instance."""

    if isinstance(payload, ResponsesRequest):
        return payload
    return _RESPONSES_REQUEST_ADAPTER.validate_python(payload)


def dump_responses_request(payload: ResponsesRequest | Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-ready dict with ``exclude_none=True`` applied."""

    return validate_responses_request(payload).model_dump(exclude_none=True)


__all__ = [
    "ResponseEvent",
    "ResponsesEvent",
    "ResponsesRequest",
    "ResponseCompletedEvent",
    "ResponseFailedEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseCodeInterpreterCallInProgressEvent",
    "ResponseCodeInterpreterCallInterpretingEvent",
    "ResponseCodeInterpreterCallCodeDeltaEvent",
    "ResponseCodeInterpreterCallCodeDoneEvent",
    "ResponseCodeInterpreterCallCompletedEvent",
    "ResponseOutputTextAnnotationAddedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningSummaryTextDoneEvent",
    "StreamOptions",
    "dump_responses_request",
    "parse_responses_event",
    "validate_responses_request",
]
