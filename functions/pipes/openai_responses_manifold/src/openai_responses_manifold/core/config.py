"""Configuration models for the OpenAI Responses manifold.

This module defines the pipe-level and per-user valve schemas along
with the runtime configuration merged from both sources. See
``docs/config_and_valves.md`` for field semantics.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class PipeValves(BaseModel):
    """Pipe-level configuration shared by all users."""

    BASE_URL: str = "https://api.openai.com/v1"
    API_KEY: str = ""

    MODEL_ID: str = "gpt-5.1-chat-latest"

    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"] = "disabled"
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"] = "disabled"

    PERSIST_TOOL_RESULTS: bool = True
    PARALLEL_TOOL_CALLS: bool = True
    ENABLE_STRICT_TOOL_CALLING: bool = True
    MAX_TOOL_CALLS: Optional[int] = None
    MAX_FUNCTION_CALL_LOOPS: int = 10

    ENABLE_WEB_SEARCH_TOOL: bool = False
    WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = "medium"
    WEB_SEARCH_USER_LOCATION: Optional[str] = None

    REMOTE_MCP_SERVERS_JSON: Optional[str] = None

    TRUNCATION: Literal["auto", "disabled"] = "auto"

    PROMPT_CACHE_KEY: Literal["id", "email"] = "id"

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _normalize_pipe_log_level(cls, value: str) -> str:
        return value.upper()


class UserValves(BaseModel):
    """Per-user valve overrides."""

    LOG_LEVEL: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
        "INHERIT",
    ] = "INHERIT"

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _normalize_user_log_level(cls, value: str) -> str:
        return value.upper()


class RuntimeConfig(BaseModel):
    """Effective configuration for a single turn."""

    BASE_URL: str
    API_KEY: str

    MODEL_ID: str

    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"]
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"]

    PERSIST_TOOL_RESULTS: bool
    PARALLEL_TOOL_CALLS: bool
    ENABLE_STRICT_TOOL_CALLING: bool
    MAX_TOOL_CALLS: Optional[int]
    MAX_FUNCTION_CALL_LOOPS: int

    ENABLE_WEB_SEARCH_TOOL: bool
    WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None]
    WEB_SEARCH_USER_LOCATION: Optional[str]

    REMOTE_MCP_SERVERS_JSON: Optional[str]

    TRUNCATION: Literal["auto", "disabled"]

    PROMPT_CACHE_KEY: Literal["id", "email"]

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def merge_valves(pipe_valves: PipeValves, user_valves: UserValves) -> RuntimeConfig:
    """Merge pipe-level and user valves into a runtime config.

    User valves override pipe valves when they specify a concrete value.
    The only override today is ``LOG_LEVEL``; when it is set to
    ``"INHERIT"`` (case-insensitive) the pipe-level ``LOG_LEVEL`` is
    preserved.
    """

    base_config = pipe_valves.model_dump()
    user_overrides = user_valves.model_dump()

    user_log_level = user_overrides.get("LOG_LEVEL")
    if isinstance(user_log_level, str) and user_log_level.upper() != "INHERIT":
        base_config["LOG_LEVEL"] = user_log_level.upper()

    return RuntimeConfig(**base_config)


__all__ = ["PipeValves", "UserValves", "RuntimeConfig", "merge_valves"]
