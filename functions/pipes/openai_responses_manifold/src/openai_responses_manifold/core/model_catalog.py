"""Single source of truth for OpenAI model IDs, aliases, and capabilities."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from openai_responses_manifold.core.logging import get_logger

# =============================================================================
# Change Log
# 2025-11-20: Align model feature flags with current OpenAI docs (web search,
#             file search, image generation, and code interpreter coverage),
#             add gpt-5-pro and Codex models, adjust deep-research and chat
#             model capabilities to match Responses API model cards.
# =============================================================================

# Update MODEL_FEATURES whenever OpenAI adds or removes model capabilities.
#
# Feature flags:
# - function_calling       → Supports custom tools / function calling in Responses.
# - reasoning              → Supports `reasoning` options (reasoning models).
# - reasoning_summary      → Supports reasoning summaries / traces.
# - web_search_tool        → Built-in Web search tool in Responses.
# - file_search_tool       → Built-in File search / retrieval tool in Responses.
# - image_gen_tool         → Built-in Image generation tool in Responses.
# - code_interpreter_tool  → Built-in Code interpreter tool in Responses.
# - deep_research          → Deep research orchestration models.
# - verbosity              → Supports `text.verbosity` parameter.
MODEL_FEATURES: dict[str, set[str]] = {
    # -------------------------------------------------------------------------
    # GPT-5 family (reasoning + tools)
    # -------------------------------------------------------------------------
    "gpt-5-auto": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5.1": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5.1-pro": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5-pro": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5-mini": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    "gpt-5-nano": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "verbosity",
    },
    # Codex variants (reasoning models, tool-heavy, no verbosity param)
    "gpt-5.1-codex": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "code_interpreter_tool",
    },
    "gpt-5.1-codex-max": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "code_interpreter_tool",
    },
    "gpt-5.1-codex-mini": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "code_interpreter_tool",
    },
    "gpt-5-codex": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "code_interpreter_tool",
    },
    "codex-mini-latest": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "code_interpreter_tool",
    },
    # Chat-tuned GPT-5 models (non-reasoning, supports tools)
    "gpt-5.1-chat-latest": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "gpt-5-chat-latest": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    # -------------------------------------------------------------------------
    # GPT-4.x family
    # -------------------------------------------------------------------------
    "gpt-4.1": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "gpt-4.1-mini": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "gpt-4.1-nano": {
        "function_calling",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "gpt-4o": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "gpt-4o-mini": {
        "function_calling",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    # ChatGPT-branded 4o model (no tools / function calling in Responses)
    "chatgpt-4o-latest": set(),
    # -------------------------------------------------------------------------
    # o-series reasoning models
    # -------------------------------------------------------------------------
    "o3": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "o3-mini": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    "o3-pro": {
        "function_calling",
        "reasoning",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
    },
    "o4-mini": {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "web_search_tool",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
    },
    # -------------------------------------------------------------------------
    # Deep research models
    # -------------------------------------------------------------------------
    "o3-deep-research": {
        "reasoning",
        "reasoning_summary",
        "deep_research",
        "web_search_tool",
        "file_search_tool",
    },
    "o4-mini-deep-research": {
        "reasoning",
        "reasoning_summary",
        "deep_research",
        "web_search_tool",
        "file_search_tool",
    },
}

# Add entries to MODEL_ALIASES for any pseudo-model name users can pick.
# Each alias is a preset that points to a base model and optional default params,
# e.g. gpt-5-thinking-high -> gpt-5 with reasoning effort fixed to high.
MODEL_ALIASES: dict[str, dict[str, dict | str]] = {
    "gpt-5.1-thinking": {
        "base_model": "gpt-5.1",
        "params": {"reasoning": {"effort": "medium"}},
    },
    "gpt-5.1-thinking-minimal": {
        "base_model": "gpt-5.1",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5.1-thinking-high": {
        "base_model": "gpt-5.1",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "medium"}},
    },
    "gpt-5-thinking-minimal": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-high": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-mini": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "medium"}},
    },
    "gpt-5-thinking-mini-minimal": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-mini-high": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-nano": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "medium"}},
    },
    "gpt-5-thinking-nano-minimal": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-nano-high": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "high"}},
    },
    "o3-mini-high": {
        "base_model": "o3-mini",
        "params": {"reasoning": {"effort": "high"}},
    },
    "o4-mini-high": {
        "base_model": "o4-mini",
        "params": {"reasoning": {"effort": "high"}},
    },
}

_PREFIX = "openai_responses."
_DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
_KNOWN_IDS = frozenset({*MODEL_FEATURES.keys(), *MODEL_ALIASES.keys()})
_logger = get_logger(__name__)
_UNKNOWN_LOGGED: set[str] = set()


def normalize(model_id: str) -> str:
    """Normalize identifiers by lowercasing, trimming, and removing prefixes/dates."""

    raw = (model_id or "").strip()
    if raw.startswith(_PREFIX):
        raw = raw[len(_PREFIX) :]
    raw = raw.lower()
    if not raw:
        return ""

    # Drop trailing date suffix if present (e.g. -2025-10-06).
    no_date = _DATE_SUFFIX_RE.sub("", raw)
    if no_date in _KNOWN_IDS:
        return no_date

    # Some official IDs are like gpt-5.1-2025-11-13; if the portion
    # after the first dot matches a known ID, use that.
    dot_index = no_date.find(".")
    if dot_index != -1:
        suffix = _DATE_SUFFIX_RE.sub("", no_date[dot_index + 1 :])
        if suffix in _KNOWN_IDS:
            return suffix

    return no_date


def base_model(
    model_id: str, alias_lookup: Mapping[str, Mapping[str, str | dict]] | None = None
) -> str:
    """Return the canonical base model for a given identifier."""

    alias_map = alias_lookup or MODEL_ALIASES
    normalized = normalize(model_id)
    alias_entry = alias_map.get(normalized)
    if alias_entry:
        base = alias_entry.get("base_model")
        if isinstance(base, str):
            return normalize(base)
    return normalized


def alias_defaults(model_id: str) -> dict[str, Any]:
    """Return default parameters defined for a pseudo-model alias."""

    params = MODEL_ALIASES.get(normalize(model_id), {}).get("params")
    return deepcopy(params) if params else {}


def features(model_id: str) -> set[str]:
    """Return the capability set for the canonical base model."""

    canonical = base_model(model_id, MODEL_ALIASES)
    feature_set = MODEL_FEATURES.get(canonical)
    if feature_set is None and canonical and canonical not in _UNKNOWN_LOGGED:
        _UNKNOWN_LOGGED.add(canonical)
        _logger.warning(
            "Unknown model_id in MODEL_FEATURES: %s (canonical=%s)", model_id, canonical
        )
        return set()
    return feature_set or set()


def supports(feature: str, model_id: str) -> bool:
    """Determine whether the supplied model exposes a feature."""

    return feature in features(model_id)


__all__ = [
    "MODEL_FEATURES",
    "MODEL_ALIASES",
    "alias_defaults",
    "features",
    "supports",
    "normalize",
    "base_model",
]
