"""Registry for OpenAI model capabilities and pseudo-model aliases.

To add support for a a new OpenAI model:

* Look up the model in the OpenAI reference: https://platform.openai.com/docs/models
* Add an entry to ``MODEL_FEATURES`` keyed by the canonical API model ID
* (Optional) Add an entry to ``MODEL_ALIASES`` for pseudo-model shortcuts
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

MODEL_PREFIX = "openai_responses."
DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
EMPTY_FEATURES: frozenset[str] = frozenset()

# Update MODEL_FEATURES whenever OpenAI adds/removes model capabilities.
MODEL_FEATURES: dict[str, frozenset[str]] = {
    "gpt-5-auto": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5-mini": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-5-nano": frozenset(
        {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "image_gen_tool",
            "verbosity",
        }
    ),
    "gpt-4.1": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4.1-nano": frozenset({"function_calling", "image_gen_tool"}),
    "gpt-4o": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "gpt-4o-mini": frozenset({"function_calling", "web_search_tool", "image_gen_tool"}),
    "o3": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-mini": frozenset({"function_calling", "reasoning", "reasoning_summary"}),
    "o3-pro": frozenset({"function_calling", "reasoning"}),
    "o4-mini": frozenset({"function_calling", "reasoning", "reasoning_summary", "web_search_tool"}),
    "o3-deep-research": frozenset(
        {"function_calling", "reasoning", "reasoning_summary", "deep_research"}
    ),
    "o4-mini-deep-research": frozenset(
        {"function_calling", "reasoning", "reasoning_summary", "deep_research"}
    ),
    "gpt-5-chat-latest": frozenset({"function_calling", "web_search_tool"}),
    "chatgpt-4o-latest": EMPTY_FEATURES,
}

# Add entries to MODEL_ALIASES for any pseudo-model name users can pick.
# Each alias is a preset that points to a base model and optional default params,
# e.g. gpt-5-thinking-high -> gpt-5 with reasoning effort fixed to high.
MODEL_ALIASES: dict[str, dict[str, Any]] = {
    "gpt-5-thinking": {"base_model": "gpt-5"},
    "gpt-5-thinking-minimal": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-high": {"base_model": "gpt-5", "params": {"reasoning": {"effort": "high"}}},
    "gpt-5-thinking-mini": {"base_model": "gpt-5-mini"},
    "gpt-5-thinking-mini-minimal": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-mini-high": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-nano": {"base_model": "gpt-5-nano"},
    "gpt-5-thinking-nano-minimal": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "minimal"}},
    },
    "gpt-5-thinking-nano-high": {
        "base_model": "gpt-5-nano",
        "params": {"reasoning": {"effort": "high"}},
    },
    "o3-mini-high": {"base_model": "o3-mini", "params": {"reasoning": {"effort": "high"}}},
    "o4-mini-high": {"base_model": "o4-mini", "params": {"reasoning": {"effort": "high"}}},
}


def _normalize_model_id(model_id: str) -> str:
    model = (model_id or "").strip()
    model = model.removeprefix(MODEL_PREFIX)
    return DATE_SUFFIX_RE.sub("", model.lower())


def normalize(model_id: str) -> str:
    """Normalize an Open WebUI model identifier by stripping prefixes and dates."""
    return _normalize_model_id(model_id)


def base_model(model_id: str) -> str:
    """Return the canonical base model for the supplied identifier."""
    key = _normalize_model_id(model_id)
    alias = MODEL_ALIASES.get(key, {})
    base = alias.get("base_model")
    return _normalize_model_id(base) if base else key


def alias_defaults(model_id: str) -> dict[str, Any]:
    """Retrieve default parameters defined for the alias, if any."""
    params = MODEL_ALIASES.get(_normalize_model_id(model_id), {}).get("params")
    return deepcopy(params) if params else {}


def features(model_id: str) -> frozenset[str]:
    """Return the feature set associated with the base model."""
    return MODEL_FEATURES.get(base_model(model_id), EMPTY_FEATURES)


def supports(feature: str, model_id: str) -> bool:
    """Determine whether the model supports a given feature."""
    return feature in features(model_id)


__all__ = [
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "alias_defaults",
    "base_model",
    "features",
    "normalize",
    "supports",
]
