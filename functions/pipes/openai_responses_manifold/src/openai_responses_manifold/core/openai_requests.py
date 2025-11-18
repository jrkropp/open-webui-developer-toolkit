"""Request DTOs and helpers for OpenAI Responses and Chat Completions."""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ..model_catalog import MODEL_ALIASES, alias_defaults
from .ids import base_model


class ReasoningParams(BaseModel):
    """Reasoning configuration accepted by the Responses API."""

    effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
    summary: str | None = None

    model_config = ConfigDict(extra="forbid")


class StreamOptions(BaseModel):
    """Streaming options for responses."""

    include_usage: bool | None = None

    model_config = ConfigDict(extra="forbid")


class ResponseCreateParams(BaseModel):
    """Request body for the OpenAI Responses API."""

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
    reasoning: ReasoningParams | None = None
    safety_identifier: str | None = None
    service_tier: Literal["auto", "default", "flex", "priority"] | None = None
    stream_options: StreamOptions | None = None
    temperature: float | None = 1.0
    top_p: float | None = 1.0
    top_logprobs: int | None = None
    tool_choice: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    truncation: Literal["auto", "disabled"] | None = "disabled"
    text: dict[str, Any] | None = None
    model_router_result: dict[str, Any] | None = None
    include_obfuscation: bool | None = False
    user: str | None = None  # deprecated upstream; kept for compatibility

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _normalize_aliases(self) -> "ResponseCreateParams":
        """Normalize model aliases and merge default parameters."""

        orig_model = self.model or ""
        canonical_model = base_model(orig_model, MODEL_ALIASES)
        defaults = alias_defaults(orig_model) or {}

        if canonical_model == orig_model and not defaults:
            return self

        data = json.loads(self.model_dump_json(exclude_none=False))
        data["model"] = canonical_model

        def _deep_overlay(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
            for key, value in src.items():
                if isinstance(value, dict):
                    node = dst.get(key)
                    if isinstance(node, dict):
                        _deep_overlay(node, value)
                    else:
                        dst[key] = json.loads(json.dumps(value))
                elif isinstance(value, list):
                    existing = dst.get(key)
                    if isinstance(existing, list):
                        seen: set[tuple[str, str]] = set()
                        merged: list[Any] = []

                        def _make_key(item: Any) -> tuple[str, str]:
                            try:
                                return ("json", json.dumps(item, sort_keys=True))
                            except Exception:
                                return ("id", str(id(item)))

                        for item in existing + value:
                            key_tuple = _make_key(item)
                            if key_tuple not in seen:
                                seen.add(key_tuple)
                                merged.append(item)
                        dst[key] = merged
                    else:
                        dst[key] = list(value)
                else:
                    dst[key] = value
            return dst

        if defaults:
            _deep_overlay(data, defaults)

        for key, value in data.items():
            setattr(self, key, value)
        return self


class CompletionCreateParams(BaseModel):
    """Request body for OpenAI's Chat Completions API."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False

    model_config = ConfigDict(extra="allow")


_RESPONSES_BODY_ADAPTER = TypeAdapter(ResponseCreateParams)


def validate_response_create_params(payload: ResponseCreateParams | Mapping[str, Any]) -> ResponseCreateParams:
    """Coerce/validate a payload into a ResponseCreateParams instance."""

    if isinstance(payload, ResponseCreateParams):
        return payload
    return _RESPONSES_BODY_ADAPTER.validate_python(payload)


def dump_response_create_params(payload: ResponseCreateParams | Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-ready dict with ``exclude_none=True`` applied."""

    return validate_response_create_params(payload).model_dump(exclude_none=True)


__all__ = [
    "CompletionCreateParams",
    "ReasoningParams",
    "StreamOptions",
    "ResponseCreateParams",
    "validate_response_create_params",
    "dump_response_create_params",
]
