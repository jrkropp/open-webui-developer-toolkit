"""Pydantic request bodies for the Completions and Responses APIs."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from .capabilities import MODEL_ALIASES, alias_defaults
from .ids import base_model
from .messages import (
    assistant_text_item,
    developer_message,
    normalize_user_blocks,
    user_blocks_to_responses_items,
)


class CompletionsBody(BaseModel):
    """Request body compatible with OpenAI's legacy Completions API."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False

    class Config:
        extra = "allow"


class ResponsesBody(BaseModel):
    """Request body for the OpenAI Responses API."""

    model: str
    input: str | list[dict[str, Any]]
    instructions: str | None = ""
    stream: bool = False
    store: bool | None = False
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    truncation: Literal["auto", "disabled"] | None = None
    reasoning: dict[str, Any] | None = None
    parallel_tool_calls: bool | None = True
    user: str | None = None
    tool_choice: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    include: list[str] | None = None
    text: dict[str, Any] | None = None
    model_router_result: dict[str, Any] | None = None

    class Config:
        extra = "allow"

    @model_validator(mode="after")
    def _apply_alias_defaults(self) -> ResponsesBody:
        """Normalize aliases and merge default parameters."""

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

    @classmethod
    def from_completions(
        cls,
        completions_body: CompletionsBody,
        *,
        history_input: list[dict[str, Any]] | None = None,
        **extra_params: Any,
    ) -> ResponsesBody:
        """Convert a Completions request payload into Responses format."""

        completions_dict = completions_body.model_dump(exclude_none=True)

        unsupported_fields = {
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "logit_bias",
            "logprobs",
            "top_logprobs",
            "n",
            "stop",
            "response_format",
            "suffix",
            "stream_options",
            "audio",
            "function_call",
            "functions",
            "reasoning_effort",
            "max_tokens",
            "tools",
            "extra_tools",
        }

        sanitized_params: dict[str, Any] = {}
        for key, value in completions_dict.items():
            if key in unsupported_fields:
                continue
            sanitized_params[key] = value

        if "max_tokens" in completions_dict:
            sanitized_params["max_output_tokens"] = completions_dict["max_tokens"]

        effort = completions_dict.get("reasoning_effort")
        if effort:
            reasoning = sanitized_params.get("reasoning", {})
            reasoning.setdefault("effort", effort)
            sanitized_params["reasoning"] = reasoning

        instructions = next(
            (
                msg["content"]
                for msg in reversed(completions_dict.get("messages", []))
                if msg.get("role") == "system"
            ),
            None,
        )
        if instructions:
            sanitized_params["instructions"] = instructions

        messages = completions_dict.get("messages")
        if messages is not None:
            sanitized_params.pop("messages", None)
            sanitized_params["input"] = (
                history_input if history_input is not None else _default_input_from_messages(messages)
            )

        return cls(**sanitized_params, **extra_params)


def _default_input_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback conversion from OpenWebUI messages when no history builder is provided."""

    input_items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "user":
            blocks = user_blocks_to_responses_items(
                normalize_user_blocks(message.get("content"))
            )
            if blocks:
                input_items.append({"role": "user", "content": blocks})
            continue
        if role == "developer":
            content = message.get("content")
            if isinstance(content, str) and content:
                input_items.append(developer_message(content))
            continue
        if role == "assistant":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                input_items.append(assistant_text_item(content.strip()))
    return input_items


__all__ = ["CompletionsBody", "ResponsesBody"]
