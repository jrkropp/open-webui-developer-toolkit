"""Shared pipe settings and defaults."""

from __future__ import annotations

import os
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

_PIPE_LOG_LEVELS: tuple[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], ...] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)
_default_pipe_log_level = (os.getenv("GLOBAL_LOG_LEVEL", "INFO") or "INFO").upper()
if _default_pipe_log_level not in _PIPE_LOG_LEVELS:
    _default_pipe_log_level = "INFO"
DEFAULT_PIPE_LOG_LEVEL = cast(
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], _default_pipe_log_level
)


class PipeValves(BaseModel):
    model_config = ConfigDict(extra="forbid")

    BASE_URL: str = Field(
        default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
        description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
    )
    API_KEY: str = Field(
        default=(os.getenv("OPENAI_API_KEY") or "").strip(),
        description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable (blank if unset).",
    )
    MODEL_ID: str = Field(
        default="gpt-5-auto, gpt-5-chat-latest, gpt-5-thinking, gpt-5-thinking-high, gpt-5-thinking-minimal, gpt-4.1-nano, chatgpt-4o-latest, o3, gpt-4o",
        description=(
            "Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. "
            "Supports all official OpenAI model IDs and pseudo IDs (see README.md for full list)."
        ),
    )
    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"] = Field(
        default="disabled",
        description="REQUIRES VERIFIED OPENAI ORG. Visible reasoning summary (auto | concise | detailed | disabled). Works on gpt-5, o3, o4-mini; ignored otherwise. Docs: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
    )
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"] = Field(
        default="disabled",
        description=(
            "REQUIRES VERIFIED OPENAI ORG. If `disabled` (default) = never request encrypted "
            "reasoning tokens; if `response` = request encrypted reasoning tokens for this response "
            "only (not reused across turns); if `conversation` = also persist encrypted reasoning "
            "items for future turns (reuse not yet wired in)."
        ),
    )
    PERSIST_TOOL_RESULTS: bool = Field(
        default=True,
        description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
    )
    PARALLEL_TOOL_CALLS: bool = Field(
        default=True,
        description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
    )
    ENABLE_STRICT_TOOL_CALLING: bool = Field(
        default=True,
        description=(
            "When True, converts Open WebUI registry tools to strict JSON Schema for OpenAI tools, "
            "enforcing explicit types, required fields, and disallowing additionalProperties."
        ),
    )
    MAX_TOOL_CALLS: int | None = Field(
        default=None,
        description=(
            "Maximum number of individual tool or function calls the model can make "
            "within a single response. Applies to the total number of calls across "
            "all built-in tools. Further tool-call attempts beyond this limit will be ignored."
        ),
    )
    MAX_FUNCTION_CALL_LOOPS: int = Field(
        default=10,
        description=(
            "Maximum number of full execution cycles (loops) allowed per request. "
            "Each loop involves the model generating one or more function/tool calls, "
            "executing all requested functions, and feeding the results back into the model. "
            "Looping stops when this limit is reached or when the model no longer requests "
            "additional tool or function calls."
        ),
    )
    ENABLE_WEB_SEARCH_TOOL: bool = Field(
        default=False,
        description="Enable OpenAI's built-in 'web_search' tool when supported. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
    )
    WEB_SEARCH_USER_LOCATION: str | None = Field(
        default=None,
        description='User location for web search context. Leave blank to disable. Must be in valid JSON format according to OpenAI spec.  E.g., {"type": "approximate","country": "US","city": "San Francisco","region": "CA"}.',
    )
    WEB_SEARCH_ALLOWED_DOMAINS: str | None = Field(
        default=None,
        description=(
            "Comma-separated or JSON array of domains for web_search filters.allowed_domains. "
            "Per OpenAI docs, omit http/https (e.g., openai.com). Applies to Responses API only."
        ),
    )
    WEB_SEARCH_EXTERNAL_WEB_ACCESS: bool = Field(
        default=True,
        description=(
            "When False, sets web_search.external_web_access=false to use cached/indexed results "
            "instead of live internet access."
        ),
    )
    WEB_SEARCH_INCLUDE_SOURCES: bool = Field(
        default=True,
        description=(
            "Automatically request web_search_call.action.sources when a web_search tool is present, "
            "surfacing the full list of consulted URLs alongside inline citations."
        ),
    )
    REMOTE_MCP_SERVERS_JSON: str | None = Field(
        default=None,
        description=(
            "[EXPERIMENTAL] A JSON-encoded list (or single JSON object) defining one or more "
            "remote MCP servers to be automatically attached to each request. This can be useful "
            "for globally enabling tools across all chats."
        ),
    )
    TRUNCATION: Literal["auto", "disabled"] = Field(
        default="auto",
        description="OpenAI truncation strategy. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
    )
    PROMPT_CACHE_KEY: Literal["id", "email"] = Field(
        default="id",
        description="Controls which user identifier is sent in the 'user' parameter to OpenAI.",
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default=DEFAULT_PIPE_LOG_LEVEL,
        description="Select logging level. Recommend INFO or WARNING for production use.",
    )


class UserValves(BaseModel):
    """
    User-level overrides. Currently only LOG_LEVEL is honored; all other settings are pipe-global.
    """

    model_config = ConfigDict(extra="forbid")

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"] = Field(
        default="INHERIT",
        description="Select logging level. 'INHERIT' uses the pipe default.",
    )
