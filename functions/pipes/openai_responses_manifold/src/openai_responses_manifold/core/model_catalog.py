"""Model catalog helpers for the OpenAI Responses manifold.

This module centralizes model normalization, alias defaults, and
capability flags so other layers can stay agnostic of naming quirks.
See ``docs/routing_and_model_catalog.md`` for the authoritative
behavioral contract.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Mapping

_PREFIX = "openai_responses."
_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")

# Base model → feature flags. Keep in sync with docs.
_SPECS: dict[str, set[str]] = {
    "gpt-5.1-chat-latest": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "verbosity",
    },
    "gpt-5.1": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "verbosity",
    },
    "gpt-5": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "verbosity",
    },
    "gpt-5-mini": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "verbosity",
    },
    "gpt-4o": {
        "function_calling",
        "web_search_tool",
    },
    "chatgpt-4o-latest": set(),
}

# Alias / pseudo ID → base model + default params overlay.
_ALIASES: dict[str, dict[str, object]] = {
    # Reasoning-flavored GPT-5.
    "gpt-5-thinking": {"base_model": "gpt-5"},
    "gpt-5-thinking-high": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-minimal": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "minimal"}},
    },

    # Reasoning-flavored GPT-5 Mini.
    "gpt-5-thinking-mini": {"base_model": "gpt-5-mini"},
    "gpt-5-thinking-mini-high": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "high"}},
    },

    # Optional 5.1-style aliases.
    "gpt-5.1-thinking": {"base_model": "gpt-5.1-chat-latest"},
    "gpt-5.1-thinking-high": {
        "base_model": "gpt-5.1-chat-latest",
        "params": {"reasoning": {"effort": "high"}},
    },
}


def normalize(model_id: str) -> str:
    """Normalize model identifiers.

    * Trim whitespace and lower-case.
    * Strip the manifold prefix (``openai_responses.``) if present.
    * Drop trailing date suffixes (``-YYYY-MM-DD``).
    """

    normalized = (model_id or "").strip()
    if normalized.startswith(_PREFIX):
        normalized = normalized[len(_PREFIX) :]
    normalized = _DATE_RE.sub("", normalized)
    return normalized.lower()


def base_model(
    model_id: str, alias_lookup: Mapping[str, Mapping[str, object]] | None = None
) -> str:
    """Return the canonical base model for a given identifier."""

    normalized = normalize(model_id)
    alias_entry = (alias_lookup or _ALIASES).get(normalized)
    if alias_entry:
        base = alias_entry.get("base_model")
        if isinstance(base, str):
            return normalize(base)
    return normalized


def alias_defaults(model_id: str) -> dict:
    """Return default parameters defined for a pseudo-model alias."""

    params = _ALIASES.get(normalize(model_id), {}).get("params")
    return deepcopy(params) if params else {}


def features(model_id: str) -> set[str]:
    """Return the capability set for the canonical base model."""

    return _SPECS.get(base_model(model_id), set())


def supports(feature: str, model_id: str) -> bool:
    """Determine whether the supplied model exposes a feature."""

    return feature in features(model_id)


__all__ = [
    "alias_defaults",
    "base_model",
    "features",
    "normalize",
    "supports",
]
