"""Single source of truth for OpenAI model capabilities.

If you're adding or modifying supported models, edit this file.
"""

from __future__ import annotations

EMPTY_FEATURES: frozenset[str] = frozenset()

# Update MODEL_FEATURES whenever OpenAI adds or removes model capabilities.
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
MODEL_ALIASES: dict[str, dict[str, dict | str]] = {
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

__all__ = ["EMPTY_FEATURES", "MODEL_FEATURES", "MODEL_ALIASES"]
