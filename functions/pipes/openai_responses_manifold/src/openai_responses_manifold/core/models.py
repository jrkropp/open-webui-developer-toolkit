"""Pydantic request/response models and transformations."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from ..infra.persistence import fetch_openai_response_items
from .capabilities import alias_defaults, base_model
from .markers import (
    contains_marker,
    extract_markers,
    parse_marker,
    split_text_by_markers,
)

logger = logging.getLogger(__name__)


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
        """Normalize alias defaults so callers get a canonical model id."""

        orig_model = self.model or ""
        canonical_model = base_model(orig_model)
        defaults = alias_defaults(orig_model) or {}

        if canonical_model == orig_model and not defaults:
            return self

        data = json.loads(self.model_dump_json(exclude_none=False))
        data["model"] = canonical_model

        def _deep_overlay(dst: dict, src: dict) -> dict:
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
                            except Exception:  # pragma: no cover - fallback
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

    @staticmethod
    def transform_owui_tools(
        __tools__: dict[str, dict] | None, *, strict: bool = False
    ) -> list[dict]:
        """Convert Open WebUI tool registry entries into OpenAI tool specs."""

        if not __tools__:
            return []

        tools: list[dict] = []
        for item in __tools__.values():
            spec = item.get("spec") or {}
            name = spec.get("name")
            if not name:
                continue

            params = spec.get("parameters") or {"type": "object", "properties": {}}
            tool = {
                "type": "function",
                "name": name,
                "description": spec.get("description") or name,
                "parameters": ResponsesBody._strictify_schema(params) if strict else params,
            }
            if strict:
                tool["strict"] = True
            tools.append(tool)
        return tools

    @staticmethod
    def _strictify_schema(schema: Any) -> dict:
        """Strictify JSON schema nodes for OpenAI's Responses API."""

        if not isinstance(schema, dict):
            return {}

        data = json.loads(json.dumps(schema))

        def _enforce(node: dict) -> None:
            node_type = node.get("type")
            is_object = (
                node_type == "object"
                or (isinstance(node_type, list) and "object" in node_type)
                or "properties" in node
            )
            if is_object:
                props = node.setdefault("properties", {})
                if not isinstance(props, dict):
                    props = {}
                    node["properties"] = props

                original_required = set(node.get("required") or [])
                node["additionalProperties"] = False
                node["required"] = list(props.keys())

                for name, prop in props.items():
                    if not isinstance(prop, dict):
                        continue
                    if name not in original_required:
                        ptype = prop.get("type")
                        if isinstance(ptype, str) and ptype != "null":
                            prop["type"] = [ptype, "null"]
                        elif isinstance(ptype, list) and "null" not in ptype:
                            prop["type"] = [*ptype, "null"]
                    _enforce(prop)

            items = node.get("items")
            if isinstance(items, dict):
                _enforce(items)
            elif isinstance(items, list):
                for entry in items:
                    if isinstance(entry, dict):
                        _enforce(entry)

            for key in ("anyOf", "oneOf"):
                branches = node.get(key)
                if isinstance(branches, list):
                    for branch in branches:
                        if isinstance(branch, dict):
                            _enforce(branch)

        _enforce(data)
        return data

    @staticmethod
    def _build_mcp_tools(mcp_json: str) -> list[dict]:
        """Build MCP tool descriptors from the valve JSON."""

        if not mcp_json:
            return []

        def _coerce_to_list(value: Any) -> list[dict]:
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
            return []

        try:
            decoded = json.loads(mcp_json)
        except Exception as exc:  # pragma: no cover - valved bug
            logger.warning("REMOTE_MCP_SERVERS_JSON is not valid JSON: %s", exc)
            return []

        tools: list[dict] = []
        for item in _coerce_to_list(decoded):
            tool = {
                "type": "mcp",
                "server_label": item.get("server_label"),
                "server_url": item.get("server_url"),
            }
            for key in (
                "model_preference",
                "client_capabilities",
                "require_approval",
                "allowed_tools",
            ):
                if key in item:
                    tool[key] = item[key]
            tools.append(tool)
        return tools

    @staticmethod
    def transform_messages_to_input(
        messages: list[dict[str, Any]],
        chat_id: str | None = None,
        openwebui_model_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert Open WebUI chat messages into Responses API input items."""

        required_item_ids: set[str] = set()
        if chat_id and openwebui_model_id:
            for message in messages:
                if (
                    message.get("role") == "assistant"
                    and message.get("content")
                    and contains_marker(message["content"])
                ):
                    for marker in extract_markers(message["content"], parsed=True):
                        required_item_ids.add(marker["ulid"])

        items_lookup: dict[str, dict[str, Any]] = {}
        if chat_id and openwebui_model_id and required_item_ids:
            items_lookup = fetch_openai_response_items(
                chat_id,
                list(required_item_ids),
                openwebui_model_id=openwebui_model_id,
            )

        openai_input: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")

            if role == "system":
                continue

            if role == "user":
                blocks = message.get("content") or []
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]

                transform = {
                    "text": lambda block: {"type": "input_text", "text": block.get("text", "")},
                    "image_url": lambda block: {
                        "type": "input_image",
                        "image_url": block.get("image_url", {}).get("url"),
                    },
                    "input_file": lambda block: {
                        "type": "input_file",
                        "file_id": block.get("file_id"),
                    },
                }
                openai_input.append(
                    {
                        "role": "user",
                        "content": [
                            transform.get(block.get("type"), lambda b: b)(block)
                            for block in blocks
                            if block
                        ],
                    }
                )
                continue

            if role == "developer":
                openai_input.append({"role": "developer", "content": content})
                continue

            if contains_marker(content):
                for segment in split_text_by_markers(content):
                    if segment["type"] == "marker":
                        marker = parse_marker(segment["marker"])
                        item = items_lookup.get(marker["ulid"])
                        if item is not None:
                            openai_input.append(item)
                    elif segment["type"] == "text" and segment["text"].strip():
                        openai_input.append(
                            {
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": segment["text"].strip()}
                                ],
                            }
                        )
            elif content:
                openai_input.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                )

        return openai_input

    @classmethod
    def from_completions(
        ResponsesBody,
        completions_body: CompletionsBody,
        chat_id: str | None = None,
        openwebui_model_id: str | None = None,
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

        sanitized_params = {}
        for key, value in completions_dict.items():
            if key in unsupported_fields:
                logger.warning("Dropping unsupported parameter: %s", key)
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
                if msg["role"] == "system"
            ),
            None,
        )
        if instructions:
            sanitized_params["instructions"] = instructions

        if "messages" in completions_dict:
            sanitized_params.pop("messages", None)
            sanitized_params["input"] = ResponsesBody.transform_messages_to_input(
                completions_dict.get("messages", []),
                chat_id=chat_id,
                openwebui_model_id=openwebui_model_id,
            )

        return ResponsesBody(
            **sanitized_params,
            **extra_params,
        )
