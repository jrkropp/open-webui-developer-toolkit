"""Single source of truth for OpenAI model IDs, aliases, and capabilities."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

EMPTY_FEATURES: frozenset[str] = frozenset()

# Update MODEL_FEATURES whenever OpenAI adds or removes model capabilities.
MODEL_FEATURES: dict[str, frozenset[str]] = {
    "gpt-5-auto": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool", "image_gen_tool", "verbosity"}),
    "gpt-5.1": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool", "image_gen_tool", "verbosity"}),
    "gpt-5": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool", "image_gen_tool", "verbosity"}),
    "gpt-5-mini": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool", "image_gen_tool", "verbosity"}),
    "gpt-5-nano": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool", "image_gen_tool", "verbosity"}),
    "gpt-4.1": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-nano": frozenset({"function_calling", "image_gen_tool"}),
    "gpt-4o": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4o-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "o3": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-mini": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-pro": frozenset({"function_calling", "reasoning"}),
    "o4-mini": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool"}),
    "o3-deep-research": frozenset({"function_calling", "reasoning", "reasoning_summary", "deep_research"}),
    "o4-mini-deep-research": frozenset({"function_calling", "reasoning", "reasoning_summary", "deep_research"}),
    "gpt-5.1-chat-latest": frozenset({"function_calling", "web_search_tool"}),
    "gpt-5-chat-latest": frozenset({"function_calling", "web_search_tool"}),
    "chatgpt-4o-latest": EMPTY_FEATURES,
}

# Add entries to MODEL_ALIASES for any pseudo-model name users can pick.
# Each alias is a preset that points to a base model and optional default params,
# e.g. gpt-5-thinking-high -> gpt-5 with reasoning effort fixed to high.
MODEL_ALIASES: dict[str, dict[str, dict | str]] = {
    "gpt-5.1-thinking": {"base_model": "gpt-5.1", "params": {"reasoning": {"effort": "medium"}}},
    "gpt-5.1-thinking-minimal": {"base_model": "gpt-5.1", "params": {"reasoning": {"effort": "minimal"}}},
    "gpt-5.1-thinking-high": {"base_model": "gpt-5.1", "params": {"reasoning": {"effort": "high"}}},
    "gpt-5-thinking": {"base_model": "gpt-5", "params": {"reasoning": {"effort": "medium"}}},
    "gpt-5-thinking-minimal": {"base_model": "gpt-5", "params": {"reasoning": {"effort": "minimal"}}},
    "gpt-5-thinking-high": {"base_model": "gpt-5", "params": {"reasoning": {"effort": "high"}}},
    "gpt-5-thinking-mini": {"base_model": "gpt-5-mini", "params": {"reasoning": {"effort": "medium"}}},
    "gpt-5-thinking-mini-minimal": {"base_model": "gpt-5-mini", "params": {"reasoning": {"effort": "minimal"}}},
    "gpt-5-thinking-mini-high": {"base_model": "gpt-5-mini", "params": {"reasoning": {"effort": "high"}}},
    "gpt-5-thinking-nano": {"base_model": "gpt-5-nano", "params": {"reasoning": {"effort": "medium"}}},
    "gpt-5-thinking-nano-minimal": {"base_model": "gpt-5-nano", "params": {"reasoning": {"effort": "minimal"}}},
    "gpt-5-thinking-nano-high": {"base_model": "gpt-5-nano", "params": {"reasoning": {"effort": "high"}}},
    "o3-mini-high": {"base_model": "o3-mini", "params": {"reasoning": {"effort": "high"}}},
    "o4-mini-high": {"base_model": "o4-mini", "params": {"reasoning": {"effort": "high"}}},
}

_DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
_KNOWN_IDS = frozenset({*MODEL_FEATURES.keys(), *MODEL_ALIASES.keys()})

def normalize(model_id: str) -> str:
    """Normalize identifiers by lowercasing, trimming, and removing prefixes/dates."""

    raw = (model_id or "").strip().lower()
    if not raw:
        return ""

    no_date = _DATE_SUFFIX_RE.sub("", raw)
    if no_date in _KNOWN_IDS:
        return no_date

    dot_index = no_date.find(".")
    if dot_index != -1:
        suffix = _DATE_SUFFIX_RE.sub("", no_date[dot_index + 1 :])
        if suffix in _KNOWN_IDS:
            return suffix

    return no_date


def base_model(
    model_id: str,
    alias_lookup: Mapping[str, Mapping[str, str | dict]] | None = None,
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


def features(model_id: str) -> frozenset[str]:
    """Return the capability set for the canonical base model."""

    canonical = base_model(model_id, MODEL_ALIASES)
    return MODEL_FEATURES.get(canonical, EMPTY_FEATURES)


def supports(feature: str, model_id: str) -> bool:
    """Determine whether the supplied model exposes a feature."""

    return feature in features(model_id)


__all__ = [
    "EMPTY_FEATURES",
    "MODEL_FEATURES",
    "MODEL_ALIASES",
    "alias_defaults",
    "features",
    "supports",
    "normalize",
    "base_model",
]
