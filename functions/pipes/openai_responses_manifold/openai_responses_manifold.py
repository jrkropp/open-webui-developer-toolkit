"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
required_open_webui_version: 0.6.3
version: 0.8.28
license: MIT
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 1. Imports
# ─────────────────────────────────────────────────────────────────────────────
# Standard library, third-party, and Open WebUI imports
# Standard library imports
import textwrap
from typing import Tuple
import asyncio
import datetime
import inspect
import json
import logging
import os
import re
import sys
import secrets
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Literal, Optional, Union
from urllib.parse import urlparse

# Third-party imports
import aiohttp
from fastapi import Request
from pydantic import BaseModel, Field, model_validator

# Open WebUI internals
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models

# ─────────────────────────────────────────────────────────────────────────────
# 2. Constants & Global Configuration
# ─────────────────────────────────────────────────────────────────────────────
# Feature flags and other module level constants
FEATURE_SUPPORT = {
    # OpenAI's built-in web search tool.
    "web_search_tool": {"gpt-5", "gpt-5-mini", "gpt-5-pro", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o3", "o3-pro", "o4-mini", "o3-deep-research", "o4-mini-deep-research"},
    # OpenAI's built-in image generation tool.
    "image_gen_tool": {"gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3"},
    # OpenAI's native function calling support.
    "function_calling": {"gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o4-mini", "o3-mini", "o3-pro", "o3-deep-research", "o4-mini-deep-research"},
    # OpenAI's reasoning models.
    "reasoning": {"gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "o3", "o4-mini", "o3-mini","o3-pro", "o3-deep-research", "o4-mini-deep-research"},
    # OpenAI's reasoning summary feature.  May require OpenAI org verification before use.
    "reasoning_summary": {"gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "o3", "o4-mini", "o4-mini-high", "o3-mini", "o3-mini-high", "o3-pro", "o3-deep-research", "o4-mini-deep-research"},
    # Supports OpenAI's verbosity parameter.
    "verbosity": {"gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro"},

    # NOTE: Deep Research models are not yet supported in pipe.  Work in-progress.
    "deep_research": {"o3-deep-research", "o4-mini-deep-research"},
}

DETAILS_RE = re.compile(
    r"<details\b[^>]*>.*?</details>|!\[.*?]\(.*?\)",
    re.S | re.I,
)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Data Models
# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models for validating request and response payloads
class CompletionsBody(BaseModel):
    """
    Represents the body of a completions request to OpenAI completions API.
    """
    model: str
    messages: List[Dict[str, Any]]
    stream: bool = False

    class Config:
        extra = "allow" # Pass through additional OpenAI parameters automatically

    # Sanitize the ``model`` field after validation.
    @model_validator(mode='after')
    def normalize_model(self) -> "CompletionsBody":
        """Normalize model: strip function/module prefixes and map '-high' pseudo-models."""

        # Remove any function/module prefix if present, e.g.
        #   "openai_responses.gpt-5-pro" → "gpt-5-pro"
        #   "openai_responses_api_manifold.gpt-4.1-nano" → "gpt-4.1-nano"
        # This only strips a leading segment of [a-z0-9_]+ followed by a dot,
        # so legitimate model IDs like "gpt-4.1" are not affected.
        m = (self.model or "").strip()
        m = re.sub(r'^(?:[a-z0-9_]+\.)+', '', m, flags=re.I)

        key = m.lower()

        # Alias mapping: pseudo ID -> (real model, reasoning effort)
        aliases = {
            # GPT-5 Thinking family
            "gpt-5-thinking": ("gpt-5", None),
            "gpt-5-thinking-minimal": ("gpt-5", "minimal"),
            "gpt-5-thinking-high": ("gpt-5", "high"),
            "gpt-5-thinking-mini": ("gpt-5-mini", None),
            "gpt-5-thinking-mini-minimal": ("gpt-5-mini", "minimal"),
            "gpt-5-thinking-nano": ("gpt-5-nano", None),
            "gpt-5-thinking-nano-minimal": ("gpt-5-nano", "minimal"),

            # Placeholder router
            "gpt-5-auto": ("gpt-5-chat-latest", None),

            # Backwards compatibility
            "o3-mini-high": ("o3-mini", "high"),
            "o4-mini-high": ("o4-mini", "high"),
        }

        if key in aliases:
            real, effort = aliases[key]
            self.model = real
            if effort:
                self.reasoning_effort = effort  # type: ignore[assignment]
        else:
            self.model = key  # pass through official IDs as lowercase

        return self

class ResponsesBody(BaseModel):
    """
    Represents the body of a responses request to OpenAI Responses API.
    """
    # Required parameters
    model: str
    input: Union[str, List[Dict[str, Any]]] # plain text, or rich array

    # Optional parameters
    instructions: Optional[str] = ""              # system / developer prompt
    stream: bool = False                          # SSE chunking
    store: Optional[bool] = False                  # persist response on OpenAI side
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_output_tokens: Optional[int] = None
    truncation: Optional[Literal["auto", "disabled"]] = None
    reasoning: Optional[Dict[str, Any]] = None    # {"effort":"high", ...}
    parallel_tool_calls: Optional[bool] = True
    user: Optional[str] = None                # user ID for the request.  Recommended to improve caching hits.
    tool_choice: Optional[Dict[str, Any]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    include: Optional[List[str]] = None           # extra output keys

    class Config:
        extra = "allow" # Allow additional OpenAI parameters automatically (future-proofing)

    @staticmethod
    def transform_tools(
        tools: dict | list | None = None,
        *,
        strict: bool = False,
    ) -> list[dict]:
        """
        Canonicalise any mixture of tool specs to the OpenAI Responses-API list.

        • Accepts a WebUI __tools__ *dict* or a plain *list*.
        • Flattens only:
            - __tools__ entries  {"spec": {...}}
            - Chat-Completions wrappers {"type":"function","function": {...}}
        • Leaves every other tool (e.g. {"type":"web_search", …}) untouched.
        • Duplicate keys:
            - functions   → by *name*
            - non-functions→ by *type*
        later items win.
        """
        if not tools:
            return []

        # 1. normalise input to an iterable of dicts -----------------------
        iterable = tools.values() if isinstance(tools, dict) else tools

        native, converted = [], []

        for item in iterable:
            if not isinstance(item, dict):
                continue

            # a) __tools__ entry
            if "spec" in item:
                spec = item["spec"]
                if isinstance(spec, dict):
                    converted.append({
                        "type":        "function",
                        "name":        spec.get("name", ""),
                        "description": spec.get("description", ""),
                        "parameters":  spec.get("parameters", {}),
                    })
                continue

            # b) Chat-Completions wrapper
            if item.get("type") == "function" and "function" in item:
                fn = item["function"]
                if isinstance(fn, dict):
                    converted.append({
                        "type":        "function",
                        "name":        fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters":  fn.get("parameters", {}),
                    })
                continue

            # c) Anything else (including web_search) → keep verbatim
            native.append(dict(item))

        # 2. strict-mode hardening for the bits we just converted ----------
        if strict:
            for tool in converted:
                params = tool.setdefault("parameters", {})
                props  = params.setdefault("properties", {})
                params["required"] = list(props)
                params["additionalProperties"] = False
                for schema in props.values():
                    t = schema.get("type")
                    schema["type"] = [t, "null"] if isinstance(t, str) else (
                        t + ["null"] if isinstance(t, list) and "null" not in t else t
                    )
                tool["strict"] = True

        # 3. deduplicate ---------------------------------------------------
        canonical: dict[str, dict] = {}
        for t in native + converted:                     # later wins
            key = t["name"] if t.get("type") == "function" else t["type"]
            canonical[key] = t

        return list(canonical.values())

    # -----------------------------------------------------------------------
    # Helper: turn the JSON string into valid MCP tool dicts
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_mcp_tools(mcp_json: str) -> list[dict]:
        """
        Parse ``REMOTE_MCP_SERVERS_JSON`` and return a list of ready-to-use
        tool objects (``{\"type\":\"mcp\", …}``).  Silently drops invalid items.
        """
        if not mcp_json or not mcp_json.strip():
            return []

        try:
            data = json.loads(mcp_json)
        except Exception as exc:                             # malformed JSON
            logging.getLogger(__name__).warning(
                "REMOTE_MCP_SERVERS_JSON could not be parsed (%s); ignoring.", exc
            )
            return []

        # Accept a single object or a list
        items = data if isinstance(data, list) else [data]

        valid_tools: list[dict] = []
        for idx, obj in enumerate(items, start=1):
            if not isinstance(obj, dict):
                logging.getLogger(__name__).warning(
                    "REMOTE_MCP_SERVERS_JSON item %d ignored: not an object.", idx
                )
                continue

            # Minimum viable keys
            label = obj.get("server_label")
            url   = obj.get("server_url")
            if not (label and url):
                logging.getLogger(__name__).warning(
                    "REMOTE_MCP_SERVERS_JSON item %d ignored: "
                    "'server_label' and 'server_url' are required.", idx
                )
                continue

            # Whitelist only official MCP keys so users can copy-paste API examples
            allowed = {
                "server_label",
                "server_url",
                "require_approval",
                "allowed_tools",
                "headers",
            }
            tool = {"type": "mcp"}
            tool.update({k: v for k, v in obj.items() if k in allowed})

            valid_tools.append(tool)

        return valid_tools
    
    @staticmethod
    def transform_messages_to_input(
        messages: List[Dict[str, Any]],
        chat_id: Optional[str] = None,
        openwebui_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build an OpenAI Responses-API `input` array from Open WebUI-style messages.

        Parameters `chat_id` and `openwebui_model_id` are optional. When both are
        supplied and the messages contain empty-link encoded item references, the
        function fetches persisted items from the database and injects them in the
        correct order. When either parameter is missing, the messages are simply
        converted without attempting to fetch persisted items.

        Returns
        -------
        List[dict] : The fully-formed `input` list for the OpenAI Responses API.
        """

        required_item_ids: set[str] = set()

        # Gather all markers from assistant messages (if both IDs are provided)
        if chat_id and openwebui_model_id:
            for m in messages:
                if (
                    m.get("role") == "assistant"
                    and m.get("content")
                    and contains_marker(m["content"])
                ):
                    for mk in extract_markers(m["content"], parsed=True):
                        required_item_ids.add(mk["ulid"])

        # Fetch persisted items if both IDs are provided and there are encoded item IDs
        items_lookup: dict[str, dict] = {}
        if chat_id and openwebui_model_id and required_item_ids:
            items_lookup = fetch_openai_response_items(
                chat_id,
                list(required_item_ids),
                openwebui_model_id=openwebui_model_id,
            )

        # Build the OpenAI input array
        openai_input: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            raw_content = msg.get("content", "")

            # Skip system messages; they belong in `instructions`
            if role == "system":
                continue

            # -------- user message ---------------------------------------- #
            if role == "user":
                # Convert string content to a block list (["Hello"] → [{"type": "text", "text": "Hello"}])
                content_blocks = msg.get("content") or []
                if isinstance(content_blocks, str):
                    content_blocks = [{"type": "text", "text": content_blocks}]

                # Only transform known types; leave all others unchanged
                block_transform = {
                    "text":       lambda b: {"type": "input_text",  "text": b.get("text", "")},
                    "image_url":  lambda b: {"type": "input_image", "image_url": b.get("image_url", {}).get("url")},
                    "input_file": lambda b: {"type": "input_file",  "file_id": b.get("file_id")},
                }

                openai_input.append({
                    "role": "user",
                    "content": [
                        block_transform.get(block.get("type"), lambda b: b)(block)
                        for block in content_blocks if block
                    ],
                })
                continue

            # -------- developer message --------------------------------- #
            # Developer messages are treated as system messages in Responses API
            if role == "developer":
                openai_input.append({
                    "role": "developer",
                    "content": raw_content,
                })
                continue

            # -------- assistant message ----------------------------------- #
            # Assistant messages might contain <details> or embedded images that need stripping
            if "<details" in raw_content or "![" in raw_content:
                content = DETAILS_RE.sub("", raw_content).strip()
            else:
                content = raw_content

            if contains_marker(content):
                for segment in split_text_by_markers(content):
                    if segment["type"] == "marker":
                        mk = parse_marker(segment["marker"])
                        item = items_lookup.get(mk["ulid"])
                        if item is not None:
                            openai_input.append(item)
                    elif segment["type"] == "text" and segment["text"].strip():
                        openai_input.append({
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": segment["text"].strip()}]
                        })
            else:
                # Plain assistant text (no encoded IDs detected)
                if content:
                    openai_input.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": content}],
                        }
                    )

        return openai_input

    @classmethod
    def from_completions(
        ResponsesBody, completions_body: "CompletionsBody", chat_id: Optional[str] = None, openwebui_model_id: Optional[str] = None, **extra_params
    ) -> "ResponsesBody":
        """
        Convert CompletionsBody → ResponsesBody.

        - Drops unsupported fields (clearly logged).
        - Converts max_tokens → max_output_tokens.
        - Converts reasoning_effort → reasoning.effort (without overwriting).
        - Builds messages in Responses API format.
        - Allows explicit overrides via kwargs.
        """
        completions_dict = completions_body.model_dump(exclude_none=True)

        # Step 1: Remove unsupported fields
        unsupported_fields = {
            # Fields that are not supported by OpenAI Responses API
            "frequency_penalty", "presence_penalty", "seed", "logit_bias",
            "logprobs", "top_logprobs", "n", "stop",
            "response_format", # Replaced with 'text' in Responses API
            "suffix", # Responses API does not support suffix
            "stream_options", # Responses API does not support stream options
            "audio", # Responses API does not support audio input
            "function_call", # Deprecated in favor of 'tool_choice'.
            "functions", # Deprecated in favor of 'tools'.

            # Fields that are dropped and manually handled in step 2.
            "reasoning_effort", "max_tokens"
        }
        sanitized_params = {}
        for key, value in completions_dict.items():
            if key in unsupported_fields:
                logging.warning(f"Dropping unsupported parameter: '{key}'")
            else:
                sanitized_params[key] = value

        # Step 2: Apply transformations
        # Rename max_tokens → max_output_tokens
        if "max_tokens" in completions_dict:
            sanitized_params["max_output_tokens"] = completions_dict["max_tokens"]

        # reasoning_effort → reasoning.effort (without overwriting existing effort)
        effort = completions_dict.get("reasoning_effort")
        if effort:
            reasoning = sanitized_params.get("reasoning", {})
            reasoning.setdefault("effort", effort)
            sanitized_params["reasoning"] = reasoning

        # Extract the last system message (if any)
        instructions = next((msg["content"] for msg in reversed(completions_dict.get("messages", [])) if msg["role"] == "system"), None)
        if instructions:
            sanitized_params["instructions"] = instructions

        # Transform input messages to OpenAI Responses API format
        if "messages" in completions_dict:
            sanitized_params.pop("messages", None)
            sanitized_params["input"] = ResponsesBody.transform_messages_to_input(
                completions_dict.get("messages", []),
                chat_id=chat_id,
                openwebui_model_id=openwebui_model_id
            )

        # Normalize model id: ensure no function/module prefix is sent to OpenAI
        model_id = (sanitized_params.get("model") or completions_body.model or "").lower()
        model_id = re.sub(r'^(?:[a-z0-9_]+\.)+', '', model_id, flags=re.I)
        sanitized_params["model"] = model_id
        model_family = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model_id)

        # Drop unsupported params for GPT-5 family
        if model_family.startswith("gpt-5"):
            for unsupported_param in ("temperature", "top_p"):
                if unsupported_param in sanitized_params:
                    logging.warning(
                        "Dropping unsupported parameter for GPT-5 model: '%s'",
                        unsupported_param,
                    )
                    sanitized_params.pop(unsupported_param, None)

        # Build the final ResponsesBody directly
        return ResponsesBody(
            **sanitized_params,
            **extra_params  # Overrides any parameters in sanitized_params with the same name since they are passed last
        )

# ─────────────────────────────────────────────────────────────────────────────
# 4. Main Controller: Pipe
# ─────────────────────────────────────────────────────────────────────────────
# Primary interface implementing the Responses manifold
class Pipe:
    # 4.1 Configuration Schemas
    class Valves(BaseModel):
        # 1) Connection & Auth
        BASE_URL: str = Field(
            default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )
        API_KEY: str = Field(
            default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )

        # 2) Models
        MODEL_ID: str = Field(
            default="gpt-5-auto, gpt-5-chat-latest, gpt-5-thinking, gpt-5-thinking-high, gpt-5-thinking-minimal, gpt-4.1-nano, chatgpt-4o-latest, o3, gpt-4o",
            description=(
            "Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. "
            "Supports all official OpenAI model IDs and pseudo IDs: "
            "gpt-5-auto, "
            "gpt-5-thinking, "
            "gpt-5-thinking-minimal, "
            "gpt-5-thinking-high, "
            "gpt-5-thinking-mini, "
            "gpt-5-thinking-mini-minimal, "
            "gpt-5-thinking-nano, "
            "gpt-5-thinking-nano-minimal, "
            "o3-mini-high, o4-mini-high."
            ),
        )

        # 3) Reasoning & summaries
        REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"] = Field(
            default="disabled",
            description="REQUIRES VERIFIED OPENAI ORG. Visible reasoning summary (auto | concise | detailed | disabled). Works on gpt-5, o3, o4-mini; ignored otherwise. Docs: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
        )
        PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"] = Field(
            default="disabled",
            description="REQUIRES VERIFIED OPENAI ORG. If verified, highly recommend using 'response' or 'conversation' for best results. If `disabled` (default) = never request encrypted reasoning tokens; if `response` = request tokens so the model can carry reasoning across tool calls for the current response; If `conversation` = also persist tokens for future messages in this chat (higher token usage; quality may vary).",
        )
        
        # 4) Tool execution behavior
        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
        )
        MAX_TOOL_CALLS: Optional[int] = Field(
            default=None,
            description=(
                "Maximum number of individual tool or function calls the model can make "
                "within a single response. Applies to the total number of calls across "
                "all built-in tools. Further tool-call attempts beyond this limit will be ignored."
            )
        )
        MAX_FUNCTION_CALL_LOOPS: int = Field(
            default=10,
            description=(
                "Maximum number of full execution cycles (loops) allowed per request. "
                "Each loop involves the model generating one or more function/tool calls, "
                "executing all requested functions, and feeding the results back into the model. "
                "Looping stops when this limit is reached or when the model no longer requests "
                "additional tool or function calls."
            )
        )

        # 6) Web search
        ENABLE_WEB_SEARCH_TOOL: bool = Field(
            default=False,
            description="Enable OpenAI's built-in 'web_search_preview' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini, o3, o4-mini, o4-mini-high).  NOTE: This appears to disable parallel tool calling. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
        )
        WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH_TOOL=True.",
        )
        WEB_SEARCH_USER_LOCATION: Optional[str] = Field(
            default=None,
            description='User location for web search context. Leave blank to disable. Must be in valid JSON format according to OpenAI spec.  E.g., {"type": "approximate","country": "US","city": "San Francisco","region": "CA"}.',
        )

        # 7) Persistence
        PERSIST_TOOL_RESULTS: bool = Field(
            default=True,
            description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
        )

        # 8) Integrations
        REMOTE_MCP_SERVERS_JSON: Optional[str] = Field(
            default=None,
            description=(
                "[EXPERIMENTAL] A JSON-encoded list (or single JSON object) defining one or more "
                "remote MCP servers to be automatically attached to each request. This can be useful "
                "for globally enabling tools across all chats.\n\n"
                "Note: The Responses API currently caches MCP server definitions at the start of each chat. "
                "This means the first message in a new thread may be slower. A more efficient implementation is planned."
                "Each item must follow the MCP tool schema supported by the OpenAI Responses API, for example:\n"
                '[{"server_label":"deepwiki","server_url":"https://mcp.deepwiki.com/mcp","require_approval":"never","allowed_tools": ["ask_question"]}]'
            ),
        )

        TRUNCATION: Literal["auto", "disabled"] = Field(
            default="auto",
            description="Truncation strategy for model responses. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
        )

        SERVICE_TIER: Literal["auto", "default", "flex", "priority"] = Field(
            default="auto",
            description=(
            "Specifies the processing type used for serving the request. "
            "If set to 'auto', the request will be processed with the service tier configured in the Project settings. "
            "If set to 'default', the request will be processed with the standard pricing and performance for the selected model. "
            "If set to 'flex' or 'priority', the request will be processed with the corresponding service tier. "
            "When not set, the default behavior is 'auto'."
            ),
        )

        # 9) Privacy & caching
        PROMPT_CACHE_KEY: Literal["id", "email"] = Field(
            default="id",
            description=(
                "Controls which user identifier is sent in the 'user' parameter to OpenAI. "
                "Passing a unique identifier enables OpenAI response caching (improves speed and reduces cost). "
                "Choose 'id' to use the OpenWebUI user ID (default; privacy-friendly), or 'email' to use the user's email address."
            ),
        )

        # 10) Logging
        LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
            default=os.getenv("GLOBAL_LOG_LEVEL", "INFO").upper(),
            description="Select logging level.  Recommend INFO or WARNING for production use. DEBUG is useful for development and debugging.",
        )


    class UserValves(BaseModel):
        """Per-user valve overrides."""
        LOG_LEVEL: Literal[
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"
        ] = Field(
            default="INHERIT",
            description="Select logging level. 'INHERIT' uses the pipe default.",
        )

    # 4.2 Constructor and Entry Points
    def __init__(self):
        self.type = "manifold"
        self.id = "openai_responses" # Unique ID for this manifold
        self.valves = self.Valves()  # Note: valve values are not accessible in __init__. Access from pipes() or pipe() methods.
        self.session: aiohttp.ClientSession | None = None
        self.logger = SessionLogger.get_logger(__name__)

    async def pipes(self):
        model_ids = [model_id.strip() for model_id in self.valves.MODEL_ID.split(",") if model_id.strip()]
        return [{"id": model_id, "name": f"OpenAI: {model_id}"} for model_id in model_ids]

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: Optional[dict[str, Any]] = None,
        __task_body__: Optional[dict[str, Any]] = None,
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> AsyncGenerator[str, None] | str | None:
        """Process a user request and return either a stream or final text.

        When ``body['stream']`` is ``True`` the method yields deltas from
        ``_run_streaming_loop``.  Otherwise it falls back to
        ``_run_nonstreaming_loop`` and returns the aggregated response.
        """
        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        openwebui_model_id = __metadata__.get("model", {}).get("id", "") # Full model ID, e.g. "openai_responses.gpt-4o"
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]  # Use 'id' or 'email' as configured
        features = __metadata__.get("features", {}).get("openai_responses", {}) # Custom location that this manifold uses to store feature flags

        # Set up session logger with session_id and log level
        SessionLogger.session_id.set(__metadata__.get("session_id", None))
        SessionLogger.log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        # Transform request body (Completions API -> Responses API).
        completions_body = CompletionsBody.model_validate(body)
        responses_body = ResponsesBody.from_completions(
            completions_body=completions_body,

            # If chat_id and openwebui_model_id are provided, from_completions() uses them to fetch previously persisted items (function_calls, reasoning, etc.) from DB and reconstruct the input array in the correct order.
            **({"chat_id": __metadata__["chat_id"]} if __metadata__.get("chat_id") else {}),
            **({"openwebui_model_id": openwebui_model_id} if openwebui_model_id else {}),

            # Additional optional parameters passed directly to ResponsesBody without validation. Overrides any parameters in the original body with the same name.
            truncation=valves.TRUNCATION,
            user=user_identifier,
            service_tier=valves.SERVICE_TIER,
            **({"max_tool_calls": valves.MAX_TOOL_CALLS} if valves.MAX_TOOL_CALLS is not None else {}),
        )

        # Detect if task model (generate title, generate tags, etc.), handle it separately
        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self._run_task_model_request(responses_body.model_dump(), valves) # Placeholder for task handling logic

        # If GPT-5-Auto, run through model router and update model.
        if openwebui_model_id.endswith(".gpt-5-auto"):
            await self._emit_notification(
                __event_emitter__,
                content="Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast).",
                level="info",
            )

            responses_body.model = await self._route_gpt5_auto(
                responses_body.input[-1].get("content", "") if responses_body.input else "",
                valves,
            )

        # Normalize to family-level model name (e.g., 'o3' from 'o3-2025-04-16') to be used for feature detection.
        model_family = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", responses_body.model)

        # Resolve __tools__ coroutine returned by newer Open WebUI versions.
        if inspect.isawaitable(__tools__):
            __tools__ = await __tools__

        # Add Open WebUI Tools (if any) to the ResponsesBody.
        # TODO: Also detect body['tools'] and merge them with __tools__.  This would allow users to pass tools in the request body from filters, etc.
        if __tools__ and model_family in FEATURE_SUPPORT["function_calling"]:
            responses_body.tools = ResponsesBody.transform_tools(
                tools=__tools__,
                strict=True,
            )

        # Add web_search tool only if supported, enabled, and effort != minimal
        # Noted that web search doesn't seem to work when effort = minimal.
        if (
            model_family in FEATURE_SUPPORT["web_search_tool"]
            and (valves.ENABLE_WEB_SEARCH_TOOL or features.get("web_search", False))
            and ((responses_body.reasoning or {}).get("effort", "").lower() != "minimal")
        ):
            responses_body.tools = responses_body.tools or []
            responses_body.tools.append({
                "type": "web_search_preview",
                "search_context_size": valves.WEB_SEARCH_CONTEXT_SIZE,
                **({"user_location": json.loads(valves.WEB_SEARCH_USER_LOCATION)} if valves.WEB_SEARCH_USER_LOCATION else {}),
            })

        # Append remote MCP servers (experimental)
        if valves.REMOTE_MCP_SERVERS_JSON:
            mcp_tools = ResponsesBody._build_mcp_tools(valves.REMOTE_MCP_SERVERS_JSON)
            if mcp_tools:
                responses_body.tools = (responses_body.tools or []) + mcp_tools

        # Check if tools are enabled but native function calling is disabled
        # If so, update the OpenWebUI model parameter to enable native function calling for future requests.
        if __tools__:
            model = Models.get_model_by_id(openwebui_model_id)
            if model:
                params = dict(model.params or {})
                if params.get("function_calling") != "native":
                    supports_function_calling = model_family in FEATURE_SUPPORT["function_calling"]

                    if supports_function_calling:
                        await self._emit_notification(
                            __event_emitter__,
                            content=f"Enabling native function calling for model: {openwebui_model_id}. Please re-run your query.",
                            level="info"
                        )

                        form_data = model.model_dump()
                        form_data["params"] = params
                        form_data["params"]["function_calling"] = "native"
                        form = ModelForm(**form_data)
                        Models.update_model_by_id(openwebui_model_id, form)

            
        # Enable reasoning summary if enabled and supported
        if model_family in FEATURE_SUPPORT["reasoning_summary"] and valves.REASONING_SUMMARY != "disabled":
            # Ensure reasoning param is a mutable dict so we can safely assign to it
            reasoning_params = dict(responses_body.reasoning or {})
            reasoning_params["summary"] = valves.REASONING_SUMMARY
            responses_body.reasoning = reasoning_params

        # Always request encrypted reasoning for in-turn carry (multi-tool) unless disabled
        if (model_family in FEATURE_SUPPORT["reasoning"]
            and valves.PERSIST_REASONING_TOKENS != "disabled"
            and responses_body.store is False):
             responses_body.include = responses_body.include or []
             if "reasoning.encrypted_content" not in responses_body.include:
                 responses_body.include.append("reasoning.encrypted_content")

        # Map WebUI "Add Details" / "More Concise" → text.verbosity (if supported by model), then strip the stub
        input_items = responses_body.input if isinstance(responses_body.input, list) else None
        if input_items:
            last_item = input_items[-1]
            content_blocks = last_item.get("content") if last_item.get("role") == "user" else None
            first_block = content_blocks[0] if isinstance(content_blocks, list) and content_blocks else {}
            last_user_text = (first_block.get("text") or "").strip().lower()

            directive_to_verbosity = {"add details": "high", "more concise": "low"}
            verbosity_value = directive_to_verbosity.get(last_user_text)

            if verbosity_value:
                # Check model support
                model_family = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", responses_body.model)
                if model_family in FEATURE_SUPPORT["verbosity"]:
                    # Set/overwrite verbosity (do NOT remove the stub message)
                    current_text_params = dict(getattr(responses_body, "text", {}) or {})
                    current_text_params["verbosity"] = verbosity_value
                    responses_body.text = current_text_params

                    # Remove the stub user message so the model doesn't see it
                    input_items.pop()  # or: del input_items[-1]

                    # Notify the user in the UI
                    await self._emit_notification(__event_emitter__,f"Regenerating with verbosity set to {verbosity_value}.",level="info")

                    self.logger.debug("Set text.verbosity=%s based on regenerate directive '%s'",verbosity_value, last_user_text)

        # Log the transformed request body
        self.logger.debug("Transformed ResponsesBody: %s", json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
            
        # Send to OpenAI Responses API
        if responses_body.stream:
            # Return async generator for partial text
            return await self._run_streaming_loop(responses_body, valves, __event_emitter__, __metadata__, __tools__)
        else:
            # Return final text (non-streaming)
            return await self._run_nonstreaming_loop(responses_body, valves, __event_emitter__, __metadata__, __tools__)

    # 4.3 Core Multi-Turn Handlers
    async def _run_streaming_loop(
        self,
        body: ResponsesBody,
        valves: Pipe.Valves,
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]],
        metadata: dict[str, Any] = {},
        tools: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Stream assistant responses incrementally, handling function calls, status updates, and tool usage.
        """
        tools = tools or {}
        openwebui_model = metadata.get("model", {}).get("id", "")
        assistant_message = ""
        total_usage: dict[str, Any] = {}
        ordinal_by_url: dict[str, int] = {}
        emitted_citations: list[dict] = []

        status_indicator = ExpandableStatusIndicator(event_emitter) # Custom class for simplifying the <details> expandable status updates
        status_indicator._done = False

        # Emit initial "thinking" block:
        # If reasoning model, write "Thinking…" to the expandable status emitter.
        model_family = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", body.model)
        if model_family in FEATURE_SUPPORT["reasoning"]:
            assistant_message = await status_indicator.add(
                assistant_message,
                status_title="Thinking…",
                status_content="Reading the question and building a plan to answer it. This may take a moment.",
            )

        # Send OpenAI Responses API request, parse and emit response
        try:
            for loop_idx in range(valves.MAX_FUNCTION_CALL_LOOPS):
                final_response: dict[str, Any] | None = None
                async for event in self.send_openai_responses_streaming_request(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                ):
                    etype = event.get("type")

                    # Efficient check if debug logging is enabled. If so, log the event name
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Received event: %s", etype)
                        # if doesn't end in .delta, log the full event
                        if not etype.endswith(".delta"):
                            self.logger.debug("Event data: %s", json.dumps(event, indent=2, ensure_ascii=False))

                    # ─── Emit partial delta assistant message
                    if etype == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            assistant_message += delta
                            await event_emitter({"type": "chat:message",
                                                 "data": {"content": assistant_message}})
                        continue

                    # ─── Reasoning summary -> status indicator (done only) ───────────────────────
                    if etype == "response.reasoning_summary_text.done":
                        text = (event.get("text") or "").strip()
                        if text:
                            # Use last bolded header as the title, else fallback
                            title_match = re.findall(r"\*\*(.+?)\*\*", text)
                            title = title_match[-1].strip() if title_match else "Thinking…"

                            # Remove bold markers from body
                            content = re.sub(r"\*\*(.+?)\*\*", "", text).strip()

                            assistant_message = await status_indicator.add(
                                assistant_message,
                                status_title=f"🧠 {title}",
                                status_content=content,
                            )
                        continue

                    # ─── Emit annotation
                    if etype == "response.output_text.annotation.added":
                        ann = event["annotation"]
                        url = ann.get("url", "").removesuffix("?utm_source=openai")
                        title = ann.get("title", "").strip()
                        domain = urlparse(url).netloc.lower().lstrip('www.')

                        # Have we already cited this URL?
                        already_cited = url in ordinal_by_url

                        if already_cited:
                            # Reuse the original citation number
                            citation_number = ordinal_by_url[url]
                        else:
                            # Assign next available number to this new citation URL
                            citation_number = len(ordinal_by_url) + 1
                            ordinal_by_url[url] = citation_number

                            # Emit the citation event now, because it's new
                            citation_payload = {
                                "source": {"name": domain, "url": url},
                                "document": [title],  # or snippet if you have it
                                "metadata": [{
                                    "source": url,
                                    "date_accessed": datetime.date.today().isoformat(),
                                }],
                            }
                            await event_emitter({"type": "source", "data": citation_payload})
                            emitted_citations.append(citation_payload)

                        # Insert the citation marker into the message text
                        assistant_message += f" [{citation_number}]"

                        # Remove the markdown link originally printed by the model
                        assistant_message = re.sub(
                            rf"\(\s*\[\s*{re.escape(domain)}\s*\]\([^)]+\)\s*\)",
                            " ",
                            assistant_message,
                            count=1,
                        ).strip()

                        # Send updated assistant message chunk to UI
                        await event_emitter({
                            "type": "chat:message",
                            "data": {"content": assistant_message},
                        })
                        continue

                    # ─── Emit status updates for in-progress items ──────────────────────
                    if etype == "response.output_item.added":
                        item = event.get("item", {})
                        item_type = item.get("type", "")
                        item_status = item.get("status", "")

                        # If type is message and status is in_progress, emit a status update
                        if item_type == "message" and item_status == "in_progress" and len(status_indicator._items) > 0:
                            # Emit a status update for the message
                            assistant_message = await status_indicator.add(
                                assistant_message,
                                status_title="📝 Responding to the user…",
                                status_content="",
                            )
                            continue

                    # ─── Emit detailed tool status upon completion ────────────────────────
                    if etype == "response.output_item.done":
                        item = event.get("item", {})
                        item_type = item.get("type", "")
                        item_name = item.get("name", "unnamed_tool")

                        # Skip irrelevant item types
                        if item_type in ("message"):
                            continue

                        # Persist all non-message items.
                        # If it's a reasoning item, only persist when PERSIST_REASONING_TOKENS is chat
                        should_persist = False
                        if item_type == "reasoning":
                            should_persist = (valves.PERSIST_REASONING_TOKENS == "conversation") # Only persist reasoning when explicitly allowed for this turn
                        elif item_type != "message":
                            should_persist = valves.PERSIST_TOOL_RESULTS # Persist all other non-message items (tool calls, web_search_call, etc.)

                        if should_persist:
                            hidden_uid_marker = persist_openai_response_items(
                                metadata.get("chat_id"),
                                metadata.get("message_id"),
                                [item],
                                openwebui_model,
                            )
                            if hidden_uid_marker:
                                self.logger.debug("Persisted item: %s", hidden_uid_marker)
                                assistant_message += hidden_uid_marker
                                await event_emitter({"type": "chat:message", "data": {"content": assistant_message}})


                        # Default empty content
                        title = f"Running `{item_name}`"
                        content = ""

                        # Prepare detailed content per item_type
                        if item_type == "function_call":
                            title = f"🛠️ Running the {item_name} tool…"
                            arguments = json.loads(item.get("arguments") or "{}")
                            args_formatted = ", ".join(f"{k}={json.dumps(v)}" for k, v in arguments.items())
                            content = wrap_code_block(f"{item_name}({args_formatted})", "python")

                        elif item_type == "web_search_call":
                            title = "🔍 Hmm, let me quickly check online…"

                            # If action type is 'search', then set title to "🔍 Searching the web for [query]"
                            action = item.get("action", {})
                            if action.get("type") == "search":
                                query = action.get("query")
                                if query:
                                    title = f"🔍 Searching the web for: `{query}`"
                                else:
                                    title = "🔍 Searching the web"

                            # If action type is 'open_page', then set title to "🔍 Opening web page [url]"
                            elif action.get("type") == "open_page":
                                title = "🔍 Opening web page…"
                                url = action.get("url")
                                if url:
                                    content = f"URL: `{url}`"

                        elif item_type == "file_search_call":
                            title = "📂 Let me skim those files…"
                        elif item_type == "image_generation_call":
                            title = "🎨 Let me create that image…"
                        elif item_type == "local_shell_call":
                            title = "💻 Let me run that command…"
                        elif item_type == "mcp_call":
                            title = "🌐 Let me query the MCP server…"
                        elif item_type == "reasoning":
                            title = None # Don't emit a title for reasoning items

                        # Emit the status with prepared title and detailed content
                        if title:
                            assistant_message = await status_indicator.add(
                                assistant_message,
                                status_title=title,
                                status_content=content,
                            )

                        continue

                    # ─── Capture final response (incl. all non-visible items like reasoning tokens for future turns)
                    if etype == "response.completed":
                        final_response = event.get("response", {})
                        body.input.extend(final_response.get("output", [])) # This includes all non-visible items (e.g. reasoning, web_search_call, tool calls, etc..) and appends to body.input so they are included in future turns (if any)
                        break

                if final_response is None:
                    raise ValueError("No final response received from OpenAI Responses API.")

                # Extract usage information from OpenAI response and pass-through to Open WebUI
                usage = final_response.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in final_response["output"] if i["type"] == "function_call"
                    )
                    total_usage = merge_usage_stats(total_usage, usage)
                    await self._emit_completion(event_emitter, content="", usage=total_usage, done=False)

                # Execute tool calls (if any), persist results (if valve enabled), and append to body.input.
                calls = [i for i in final_response["output"] if i["type"] == "function_call"]
                if calls:
                    function_outputs = await self._execute_function_calls(calls, tools)
                    if valves.PERSIST_TOOL_RESULTS:
                        hidden_uid_marker = persist_openai_response_items(
                            metadata.get("chat_id"),
                            metadata.get("message_id"),
                            function_outputs,
                            openwebui_model,
                        )
                        self.logger.debug("Persisted item: %s", hidden_uid_marker)
                        if hidden_uid_marker:
                            assistant_message += hidden_uid_marker
                            await event_emitter({"type": "chat:message", "data": {"content": assistant_message}})


                    # Add status indicator with sanitized result
                    for output in function_outputs:
                        result_text = wrap_code_block(output.get("output", ""))
                        assistant_message = await status_indicator.add(
                            assistant_message,
                            status_title="🛠️ Received tool result",
                            status_content=result_text,
                        )
                    body.input.extend(function_outputs)
                else:
                    break

        # Catch any exceptions during the streaming loop and emit an error
        except Exception as e:  # pragma: no cover - network errors
            await self._emit_error(event_emitter, f"Error: {str(e)}", show_error_message=True, show_error_log_citation=True, done=True)

        finally:
            if not status_indicator._done and status_indicator._items:
                assistant_message = await status_indicator.finish(assistant_message)

            if valves.LOG_LEVEL != "INHERIT":
                if event_emitter:
                    session_id = SessionLogger.session_id.get()
                    logs = SessionLogger.logs.get(session_id, [])
                    if logs:
                        await self._emit_citation(event_emitter, "\n".join(logs), "Logs")

            # Emit completion (middleware.py also does this so this just covers if there is a downstream error)
            await self._emit_completion(event_emitter, content="", usage=total_usage, done=True)  # There must be an empty content to avoid breaking the UI

            # Clear logs
            logs_by_msg_id.clear()
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)

            chat_id = metadata.get("chat_id")
            message_id = metadata.get("message_id")
            if chat_id and message_id and emitted_citations:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id, message_id, {"sources": emitted_citations}
                )

            # Return the final output to ensure persistence.
            return assistant_message


    async def _run_nonstreaming_loop(
        self,
        body: ResponsesBody,                                       # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_FUNCTION_CALL_LOOPS, API_KEY, etc.
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]], # Function to emit events to the front-end UI
        metadata: Dict[str, Any] = {},                              # Metadata for the request (e.g., session_id, chat_id)
        tools: Optional[Dict[str, Dict[str, Any]]] = None,          # Optional tools dictionary for function calls
    ) -> str:
        """Multi-turn conversation loop using blocking requests.

        Each iteration performs a standard POST request rather than streaming
        SSE chunks.  The returned JSON is parsed, optional tool calls are
        executed and the final text is accumulated before being returned.
        """

        openwebui_model_id = metadata.get("model", {}).get("id", "") # Full model ID, e.g. "openai_responses.gpt-4o"

        tools = tools or {}
        assistant_message = ""
        total_usage: Dict[str, Any] = {}
        reasoning_map: dict[int, str] = {}

        status_indicator = ExpandableStatusIndicator(event_emitter)
        status_indicator._done = False

        model_family = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", body.model)
        if model_family in FEATURE_SUPPORT["reasoning"]:
            assistant_message = await status_indicator.add(
                assistant_message,
                status_title="Thinking…",
                status_content=(
                    "Reading the question and building a plan to answer it. This may take a moment."
                ),
            )

        try:
            for loop_idx in range(valves.MAX_FUNCTION_CALL_LOOPS):
                response = await self.send_openai_responses_nonstreaming_request(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                )

                items = response.get("output", [])

                # Persist non-message items immediately and insert invisible markers
                for item in items:
                    item_type = item.get("type")

                    if item_type == "message":
                        for content in item.get("content", []):
                            if content.get("type") == "output_text":
                                assistant_message += content.get("text", "")

                    elif item_type == "reasoning_summary_text":
                        idx = item.get("summary_index", 0)
                        text = item.get("text", "")
                        if text:
                            reasoning_map[idx] = reasoning_map.get(idx, "") + text
                            title_match = re.findall(r"\*\*(.+?)\*\*", text)
                            title = title_match[-1].strip() if title_match else "Thinking…"
                            content = re.sub(r"\*\*(.+?)\*\*", "", text).strip()
                            assistant_message = await status_indicator.add(
                                assistant_message,
                                status_title="🧠 " + title,
                                status_content=content,
                            )

                    elif item_type == "reasoning":
                        parts = "\n\n---".join(
                            reasoning_map[i] for i in sorted(reasoning_map)
                        )
                        snippet = (
                            f'<details type="{__name__}.reasoning" done="true">\n'
                            f"<summary>Done thinking!</summary>\n{parts}</details>"
                        )
                        assistant_message += snippet
                        reasoning_map.clear()

                    else:
                        if valves.PERSIST_TOOL_RESULTS:
                            hidden_uid_marker = persist_openai_response_items(
                                metadata.get("chat_id"),
                                metadata.get("message_id"),
                                [item],
                                metadata.get("model", {}).get("id"),
                            )
                            self.logger.debug("Persisted item: %s", hidden_uid_marker)
                            assistant_message += hidden_uid_marker

                        title = f"Running `{item.get('name', 'unnamed_tool')}`"
                        content = ""

                        if item_type == "function_call":
                            title = f"🛠️ Running the {item.get('name', 'unnamed_tool')} tool…"
                            arguments = json.loads(item.get("arguments") or "{}")
                            args_formatted = ", ".join(
                                f"{k}={json.dumps(v)}" for k, v in arguments.items()
                            )
                            content = wrap_code_block(f"{item.get('name', 'unnamed_tool')}({args_formatted})", "python")
                        elif item_type == "web_search_call":
                            title = "🔍 Hmm, let me quickly check online…"
                            action = item.get("action", {})
                            if action.get("type") == "search":
                                query = action.get("query")
                                if query:
                                    title = f"🔍 Searching the web for: `{query}`"
                                else:
                                    title = "🔍 Searching the web"
                            elif action.get("type") == "open_page":
                                title = "🔍 Opening web page…"
                                url = action.get("url")
                                if url:
                                    content = f"URL: `{url}`"
                        elif item_type == "file_search_call":
                            title = "📂 Let me skim those files…"
                        elif item_type == "image_generation_call":
                            title = "🎨 Let me create that image…"
                        elif item_type == "local_shell_call":
                            title = "💻 Let me run that command…"
                        elif item_type == "mcp_call":
                            title = "🌐 Let me query the MCP server…"
                        elif item_type == "reasoning":
                            title = None

                        if title:
                            assistant_message = await status_indicator.add(
                                assistant_message,
                                status_title=title,
                                status_content=content,
                            )

                usage = response.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in items if i.get("type") == "function_call"
                    )
                    total_usage = merge_usage_stats(total_usage, usage)
                    await self._emit_completion(event_emitter, content="", usage=total_usage, done=False)

                body.input.extend(items)

                # Run tools if requested
                calls = [i for i in items if i.get("type") == "function_call"]
                if calls:
                    function_outputs = await self._execute_function_calls(calls, tools)
                    if valves.PERSIST_TOOL_RESULTS:
                        hidden_uid_marker = persist_openai_response_items(
                            metadata.get("chat_id"),
                            metadata.get("message_id"),
                            function_outputs,
                            openwebui_model_id,
                        )
                        self.logger.debug("Persisted item: %s", hidden_uid_marker)
                        assistant_message += hidden_uid_marker

                    # Add status indicator with sanitized result
                    for output in function_outputs:
                        result_text = wrap_code_block(output.get("output", ""))
                        assistant_message = await status_indicator.add(
                            assistant_message,
                            status_title="🛠️ Received tool result",
                            status_content=result_text,
                        )
                    body.input.extend(function_outputs)
                else:
                    break

            # Finalize output
            final_text = assistant_message.strip()
            if not status_indicator._done and status_indicator._items:
                final_text = await status_indicator.finish(final_text)
            return final_text

        except Exception as e:  # pragma: no cover - network errors
            await self._emit_error(
                event_emitter,
                e,
                show_error_message=True,
                show_error_log_citation=True,
                done=True,
            )
        finally:
            if not status_indicator._done and status_indicator._items:
                assistant_message = await status_indicator.finish(assistant_message)
            # Clear logs
            logs_by_msg_id.clear()
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)
    
    # 4.4 Task Model Handling
    async def _run_task_model_request(
        self,
        body: Dict[str, Any],
        valves: Pipe.Valves
    ) -> Dict[str, Any]:
        """Process a task model request via the Responses API.

        Task models (e.g. generating a chat title or tags) return their
        information as standard Responses output.  This helper performs a single
        non-streaming call and extracts the plain text from the response items.
        """

        task_body = {
            "model": body.get("model"),
            "instructions": body.get("instructions", ""),
            "input": body.get("input", ""),
            "stream": False,
        }

        response = await self.send_openai_responses_nonstreaming_request(
            task_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )

        text_parts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_parts.append(content.get("text", ""))

        message = "".join(text_parts)

        return message
      
    # 4.5 LLM HTTP Request Helpers
    async def send_openai_responses_streaming_request(
        self,
        request_body: dict[str, Any],
        api_key: str,
        base_url: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE events from the Responses endpoint as soon as they arrive.

        This low-level helper is tuned for minimal latency when streaming large
        responses.  It decodes each ``data:`` line and yields the parsed JSON
        payload immediately.
        """
        # Get or create aiohttp session (aiohttp is used for performance).
        self.session = await self._get_or_init_http_session()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"

        buf = bytearray()
        async with self.session.post(url, json=request_body, headers=headers) as resp:
            if resp.status >= 400:
                error_text = await resp.text()
                self.logger.error("OpenAI Responses API error %s: %s", resp.status, error_text)
                resp.raise_for_status()

            async for chunk in resp.content.iter_chunked(4096):
                buf.extend(chunk)
                start_idx = 0
                # Process all complete lines in the buffer
                while True:
                    newline_idx = buf.find(b"\n", start_idx)
                    if newline_idx == -1:
                        break
                    
                    line = buf[start_idx:newline_idx].strip()
                    start_idx = newline_idx + 1

                    # Skip empty lines, comment lines, or anything not starting with "data:"
                    if (not line or line.startswith(b":") or not line.startswith(b"data:")):
                        continue

                    data_part = line[5:].strip()
                    if data_part == b"[DONE]":
                        return  # End of SSE stream
                    
                    # Yield JSON-decoded data
                    yield json.loads(data_part.decode("utf-8"))

                # Remove processed data from the buffer
                if start_idx > 0:
                    del buf[:start_idx]

    async def send_openai_responses_nonstreaming_request(
        self,
        request_params: dict[str, Any],
        api_key: str,
        base_url: str,
    ) -> Dict[str, Any]:
        """Send a blocking request to the Responses API and return the JSON payload."""
        # Get or create aiohttp session (aiohttp is used for performance).
        self.session = await self._get_or_init_http_session()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"

        async with self.session.post(url, json=request_params, headers=headers) as resp:
            if resp.status >= 400:
                error_text = await resp.text()
                self.logger.error("OpenAI Responses API error %s: %s", resp.status, error_text)
                resp.raise_for_status()
            return await resp.json()
    
    async def _get_or_init_http_session(self) -> aiohttp.ClientSession:
        """Return a cached ``aiohttp.ClientSession`` instance.

        The session is created with connection pooling and sensible timeouts on
        first use and is then reused for the lifetime of the process.
        """
        # Reuse existing session if available and open
        if self.session is not None and not self.session.closed:
            self.logger.debug("Reusing existing aiohttp.ClientSession")
            return self.session

        self.logger.debug("Creating new aiohttp.ClientSession")

        # Configure TCP connector for connection pooling and DNS caching
        connector = aiohttp.TCPConnector(
            limit=50,  # Max total simultaneous connections
            limit_per_host=10,  # Max connections per host
            keepalive_timeout=75,  # Seconds to keep idle sockets open
            ttl_dns_cache=300,  # DNS cache time-to-live in seconds
        )

        # Set reasonable timeouts for connection and socket operations
        timeout = aiohttp.ClientTimeout(
            connect=30,  # Max seconds to establish connection
            sock_connect=30,  # Max seconds for socket connect
            sock_read=3600,  # Max seconds for reading from socket (1 hour)
        )

        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            json_serialize=json.dumps,
        )

        return session
    
    # 4.6 Tool Execution Logic
    @staticmethod
    async def _execute_function_calls(
        calls: list[dict],                      # raw call-items from the LLM
        tools: dict[str, dict[str, Any]],       # name → {callable, …}
    ) -> list[dict]:
        """Execute one or more tool calls and return their outputs.

        Each call specification is looked up in the ``tools`` mapping by name
        and executed concurrently.  The returned list contains synthetic
        ``function_call_output`` items suitable for feeding back into the LLM.
        """
        def _make_task(call):
            tool_cfg = tools.get(call["name"])
            if not tool_cfg:                                 # tool missing
                return asyncio.sleep(0, result="Tool not found")

            fn = tool_cfg["callable"]
            args = json.loads(call["arguments"])

            if inspect.iscoroutinefunction(fn):              # async tool
                return fn(**args)
            else:                                            # sync tool
                return asyncio.to_thread(fn, **args)

        tasks   = [_make_task(call) for call in calls]       # ← fire & forget
        results = await asyncio.gather(*tasks)               # ← runs in parallel. TODO: asyncio.gather(*tasks) cancels all tasks if one tool raises.

        return [
            {
                "type":   "function_call_output",
                "call_id": call["call_id"],
                "output":  str(result),
            }
            for call, result in zip(calls, results)
        ]

    # 4.7 Emitters (Front-end communication)
    async def _emit_error(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]],
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        show_error_log_citation: bool = False,
        done: bool = False,
    ) -> None:
        """Log an error and optionally surface it to the UI.

        When ``show_error_log_citation`` is true the function also emits the
        collected debug logs as a citation block so users can inspect what went
        wrong.
        """
        error_message = str(error_obj)  # If it's an exception, convert to string
        self.logger.error("Error: %s", error_message)

        if show_error_message and event_emitter:
            await event_emitter(
                {
                    "type": "chat:completion",
                    "data": {
                        "error": {"message": error_message},
                        "done": done,
                    },
                }
            )

            # 2) Optionally emit the citation with logs
            if show_error_log_citation:
                session_id = SessionLogger.session_id.get()
                logs = SessionLogger.logs.get(session_id, [])
                if logs:
                    await self._emit_citation(
                        event_emitter,
                        "\n".join(logs),
                        "Error Logs",
                    )
                else:
                    self.logger.warning(
                        "No debug logs found for session_id %s", session_id
                    )

    async def _emit_citation(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        document: str | list[str],
        source_name: str,
    ) -> None:
        """Send a citation block to the UI if an emitter is available.

        ``document`` may be either a single string or a list of strings.  The
        function normalizes this input and emits a ``citation`` event containing
        the text and its source metadata.
        """
        if event_emitter is None:
            return

        if isinstance(document, list):
            doc_text = "\n".join(document)
        else:
            doc_text = document

        await event_emitter(
            {
                "type": "citation",
                "data": {
                    "document": [doc_text],
                    "metadata": [
                        {
                            "date_accessed": datetime.datetime.now().isoformat(),
                            "source": source_name,
                        }
                    ],
                    "source": {"name": source_name},
                },
            }
        )

    async def _emit_completion(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        content: str | None = "",                       # always included (may be "").  UI will stall if you leave it out.
        title:   str | None = None,                     # optional title.
        usage:   dict[str, Any] | None = None,          # optional usage block
        done:    bool = True,                           # True → final frame
    ) -> None:
        """Emit a ``chat:completion`` event if an emitter is present.

        The ``done`` flag indicates whether this is the final frame for the
        request.  When ``usage`` information is provided it is forwarded as part
        of the event data.
        """
        if event_emitter is None:
            return

        # Note: Open WebUI emits a final "chat:completion" event after the stream ends, which overwrites any previously emitted completion events' content and title in the UI.
        await event_emitter(
            {
                "type": "chat:completion",
                "data": {
                    "done": done,
                    "content": content,
                    **({"title": title} if title is not None else {}),
                    **({"usage": usage} if usage is not None else {}),
                }
            }
        )

    async def _emit_status(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
    ) -> None:
        """Emit a short status update to the UI.

        ``hidden`` allows emitting a transient update that is not shown in the
        conversation transcript.
        """
        if event_emitter is None:
            return
        
        await event_emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done, "hidden": hidden},
            }
        )

    async def _emit_notification(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        """Emit a toast-style notification to the UI.

        The ``level`` argument controls the styling of the notification banner.
        """
        if event_emitter is None:
            return

        await event_emitter(
            {"type": "notification", "data": {"type": level, "content": content}}
        )

    async def _route_gpt5_auto(
        self,
        last_user_message: str,
        valves: "Pipe.Valves",
    ) -> str:
        """Placeholder GPT-5 router.

        Eventually this helper will make a non-streaming call to a low-latency
        model (e.g., ``gpt-4.1-nano``) that inspects the last user message and
        returns structured JSON indicating which GPT-5 variant to use.  The
        selected model will then handle the user's request.

        Currently, it simply returns ``"gpt-5-chat-latest"`` so ``gpt-5-auto``
        behaves as a direct alias and the router design can be iterated on
        separately.
        """
        return "gpt-5-chat-latest"

    # 4.8 Internal Static Helpers
    def _merge_valves(self, global_valves, user_valves) -> "Pipe.Valves":
        """Merge user-level valves into the global defaults.

        Any field set to ``"INHERIT"`` (case-insensitive) is ignored so the
        corresponding global value is preserved.
        """
        if not user_valves:
            return global_valves

        # Merge: update only fields not set to "INHERIT"
        update = {
            k: v
            for k, v in user_valves.model_dump().items()
            if v is not None and str(v).lower() != "inherit"
        }
        return global_valves.model_copy(update=update)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Utility Classes (Shared utilities)
# ─────────────────────────────────────────────────────────────────────────────
# Support classes used across the pipe implementation
# In-memory store for debug logs keyed by message ID
logs_by_msg_id: dict[str, list[str]] = defaultdict(list)
# Context variable tracking the current message being processed
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
class SessionLogger:
    session_id = ContextVar("session_id", default=None)
    log_level = ContextVar("log_level", default=logging.INFO)
    logs = defaultdict(lambda: deque(maxlen=2000))

    @classmethod
    def get_logger(cls, name=__name__):
        """Return a logger wired to the current ``SessionLogger`` context."""
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Single combined filter
        def filter(record):
            record.session_id = cls.session_id.get()
            return record.levelno >= cls.log_level.get()

        logger.addFilter(filter)

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s"))
        logger.addHandler(console)

        # Memory handler
        mem = logging.Handler()
        mem.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        mem.emit = lambda r: cls.logs[r.session_id].append(mem.format(r)) if r.session_id else None
        logger.addHandler(mem)

        return logger

class ExpandableStatusIndicator:
    """
    Real‑time, **expandable progress log** for chat assistants
    ========================================================

    This helper maintains **one** collapsible `<details type="status">` block at
    the *top* of the assistant’s message.  It lets you incrementally append or
    edit bullet‑style status lines while automatically re‑emitting the full
    message to the UI.

    ───────────────────────────────
    Basic example
    ───────────────────────────────
    ```python
    assistant_message = "Let's work step‑by‑step.\n"

    status = ExpandableStatusIndicator(event_emitter=__event_emitter__)

    assistant_message = await status.add(
        assistant_message, "Analyzing input"
    )
    assistant_message = await status.add(
        assistant_message, "Retrieving context", "Querying sources…"
    )
    assistant_message = await status.update_last_status(
        assistant_message, new_content="Retrieved 3 documents"
    )
    assistant_message = await status.finish(assistant_message)
    ```
    Each call *returns* the updated `assistant_message`; always keep the latest
    string for further processing or output.

    ───────────────────────────────
    Public API
    ───────────────────────────────
    ▸ `add(assistant_message, title, content=None, *, emit=True) -> str`
        Add a new top‑level bullet; if *title* matches the last bullet,
        *content* becomes a sub‑bullet instead.

    ▸ `update_last_status(assistant_message, *, new_title=None,
                          new_content=None, emit=True) -> str`
        Replace the last bullet’s title and/or its sub‑bullets.

    ▸ `finish(assistant_message, *, emit=True) -> str`
        Append “Finished in X s”, set `done="true"` and freeze the instance.
        Subsequent `add`/`update_last_status` calls raise `RuntimeError`.

    ▸ `reset()`
        Clear bullets and restart the internal timer.

    Constructor
    ───────────
    `ExpandableStatusIndicator(event_emitter=None, *, expanded=False)`

    * `event_emitter` must be an **async** callable accepting
      `{"type": "chat:message", "data": {"content": <str>}}`.
      When supplied (and `emit=True`), every status change is pushed to the UI.
    * `expanded` (default **False**) starts the details block open when true.

    Design guarantees
    ─────────────────
    • The status block is always the **first** element in the message.  
    • Only **one** status block is ever inserted/updated (identified by the
      `type="status"` attribute).  
    • Thread‑unsafe on purpose – one instance should service one coroutine.

    """

    # Regex reused for fast replacement of the existing block.
    _BLOCK_RE = re.compile(
        r"<details\s+type=\"status\".*?</details>", re.DOTALL | re.IGNORECASE
    )

    def __init__(
        self,
        event_emitter: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        self._event_emitter = event_emitter
        self._items: List[Tuple[str, List[str]]] = []
        self._started = time.perf_counter()
        self._done: bool = False

    # --------------------------------------------------------------------- #
    # Public async API                                                      #
    # --------------------------------------------------------------------- #
    async def add(
        self,
        assistant_message: str,
        status_title: str,
        status_content: Optional[str] = None,
        *,
        emit: bool = True,
    ) -> str:
        """Append a new status bullet (or extend the last one if title repeats)."""
        self._assert_not_finished("add")

        if not self._items or self._items[-1][0] != status_title:
            self._items.append((status_title, []))

        if status_content:
            self._items[-1][1].append(status_content.strip())

        return await self._render(assistant_message, emit)

    async def update_last_status(
        self,
        assistant_message: str,
        *,
        new_title: Optional[str] = None,
        new_content: Optional[str] = None,
        emit: bool = True,
    ) -> str:
        """Replace the most recent status bullet’s title and/or its content."""
        self._assert_not_finished("update_last_status")

        if not self._items:
            return await self.add(
                assistant_message, new_title or "Status", new_content, emit=emit
            )

        title, subs = self._items[-1]
        if new_title:
            title = new_title
        if new_content is not None:
            subs = [new_content.strip()]

        self._items[-1] = (title, subs)
        return await self._render(assistant_message, emit)

    async def finish(
        self,
        assistant_message: str,
        *,
        emit: bool = True,
    ) -> str:
        if self._done:
            return assistant_message
        elapsed = time.perf_counter() - self._started
        self._items.append((f"Finished in {elapsed:.1f} s", []))
        self._done = True
        return await self._render(assistant_message, emit)

    # ------------------------------------------------------------------ #
    # Rendering helpers                                                  #
    # ------------------------------------------------------------------ #
    def _assert_not_finished(self, method: str) -> None:
        if self._done:
            raise RuntimeError(
                f"Cannot call {method}(): status indicator is already finished."
            )

    async def _render(self, assistant_message: str, emit: bool) -> str:
        block = self._render_status_block()
        full_msg = (
            self._BLOCK_RE.sub(lambda _: block, assistant_message, 1)
            if self._BLOCK_RE.search(assistant_message)
            else f"{block}{assistant_message}"
        )
        if emit and self._event_emitter:
            await self._event_emitter({"type": "chat:message", "data": {"content": full_msg}})
        return full_msg

    def _render_status_block(self) -> str:
        lines: List[str] = []

        for title, subs in self._items:
            lines.append(f"- **{title}**")  # top-level bullet

            for sub in subs:
                # Indent entire sub-item by 2 spaces; prepend "- " exactly once.
                sub_lines = sub.splitlines()
                if sub_lines:
                    lines.append(f"  - {sub_lines[0]}")  # first line with dash
                    # All subsequent lines indented 4 spaces to align with markdown
                    if len(sub_lines) > 1:
                        lines.extend(textwrap.indent("\n".join(sub_lines[1:]), "    ").splitlines())

        body_md = "\n".join(lines) if lines else "_No status yet._"
        summary = self._items[-1][0] if self._items else "Working…"

        return (
            f'<details type="status" done="{str(self._done).lower()}">\n'
            f"<summary>{summary}</summary>\n\n{body_md}\n\n---</details>"
        )

    
# ─────────────────────────────────────────────────────────────────────────────
# 6. Framework Integration Helpers (Open WebUI DB operations)
# ─────────────────────────────────────────────────────────────────────────────
# Utility functions that interface with Open WebUI's data models
def persist_openai_response_items(
    chat_id: str,
    message_id: str,
    items: List[Dict[str, Any]],
    openwebui_model_id: str,
) -> str:
    """Persist items and return their wrapped marker string.

    :param chat_id: Chat identifier used to locate the conversation.
    :param message_id: Message ID the items belong to.
    :param items: Sequence of payloads to store.
    :param openwebui_model_id: Fully qualified model ID the items originate from.
    :return: Concatenated empty-link encoded item IDs for later retrieval.
    """

    if not items:
        return ""

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return ""

    pipe_root      = chat_model.chat.setdefault("openai_responses_pipe", {"__v": 3})
    items_store    = pipe_root.setdefault("items", {})
    messages_index = pipe_root.setdefault("messages_index", {})

    message_bucket = messages_index.setdefault(
        message_id,
        {"role": "assistant", "done": True, "item_ids": []},
    )

    now = int(datetime.datetime.utcnow().timestamp())
    hidden_uid_markers: List[str] = []

    for payload in items:
        item_id = generate_item_id()
        items_store[item_id] = {
            "model":      openwebui_model_id,
            "created_at": now,
            "payload":    payload,
            "message_id": message_id,
        }
        message_bucket["item_ids"].append(item_id)
        hidden_uid_marker = wrap_marker(
            create_marker(payload.get("type", "unknown"), ulid=item_id)
        )
        hidden_uid_markers.append(hidden_uid_marker)

    Chats.update_chat_by_id(chat_id, chat_model.chat)
    return "".join(hidden_uid_markers)

# ─────────────────────────────────────────────────────────────────────────────
# 7. General-Purpose Utility Functions (Data transforms & patches)
# ─────────────────────────────────────────────────────────────────────────────
# Helper functions shared by multiple parts of the pipe
def merge_usage_stats(total, new):
    """Recursively merge nested usage statistics.

    :param total: Accumulator dictionary to update.
    :param new: Newly reported usage block to merge in.
    :return: The updated ``total`` dictionary.
    """
    for k, v in new.items():
        if isinstance(v, dict):
            total[k] = merge_usage_stats(total.get(k, {}), v)
        elif isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        else:
            # Skip or explicitly set non-numeric values
            total[k] = v if v is not None else total.get(k, 0)
    return total


def wrap_code_block(text: str, language: str = "python") -> str:
    """Wrap ``text`` in a fenced Markdown code block.

    The fence length adapts to the longest backtick run within ``text``
    to avoid prematurely closing the block.
    """
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def remove_details_tags_by_type(text: str, removal_types: list[str]) -> str:
    """Strip ``<details>`` blocks matching the specified ``type`` values.

    Example::

        remove_details_tags_by_type("Hello <details type='reasoning'>stuff</details>", ["reasoning"])
        # -> "Hello "

    :param text: Source text containing optional ``<details>`` tags.
    :param removal_types: ``type`` attribute values to remove.
    :return: ``text`` with matching blocks removed.
    """
    # Safely escape the types in case they have special regex chars
    pattern_types = "|".join(map(re.escape, removal_types))
    # Example pattern: <details type="reasoning">...</details>
    pattern = rf'<details\b[^>]*\btype=["\'](?:{pattern_types})["\'][^>]*>.*?</details>'
    return re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

#####################

# Helper utilities for persistent item markers
ULID_LENGTH = 16
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_SENTINEL = "[openai_responses:v2:"
_RE = re.compile(
    rf"\[openai_responses:v2:(?P<kind>[a-z0-9_]{{2,30}}):"
    rf"(?P<ulid>[A-Z0-9]{{{ULID_LENGTH}}})(?:\?(?P<query>[^\]]+))?\]:\s*#",
    re.I,
)

def _qs(d: dict[str, str]) -> str:
    return "&".join(f"{k}={v}" for k, v in d.items()) if d else ""

def _parse_qs(q: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in q.split("&")) if q else {}


def generate_item_id() -> str:
    return ''.join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))

def create_marker(
    item_type: str,
    *,
    ulid: str | None = None,
    model_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    if not re.fullmatch(r"[a-z0-9_]{2,30}", item_type):
        raise ValueError("item_type must be 2-30 chars of [a-z0-9_]")
    meta = {**(metadata or {})}
    if model_id:
        meta["model"] = model_id
    base = f"openai_responses:v2:{item_type}:{ulid or generate_item_id()}"
    return f"{base}?{_qs(meta)}" if meta else base

def wrap_marker(marker: str) -> str:
    return f"\n[{marker}]: #\n"

def contains_marker(text: str) -> bool:
    return _SENTINEL in text

def parse_marker(marker: str) -> dict:
    if not marker.startswith("openai_responses:v2:"):
        raise ValueError("not a v2 marker")
    _, _, kind, rest = marker.split(":", 3)
    uid, _, q = rest.partition("?")
    return {"version": "v2", "item_type": kind, "ulid": uid, "metadata": _parse_qs(q)}

def extract_markers(text: str, *, parsed: bool = False) -> list:
    found = []
    for m in _RE.finditer(text):
        raw = f"openai_responses:v2:{m.group('kind')}:{m.group('ulid')}"
        if m.group("query"):
            raw += f"?{m.group('query')}"
        found.append(parse_marker(raw) if parsed else raw)
    return found

def split_text_by_markers(text: str) -> list[dict]:
    segments = []
    last = 0
    for m in _RE.finditer(text):
        if m.start() > last:
            segments.append({"type": "text", "text": text[last:m.start()]})
        raw = f"openai_responses:v2:{m.group('kind')}:{m.group('ulid')}"
        if m.group("query"):
            raw += f"?{m.group('query')}"
        segments.append({"type": "marker", "marker": raw})
        last = m.end()
    if last < len(text):
        segments.append({"type": "text", "text": text[last:]})
    return segments

def fetch_openai_response_items(
    chat_id: str,
    item_ids: List[str],
    *,
    openwebui_model_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return a mapping of ``item_id`` to its persisted payload.

    :param chat_id: Chat identifier used to look up stored items.
    :param item_ids: ULIDs previously embedded in the message text.
    :param openwebui_model_id: Only include items originating from this model.
    :return: Mapping of ULID to the stored item payload.
    """

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return {}

    items_store = chat_model.chat.get("openai_responses_pipe", {}).get("items", {})
    lookup: Dict[str, Dict[str, Any]] = {}
    for item_id in item_ids:
        item = items_store.get(item_id)
        if not item:
            continue
        # Only include previously persisted items that match the current model ID.
        # OpenAI requires this to avoid items produced by one model leaking into subsequent requests for a different model.
        # e.g., Encrypted reasoning tokens from o4-mini are not compatible with gpt-4o.
        # TODO: Do some more sophisticated filtering here, e.g. check model features and allow items that are compatible with the current model.
        if openwebui_model_id:
            if item.get("model", "") != openwebui_model_id:
                continue
        lookup[item_id] = item.get("payload", {})
    return lookup