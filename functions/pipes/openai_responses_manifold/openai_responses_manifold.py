"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
required_open_webui_version: 0.6.3
version: 0.8.14
license: MIT
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 1. Imports
# ─────────────────────────────────────────────────────────────────────────────
# Standard library, third-party, and Open WebUI imports
# Standard library imports
import asyncio
import datetime
import inspect
from io import StringIO
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
    "web_search_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"}, # OpenAI's built-in web search tool.
    "image_gen_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o3-pro"}, # OpenAI's built-in image generation tool.
    "function_calling": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o4-mini", "o3-mini", "o3-pro"}, # OpenAI's native function calling support.
    "reasoning": {"o3", "o4-mini", "o3-mini","o3-pro"}, # OpenAI's reasoning models.
    "reasoning_summary": {"o3", "o4-mini", "o4-mini-high", "o3-mini", "o3-mini-high", "o3-pro"}, # OpenAI's reasoning summary feature.  May require OpenAI org verification before use.
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
        """Normalize model: strip 'openai_responses.' prefix and map '-high' pseudo-models."""
        
        # Strip prefix if present
        self.model = self.model.removeprefix("openai_responses.")

        # Normalize pseudo-model IDs
        if self.model in {"o3-mini-high", "o4-mini-high"}:
            self.model = self.model.removesuffix("-high")
            self.reasoning_effort = "high"

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
    tool_choice: Optional[Literal["none", "auto", "required"]] = None
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
        Canonicalise any mixture of tool specs to the OpenAI Responses‑API list.

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

            # b) Chat‑Completions wrapper
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

        # 2. strict‑mode hardening for the bits we just converted ----------
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

    @staticmethod
    def transform_messages_to_input(
        messages: List[Dict[str, Any]],
        chat_id: Optional[str] = None,
        openwebui_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build an OpenAI Responses-API `input` array from Open WebUI-style messages.

        If `chat_id` and `openwebui_model_id` is provided AND messages contain empty-link
        encoded item references, the function looks up the persisted items from database
        and embeds them in the correct order.

        Returns
        -------
        List[dict] : The fully-formed `input` list for the OpenAI Responses API.
        """

        if (chat_id is None) != (openwebui_model_id is None):
            raise ValueError("If either 'chat_id' or 'openwebui_model_id' is provided, both must be specified.")

        required_item_ids: set[str] = set()

        # Gather all markers from assistant messages (if chat_id is provided)
        if chat_id:
            for m in messages:
                if (
                    m.get("role") == "assistant"
                    and m.get("content")
                    and contains_marker(m["content"])
                ):
                    for mk in extract_markers(m["content"], parsed=True):
                        required_item_ids.add(mk["ulid"])

        # Fetch persisted items if chat_id is provided and there are encoded item IDs
        items_lookup: dict[str, dict] = {}
        if chat_id and required_item_ids:
            items_lookup = fetch_openai_response_items(
                chat_id,
                list(required_item_ids),
                openwebui_model_id=openwebui_model_id,
            )

        # Build the OpenAI input array
        openai_input: list[dict] = []
        for msg in messages:
            role = msg.get("role", "assistant")
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
                    "type": "message",
                    "role": "user",
                    "content": [
                        block_transform.get(block.get("type"), lambda b: b)(block)
                        for block in content_blocks if block
                    ],
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
                        if item:
                            openai_input.append(item)
                        else:
                            logging.warning(f"Missing persisted item for ID: {mk['ulid']}")
                    elif segment["type"] == "text" and segment["text"].strip():
                        openai_input.append({
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": segment["text"].strip()}]
                        })
            else:
                # Plain assistant text (no encoded IDs detected)
                if content:
                    openai_input.append(
                        {
                            "type": "message",
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
        BASE_URL: str = Field(
            default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )
        API_KEY: str = Field(
            default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )
        MODEL_ID: str = Field(
            default="gpt-4.1, gpt-4o",
            description="Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. Supports the pseudo models 'o3-mini-high' and 'o4-mini-high', which map to 'o3-mini' and 'o4-mini' with reasoning effort forced to high.",
        )
        ENABLE_REASONING_SUMMARY: Literal["auto", "concise", "detailed", None] = Field(
            default=None,
            description="Reasoning summary style for o-series models (supported by: o3, o4-mini). Ignored for others. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
        )
        ENABLE_AUTO_WEB_SEARCH_TOOL: bool = Field(
            default=False,
            description="Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini).  NOTE: This appears to disable parallel tool calling. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
        )
        SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_AUTO_WEB_SEARCH_TOOL=True.",
        )
        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
        )
        TRUNCATION: Literal["auto", "disabled"] = Field(
            default="auto",
            description="Truncation strategy for model responses. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
        )
        MAX_TOOL_CALL_LOOPS: int = Field(
            default=5,
            description="Maximum number of tool calls the model can make in a single request. This is a hard stop safety limit to prevent infinite loops. Defaults to 5.",
        )
        PERSIST_TOOL_RESULTS: bool = Field(
            default=True,
            description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
        )
        MCP: Optional[str] = Field(
            default=None,
            description=(
                "\U0001f9ea Experimental: JSON describing one or more MCP servers to "
                "append to every request's tools array. Format may change."
            ),
        )
        USER_ID_FIELD: Literal["id", "email"] = Field(
            default="id",
            description=(
                "Controls which user identifier is sent in the 'user' parameter to OpenAI. "
                "Passing a unique identifier enables OpenAI response caching (improves speed and reduces cost). "
                "Choose 'id' to use the OpenWebUI user ID (privacy-friendly), or 'email' to use the user's email address."
            ),
        )
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
    ) -> AsyncGenerator[str, None] | str | None:
        """Process a user request and return either a stream or final text.

        When ``body['stream']`` is ``True`` the method yields deltas from
        ``_run_streaming_loop``.  Otherwise it falls back to
        ``_run_nonstreaming_loop`` and returns the aggregated response.
        """
        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        openwebui_model_id = __metadata__.get("model", {}).get("id", "") # Full model ID, e.g. "openai_responses.gpt-4o"
        user_identifier = __user__[valves.USER_ID_FIELD]  # Use 'id' or 'email' as configured
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
        )

        # Detect if task model (generate title, generate tags, etc.), handle it separately
        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self._run_task_model_request(responses_body.model_dump(), valves) # Placeholder for task handling logic
        
        # Transform tools from __tools__ to OpenAI Responses API format.
        # TODO: Also transform __tools__ and merge them into responses_body.tools
        if __tools__:
            responses_body.tools = ResponsesBody.transform_tools(
                tools = __tools__,
                strict = True
            )

        # Add web_search tool, if supported and enabled.
        if responses_body.model in FEATURE_SUPPORT["web_search_tool"] and (valves.ENABLE_AUTO_WEB_SEARCH_TOOL or features.get("web_search", False)):
            responses_body.tools = responses_body.tools or []
            responses_body.tools.append({
                "type": "web_search",
                "search_context_size": valves.SEARCH_CONTEXT_SIZE,

                # Temp hardcode until I implement a more elegant way to handle this.
                "user_location": {
                    "type": "approximate",
                    "country": "CA",
                    "city": "Langley",
                    "region": "BC",
                }
            })

        # Experimental MCP tool support
        if valves.MCP:
            responses_body.tools = responses_body.tools or []
            try:
                mcp_defs = json.loads(valves.MCP)
                if isinstance(mcp_defs, dict):
                    mcp_defs = [mcp_defs]
                for spec in mcp_defs:
                    if isinstance(spec, dict):
                        tool = {"type": "mcp", **spec}
                        responses_body.tools.append(tool)
            except Exception as e:  # pragma: no cover - malformed config
                self.logger.error("Invalid MCP valve: %s", e)

        # Check if tools are enabled but native function calling is disabled
        # If so, update the OpenWebUI model parameter to enable native function calling for future requests.
        if __tools__ and __metadata__.get("function_calling") != "native":
            supports_function_calling = responses_body.model in FEATURE_SUPPORT["function_calling"]

            if supports_function_calling:
                await self._emit_notification(
                    __event_emitter__,
                    content=f"Enabling native function calling for model: {responses_body.model}. Please re-run your query.",
                    level="info"
                )
                update_openwebui_model_param(openwebui_model_id, "function_calling", "native")
            else:
                await self._emit_error(
                    __event_emitter__,
                    f"The selected model '{responses_body.model}' does not support tools. "
                    f"Disable tools or choose a supported model (e.g., {', '.join(FEATURE_SUPPORT['function_calling'])})."
                )
                return
            
        # Enable reasoning summary, if supported and enabled
        if responses_body.model in FEATURE_SUPPORT["reasoning_summary"] and valves.ENABLE_REASONING_SUMMARY:
            responses_body.reasoning = responses_body.reasoning or {}
            responses_body.reasoning["summary"] = valves.ENABLE_REASONING_SUMMARY

        # Enable persistence of encrypted reasoning tokens, if supported and store=False
        # TODO make this configurable via valves since some orgs might not be approved for encrypted content
        # Note storing encrypted contents is only supported when store = False
        if responses_body.model in FEATURE_SUPPORT["reasoning"] and responses_body.store is False:
            responses_body.include = responses_body.include or []
            responses_body.include.append("reasoning.encrypted_content")

        # Log the transformed request body
        self.logger.debug("Transformed ResponsesBody: %s", json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
            
        # Send to OpenAI Responses API
        if responses_body.stream:
            # Return async generator for partial text
            return self._run_streaming_loop(responses_body, valves, __event_emitter__, __metadata__, __tools__)
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
    ) -> AsyncGenerator[str, None]:
        """Stream a conversation loop while maintaining Markdown integrity."""

        tools = tools or {}
        openwebui_model = metadata.get("model", {}).get("id", "")
        reasoning_map: dict[int, str] = {}
        final_output = StringIO()
        total_usage: dict[str, Any] = {}
        status_emitted = False

        if body.model in FEATURE_SUPPORT["reasoning"]:
            snippet = (
                f'<details type="{__name__}.reasoning" done="false">\n'
                "<summary>🧠Thinking…</summary>\nHmm… just a moment while I gather my thoughts…"
                "</details>"
            )
            if event_emitter:
                await event_emitter({"type": "chat:completion", "data": {"content": snippet}})

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
                final_response: dict[str, Any] | None = None
                async for event in self.send_openai_responses_streaming_request(
                    body.model_dump(exclude_none=True),
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                ):
                    etype = event.get("type")

                    if etype == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            final_output.write(delta)
                            yield delta
                        continue

                    if etype == "response.reasoning_summary_text.delta":
                        idx = event.get("summary_index", 0)
                        delta = event.get("delta", "")
                        if delta:
                            reasoning_map[idx] = reasoning_map.get(idx, "") + delta
                            combined = "\n\n --- \n\n".join(
                                reasoning_map[i] for i in sorted(reasoning_map)
                            )
                            titles = re.findall(r"\*\*(.+?)\*\*", combined)
                            latest = titles[-1].strip() if titles else "Thinking..."
                            snippet = (
                                f"<details type=\"{__name__}.reasoning\" done=\"false\">\n"
                                f"<summary>🧠{latest}</summary>\n"
                                f"{combined}\n</details>"
                            )
                            if event_emitter:
                                await event_emitter(
                                    {"type": "chat:completion", "data": {"content": snippet}}
                                )
                            yield ""
                        continue

                    # ─── when a tool STARTS ──────────────────────────────────────────────
                    # Write status emitting for tool start
                    if etype == "response.output_item.added":
                        item       = event.get("item", {})
                        item_type  = item.get("type", "")

                        # 1️⃣ map each type to a plain string template
                        started: dict[str, str] = {
                            "web_search_call"       : "🔍 Hmm, let me quickly check online…",
                            "function_call"         : "🛠️ Running the {fn} tool…",
                            "file_search_call"      : "📂 Let me skim those files…",
                            "image_generation_call" : "🎨 Let me create that image…",
                            "local_shell_call"      : "💻 Let me run that command…",
                        }

                        template = started.get(item_type)
                        if template:
                            # 2️⃣ Plug the function name in when it exists (ignored for other templates)
                            description = template.format(fn=item.get("name", "a tool"))

                            # 3️⃣ Emit the live-status message
                            await self._emit_status(
                                event_emitter,
                                description=description,
                                done=False,
                            )
                            status_emitted = True
                            
                        yield ""  # Yield empty string to keep the stream alive
                        continue # Continue to the next event

                    # ─── when a tool FINISHES ──────────────────────────────────────────────
                    if etype == "response.output_item.done":
                        item = event.get("item", {})
                        item_type = item.get("type", "")

                        if item_type == "reasoning":
                            parts = (
                                "\n\n --- \n\n".join(reasoning_map[i] for i in sorted(reasoning_map))
                                if reasoning_map else "Done thinking!" # TODO: handle empty reasoning case more intelligently
                            )
                            snippet = (
                                f'<details type="{__name__}.reasoning" done="true">\n'
                                f"<summary>Done thinking!</summary>\n{parts}</details>"
                            )
                            yield snippet
                            reasoning_map.clear()
                        else:
                            yield "" # Yield empty string to keep the stream alive

                        # persist the item if it is not a message (function_call, reasoning, etc.)
                        if valves.PERSIST_TOOL_RESULTS and item_type != "message":
                            hidden_uid_marker = persist_openai_response_items(
                                metadata.get("chat_id"),
                                metadata.get("message_id"),
                                [item],
                                openwebui_model,
                            )
                            if hidden_uid_marker:
                                yield hidden_uid_marker

                        continue # Continue to the next event

                    if etype == "response.completed":
                        final_response = event.get("response", {})
                        body.input.extend(final_response.get("output", []))
                        break

                if final_response is None:
                    raise ValueError("No final response received from OpenAI Responses API.")

                usage = final_response.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in final_response["output"] if i["type"] == "function_call"
                    )
                    total_usage = merge_usage_stats(total_usage, usage)
                    await self._emit_completion(event_emitter, content="", usage=total_usage, done=False)

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
                        if hidden_uid_marker:
                            yield hidden_uid_marker
                    body.input.extend(function_outputs)
                else:
                    break

        # Catch any exceptions during the streaming loop and emit an error
        except Exception as e:  # pragma: no cover - network errors
            await self._emit_error(event_emitter, f"Error: {str(e)}", show_error_message=True, show_error_log_citation=True, done=True)
            yield "" # Yield empty string to keep the stream alive

        finally:
            if status_emitted:
                # Emit final status to indicate completion
                await self._emit_status(
                    event_emitter,
                    description="",
                    done=True,
                    hidden=False,
                )
                status_emitted = False

            if valves.LOG_LEVEL != "INHERIT":
                if event_emitter:
                    session_id = SessionLogger.session_id.get()
                    logs = SessionLogger.logs.get(session_id, [])
                    if logs:
                        await self._emit_citation(
                            event_emitter,
                            "\n".join(logs),
                            "Logs",
                        )

            # Emit completion (middleware.py also does this so this just covers if there is a downstream error)
            await self._emit_completion(event_emitter, content="", usage=total_usage, done=True) # There must be an empty content to avoid breaking the UI

            # Clear logs
            logs_by_msg_id.clear()
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)

    async def _run_nonstreaming_loop(
        self,
        body: ResponsesBody,                                       # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_TOOL_CALL_LOOPS, API_KEY, etc.
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
        final_output = StringIO()
        total_usage: Dict[str, Any] = {}
        reasoning_map: dict[int, str] = {}

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
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
                                final_output.write(content.get("text", ""))

                    elif item_type == "reasoning_summary_text":
                        idx = item.get("summary_index", 0)
                        text = item.get("text", "")
                        if text:
                            reasoning_map[idx] = reasoning_map.get(idx, "") + text

                    elif item_type == "reasoning":
                        parts = "\n\n --- \n\n".join(
                            reasoning_map[i] for i in sorted(reasoning_map)
                        )
                        snippet = (
                            f'<details type="{__name__}.reasoning" done="true">\n'
                            f"<summary>Done thinking!</summary>\n{parts}</details>"
                        )
                        final_output.write(snippet)
                        reasoning_map.clear()
                        if valves.PERSIST_TOOL_RESULTS:
                            hidden_uid_marker = persist_openai_response_items(
                                metadata.get("chat_id"),
                                metadata.get("message_id"),
                                [item],
                                metadata.get("model", {}).get("id"),
                            )
                            final_output.write(hidden_uid_marker)

                    else:
                        if valves.PERSIST_TOOL_RESULTS:
                            hidden_uid_marker = persist_openai_response_items(
                                metadata.get("chat_id"),
                                metadata.get("message_id"),
                                [item],
                                metadata.get("model", {}).get("id"),
                            )
                            final_output.write(hidden_uid_marker)

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
                    fn_outputs = await self._execute_function_calls(calls, tools)
                    if valves.PERSIST_TOOL_RESULTS:
                        hidden_uid_marker = persist_openai_response_items(
                            metadata.get("chat_id"),
                            metadata.get("message_id"),
                            fn_outputs,
                            openwebui_model_id,
                        )
                        final_output.write(hidden_uid_marker)

                    body.input.extend(fn_outputs)
                else:
                    break

            # Finalize output
            final_text = final_output.getvalue().strip()
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
class SessionLogger:
    session_id = ContextVar("session_id", default=None)
    log_level = ContextVar("log_level", default=logging.INFO)
    logs = defaultdict(lambda: deque(maxlen=1000))

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

# In-memory store for debug logs keyed by message ID
logs_by_msg_id: dict[str, list[str]] = defaultdict(list)
# Context variable tracking the current message being processed
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


    
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
            create_marker(payload.get("type", "unknown"), ulid=item_id, model_id=openwebui_model_id)
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

def update_openwebui_model_param(openwebui_model_id: str, field: str, value: Any):
    """Update a model's parameter when the stored value differs.

    :param openwebui_model_id: Identifier of the model to update.
    :param field: Parameter field name to modify.
    :param value: New value to store in ``field``.
    :return: ``None``
    """
    model = Models.get_model_by_id(openwebui_model_id)
    if not model:
        return

    form_data = model.model_dump()
    form_data["params"] = dict(model.params or {})
    if form_data["params"].get(field) == value:
        return

    form_data["params"][field] = value

    form = ModelForm(**form_data)
    Models.update_model_by_id(openwebui_model_id, form)

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

_SENTINEL = "[](openai_responses:"
_RE = re.compile(
    r"\[\]\(openai_responses:v1:(?P<kind>[a-z0-9_]{2,30}):"
    r"(?P<ulid>[A-Z0-9]{26})(?:\?(?P<query>[^)]+))?\)",
    re.I,
)

ULID_LENGTH = 26
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def _ulid() -> str:
    ts = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rd = secrets.randbits(80)
    return "".join(CROCKFORD_ALPHABET[(ts >> i) & 31] for i in range(45, -1, -5)) + \
        "".join(CROCKFORD_ALPHABET[(rd >> i) & 31] for i in range(75, -1, -5))

def _qs(d: dict[str, str]) -> str:
    return "&".join(f"{k}={v}" for k, v in d.items()) if d else ""

def _parse_qs(q: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in q.split("&")) if q else {}

def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(CROCKFORD_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))

def generate_item_id() -> str:
    ts_ms = int(datetime.datetime.utcnow().timestamp() * 1000)
    rd = int.from_bytes(os.urandom(10), "big")
    return _encode_base32(ts_ms, 10) + _encode_base32(rd, 16)

def create_marker(
    item_type: str,
    *,
    ulid: str | None = None,
    model_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    if not re.fullmatch(r"[a-z0-9_]{2,30}", item_type):
        raise ValueError("item_type must be 2–30 chars of [a-z0-9_]")
    meta = {**(metadata or {})}
    if model_id:
        meta["model"] = model_id
    base = f"openai_responses:v1:{item_type}:{ulid or _ulid()}"
    return f"{base}?{_qs(meta)}" if meta else base

def wrap_marker(marker: str) -> str:
    return f"\n\n[]({marker})\n\n"

def contains_marker(text: str) -> bool:
    return _SENTINEL in text

def parse_marker(marker: str) -> dict:
    if not marker.startswith("openai_responses:v1:"):
        raise ValueError("not a v1 marker")
    _, _, kind, rest = marker.split(":", 3)
    uid, _, q = rest.partition("?")
    return {"version": "v1", "item_type": kind, "ulid": uid, "metadata": _parse_qs(q)}

def extract_markers(text: str, *, parsed: bool = False) -> list:
    found = []
    for m in _RE.finditer(text):
        raw = f"openai_responses:v1:{m.group('kind')}:{m.group('ulid')}"
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
        raw = f"openai_responses:v1:{m.group('kind')}:{m.group('ulid')}"
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