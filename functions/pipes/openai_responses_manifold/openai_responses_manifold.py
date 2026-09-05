"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
required_open_webui_version: 0.6.28
version: 0.9.15
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
import json
import logging
import os
import re
import sys
import secrets
import random
from time import monotonic, perf_counter
from collections import defaultdict, deque
from contextvars import ContextVar
import contextlib
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Literal, Optional, Union
from urllib.parse import urlparse

# Third-party imports
import aiohttp
from fastapi import Request
from pydantic import BaseModel, Field, model_validator

# Open WebUI internals
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models
from open_webui.models.users import Users
from open_webui.utils.misc import get_last_user_message

# fmt: off
# Open WebUI runs Black on upload; disabling fmt keeps this bundle readable in that UI.

# ─────────────────────────────────────────────────────────────────────────────
# 2. Constants & Global Configuration
# ─────────────────────────────────────────────────────────────────────────────
class ModelFamily:
    """
    One place for base capabilities + alias mapping (with effort defaults).
    """

    _DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
    _PREFIX  = "openai_responses."

    # Pipe-side pseudo-models that are never served by the /models endpoint
    # (kept in the picker even when the fetched model list doesn't contain them).
    _PSEUDO_MODELS = frozenset({"gpt-5-auto"})

    # Tokens that don't follow simple capitalization in display names.
    # An empty value drops the token entirely (e.g. '-none' effort suffix).
    _NAME_TOKEN_OVERRIDES = {"gpt": "GPT", "chatgpt": "ChatGPT", "xhigh": "XHigh", "none": ""}
    _O_SERIES_RE = re.compile(r"^o\d+$")  # o3, o4, … keep OpenAI's lowercase branding

    # Base models → capabilities.
    _SPECS: Dict[str, Dict[str, Any]] = {
        # GPT-6 Astra: single flagship slug (no tiers, no gpt-6 alias). Same capability set as GPT-5.6,
        # including pro mode. Does NOT accept reasoning.effort="none" (low | medium | high | xhigh | max).
        "gpt-6-astra":             {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},

        # GPT-5.6 renames the capability tiers: sol (flagship) / terra (balanced) / luna (high volume).
        # There is no separate "-pro" slug anymore — pro is reasoning.mode="pro" on any GPT-5.6 model.
        "gpt-5.6-sol":             {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5.6-terra":           {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5.6-luna":            {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},

        "gpt-5.5-pro":             {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5.5":                 {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        
        "gpt-5.4-pro":             {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5.4":                 {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        
        "gpt-5.2-pro":              {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5.2":              {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        
        "gpt-5.1":              {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        
        "gpt-5-pro":              {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5-auto":           {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5":                {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5-mini":           {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},
        "gpt-5-nano":           {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool","image_gen_tool","verbosity"}},

        "gpt-4.1":              {"features": {"function_calling","web_search_tool","image_gen_tool"}},
        "gpt-4.1-mini":         {"features": {"function_calling","web_search_tool","image_gen_tool"}},
        "gpt-4.1-nano":         {"features": {"function_calling","image_gen_tool"}},

        "gpt-4o":               {"features": {"function_calling","web_search_tool","image_gen_tool"}},
        "gpt-4o-mini":          {"features": {"function_calling","web_search_tool","image_gen_tool"}},

        "o3":                   {"features": {"function_calling","reasoning","reasoning_summary"}},
        "o3-mini":              {"features": {"function_calling","reasoning","reasoning_summary"}},
        "o3-pro":               {"features": {"function_calling","reasoning"}},

        "o4-mini":              {"features": {"function_calling","reasoning","reasoning_summary","web_search_tool"}},
        "o3-deep-research":     {"features": {"function_calling","reasoning","reasoning_summary","deep_research"}},
        "o4-mini-deep-research":{"features": {"function_calling","reasoning","reasoning_summary","deep_research"}},

        "gpt-5.2-chat-latest":  {"features": {"function_calling","web_search_tool"}},
        "gpt-5.1-chat-latest":  {"features": {"function_calling","web_search_tool"}},
        "gpt-5-chat-latest":    {"features": {"function_calling","web_search_tool"}},
        "chatgpt-4o-latest":    {"features": {}}, # Chat-optimized non-reasoning model does not support tool calling, or any other advanced features.
    }

    # Aliases/pseudos
    _ALIASES: Dict[str, Dict[str, Any]] = {
        # Commented out aliases are by default

        # GPT-6 Astra efforts: low | medium (default) | high | xhigh | max  (no "none" — the API rejects it)
        # "gpt-6-astra-medium":            {"base_model": "gpt-6-astra",   "params": {"reasoning": {"effort": "medium"}}},
        "gpt-6-astra-low":                 {"base_model": "gpt-6-astra",   "params": {"reasoning": {"effort": "low"}}},
        "gpt-6-astra-high":                {"base_model": "gpt-6-astra",   "params": {"reasoning": {"effort": "high"}}},
        "gpt-6-astra-xhigh":               {"base_model": "gpt-6-astra",   "params": {"reasoning": {"effort": "xhigh"}}},
        "gpt-6-astra-max":                 {"base_model": "gpt-6-astra",   "params": {"reasoning": {"effort": "max"}}},

        "gpt-6-astra-pro":                 {"base_model": "gpt-6-astra",   "params": {"reasoning": {"mode": "pro"}}},
        "gpt-6-astra-pro-high":            {"base_model": "gpt-6-astra",   "params": {"reasoning": {"mode": "pro", "effort": "high"}}},
        "gpt-6-astra-pro-xhigh":           {"base_model": "gpt-6-astra",   "params": {"reasoning": {"mode": "pro", "effort": "xhigh"}}},
        "gpt-6-astra-pro-max":             {"base_model": "gpt-6-astra",   "params": {"reasoning": {"mode": "pro", "effort": "max"}}},

        # GPT-5.6 efforts: none | low | medium (default) | high | xhigh | max
        "gpt-5.6":                         {"base_model": "gpt-5.6-sol"},  # OpenAI routes gpt-5.6 → gpt-5.6-sol

        # "gpt-5.6-sol-medium":             {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.6-sol-none":                {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.6-sol-low":                 {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.6-sol-high":                {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.6-sol-xhigh":               {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "xhigh"}}},
        "gpt-5.6-sol-max":                 {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"effort": "max"}}},

        # Pro mode = extra model work before a single final answer. Mode and effort are independent.
        "gpt-5.6-sol-pro":                 {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"mode": "pro"}}},
        "gpt-5.6-sol-pro-high":            {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"mode": "pro", "effort": "high"}}},
        "gpt-5.6-sol-pro-xhigh":           {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"mode": "pro", "effort": "xhigh"}}},
        "gpt-5.6-sol-pro-max":             {"base_model": "gpt-5.6-sol",   "params": {"reasoning": {"mode": "pro", "effort": "max"}}},

        # "gpt-5.6-terra-medium":           {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.6-terra-none":              {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.6-terra-low":               {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.6-terra-high":              {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.6-terra-xhigh":             {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "xhigh"}}},
        "gpt-5.6-terra-max":               {"base_model": "gpt-5.6-terra", "params": {"reasoning": {"effort": "max"}}},

        # "gpt-5.6-luna-medium":            {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.6-luna-none":               {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.6-luna-low":                {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.6-luna-high":               {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.6-luna-xhigh":              {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "xhigh"}}},
        "gpt-5.6-luna-max":                {"base_model": "gpt-5.6-luna",  "params": {"reasoning": {"effort": "max"}}},

        # "gpt-5.5-none":                        {"base_model": "gpt-5.5",       "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.5-low":                     {"base_model": "gpt-5.5",       "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.5-medium":                  {"base_model": "gpt-5.5",       "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.5-high":                    {"base_model": "gpt-5.5",       "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.5-xhigh":                   {"base_model": "gpt-5.5",       "params": {"reasoning": {"effort": "xhigh"}}},
        
        # "gpt-5.5-pro-medium":              {"base_model": "gpt-5.5-pro",   "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.5-pro-high":                {"base_model": "gpt-5.5-pro",   "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.5-pro-xhigh":               {"base_model": "gpt-5.5-pro",   "params": {"reasoning": {"effort": "xhigh"}}},
        
        # "gpt-5.4-none":                        {"base_model": "gpt-5.4"       "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.4-low":                     {"base_model": "gpt-5.4",       "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.4-medium":                  {"base_model": "gpt-5.4",       "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.4-high":                    {"base_model": "gpt-5.4",       "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.4-xhigh":                   {"base_model": "gpt-5.4",       "params": {"reasoning": {"effort": "xhigh"}}},
        
        # "gpt-5.4-pro-medium":              {"base_model": "gpt-5.4-pro",   "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.4-pro-high":                {"base_model": "gpt-5.4-pro",   "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.4-pro-xhigh":               {"base_model": "gpt-5.4-pro",   "params": {"reasoning": {"effort": "xhigh"}}},
        
        # "gpt-5.2-none":                        {"base_model": "gpt-5.2",       "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.2-low":                     {"base_model": "gpt-5.2",       "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.2-medium":                  {"base_model": "gpt-5.2",       "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.2-high":                    {"base_model": "gpt-5.2",       "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.2-xhigh":                   {"base_model": "gpt-5.2",       "params": {"reasoning": {"effort": "xhigh"}}},

        # "gpt-5.2-pro-medium":              {"base_model": "gpt-5.2-pro",   "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.2-pro-high":                {"base_model": "gpt-5.2-pro",   "params": {"reasoning": {"effort": "high"}}},
        "gpt-5.2-pro-xhigh":               {"base_model": "gpt-5.2-pro",   "params": {"reasoning": {"effort": "xhigh"}}},
        
        # "gpt-5.1-none":                        {"base_model": "gpt-5.1",       "params": {"reasoning": {"effort": "none"}}},
        "gpt-5.1-low":                     {"base_model": "gpt-5.1",       "params": {"reasoning": {"effort": "low"}}},
        "gpt-5.1-medium":                  {"base_model": "gpt-5.1",       "params": {"reasoning": {"effort": "medium"}}},
        "gpt-5.1-high":                    {"base_model": "gpt-5.1",       "params": {"reasoning": {"effort": "high"}}},

        # "gpt-5-medium":                          {"base_model": "gpt-5"},
        "gpt-5-minimal":                   {"base_model": "gpt-5",       "params": {"reasoning": {"effort": "minimal"}}},
        "gpt-5-high":                      {"base_model": "gpt-5",       "params": {"reasoning": {"effort": "high"}}},

        # "gpt-5-mini-medium":                     {"base_model": "gpt-5-mini"},
        "gpt-5-mini-minimal":              {"base_model": "gpt-5-mini",  "params": {"reasoning": {"effort": "minimal"}}},
        "gpt-5-mini-high":                 {"base_model": "gpt-5-mini",  "params": {"reasoning": {"effort": "high"}}},

        # "gpt-5-nano-medium":                     {"base_model": "gpt-5-nano"},
        "gpt-5-nano-minimal":              {"base_model": "gpt-5-nano",  "params": {"reasoning": {"effort": "minimal"}}},
        "gpt-5-nano-high":                 {"base_model": "gpt-5-nano",  "params": {"reasoning": {"effort": "high"}}},

        # Back-compat
        "o3-mini-high":                 {"base_model": "o3-mini",     "params": {"reasoning": {"effort": "high"}}},
        "o4-mini-high":                 {"base_model": "o4-mini",     "params": {"reasoning": {"effort": "high"}}},
    }

    # Pricing in USD per 1M tokens: (input, cached_input, output).
    # cached_input of None → cached input billed at the full input rate.
    # Verify against https://platform.openai.com/pricing and override/extend
    # via the CUSTOM_MODEL_PRICING_JSON valve without editing code.
    _PRICING: Dict[str, Any] = {
        "gpt-6-astra":             (10.00, 1.00,  50.00),  # >272K-token prompts bill 2x input / 1.5x output (not modelled)

        "gpt-5.6-sol":             (1.25,  0.125, 10.00),
        "gpt-5.6-terra":           (0.25,  0.025,  2.00),
        "gpt-5.6-luna":            (0.05,  0.005,  0.40),

        "gpt-5.5-pro":             (15.00, None,  120.00),
        "gpt-5.5":                 (1.25,  0.125, 10.00),

        "gpt-5.4-pro":             (15.00, None,  120.00),
        "gpt-5.4":                 (1.25,  0.125, 10.00),

        "gpt-5.2-pro":             (15.00, None,  120.00),
        "gpt-5.2":                 (1.25,  0.125, 10.00),

        "gpt-5.1":                 (1.25,  0.125, 10.00),

        "gpt-5-pro":               (15.00, None,  120.00),
        "gpt-5-auto":              (1.25,  0.125, 10.00),  # router pseudo-model; actual served model is priced when known
        "gpt-5":                   (1.25,  0.125, 10.00),
        "gpt-5-mini":              (0.25,  0.025,  2.00),
        "gpt-5-nano":              (0.05,  0.005,  0.40),

        "gpt-4.1":                 (2.00,  0.50,   8.00),
        "gpt-4.1-mini":            (0.40,  0.10,   1.60),
        "gpt-4.1-nano":            (0.10,  0.025,  0.40),

        "gpt-4o":                  (2.50,  1.25,  10.00),
        "gpt-4o-mini":             (0.15,  0.075,  0.60),

        "o3":                      (2.00,  0.50,   8.00),
        "o3-mini":                 (1.10,  0.55,   4.40),
        "o3-pro":                  (20.00, None,  80.00),

        "o4-mini":                 (1.10,  0.275,  4.40),
        "o3-deep-research":        (10.00, 2.50,  40.00),
        "o4-mini-deep-research":   (2.00,  0.50,   8.00),

        "gpt-5.2-chat-latest":     (1.25,  0.125, 10.00),
        "gpt-5.1-chat-latest":     (1.25,  0.125, 10.00),
        "gpt-5-chat-latest":       (1.25,  0.125, 10.00),
        "chatgpt-4o-latest":       (5.00,  None,  15.00),
    }

    # ── tiny, intuitive helpers ──────────────────────────────────────────────
    @classmethod
    def _norm(cls, model_id: str) -> str:
        m = (model_id or "").strip()
        if m.startswith(cls._PREFIX):
            m = m[len(cls._PREFIX):]
        return cls._DATE_RE.sub("", m.lower())

    @classmethod
    def base_model(cls, model_id: str) -> str:
        """Canonical base model id (aliases resolved; prefix/date stripped)."""
        key = cls._norm(model_id)
        base = cls._ALIASES.get(key, {}).get("base_model")
        return cls._norm(base or key)

    @classmethod
    def params(cls, model_id: str) -> Dict[str, Any]:
        """Alias-implied defaults (e.g., {'reasoning': {'effort':'high'}}). Empty for base ids."""
        key = cls._norm(model_id)
        return dict(cls._ALIASES.get(key, {}).get("params", {}))

    @classmethod
    def features(cls, model_id: str) -> frozenset[str]:
        """Capabilities for the base model behind this id/alias."""
        return frozenset(cls._SPECS.get(cls.base_model(model_id), {}).get("features", set()))

    @classmethod
    def supports(cls, feature: str, model_id: str) -> bool:
        """Check if a model (alias or base) supports a given feature."""
        return feature in cls.features(model_id)

    @classmethod
    def display_name(cls, model_id: str) -> str:
        """Human-friendly name, e.g. 'gpt-5.6-luna-pro' → 'GPT 5.6 Luna Pro'.

        Splits the normalized id on dashes, then per token: applies the override
        table (GPT/ChatGPT/XHigh), keeps version-ish tokens (5.6, 4o, 4.1) and
        o-series ids (o3, o4) as-is, and capitalizes the rest (sol → Sol).
        """
        words = []
        for token in cls._norm(model_id).split("-"):
            if not token:
                continue
            if token in cls._NAME_TOKEN_OVERRIDES:
                override = cls._NAME_TOKEN_OVERRIDES[token]
                if override:
                    words.append(override)
            elif token[0].isdigit() or cls._O_SERIES_RE.match(token):
                words.append(token)
            else:
                words.append(token.capitalize())
        return " ".join(words) or model_id

    @classmethod
    def pricing(cls, model_id: str) -> Optional[Dict[str, float]]:
        """USD rates per 1M tokens for the base model behind this id/alias, or None if unknown."""
        rates = cls._PRICING.get(cls.base_model(model_id))
        if not rates:
            return None
        input_rate, cached_rate, output_rate = rates
        return {
            "input": input_rate,
            "cached_input": cached_rate if cached_rate is not None else input_rate,
            "output": output_rate,
        }

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

class ResponsesBody(BaseModel):
    """
    Represents the body of a responses request to OpenAI Responses API.
    """
    
    # Required parameters
    model: str
    input: Union[str, List[Dict[str, Any]]] # plain text, or rich array

    # Optional parameters
    instructions: Optional[str] = ""              # system prompt
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

    @model_validator(mode='after')
    def _apply_alias_defaults(self) -> "ResponsesBody":
        """
        Normalize the model ID to its base and apply alias defaults from ModelFamily.

        Example:
            model="gpt-5-high" → model="gpt-5", reasoning={"effort": "high"}
        """
        orig_model = self.model or ""
        base_model = ModelFamily.base_model(orig_model)
        alias_defaults = ModelFamily.params(orig_model) or {}

        # No alias? keep as-is
        if base_model == orig_model and not alias_defaults:
            return self

        # Work on a deep copy of current state
        data = json.loads(self.model_dump_json(exclude_none=False))
        data["model"] = base_model

        def _deep_overlay(dst: dict, src: dict) -> dict:
            for k, v in src.items():
                if isinstance(v, dict):
                    node = dst.get(k)
                    if isinstance(node, dict):
                        _deep_overlay(node, v)
                    else:
                        dst[k] = json.loads(json.dumps(v))  # deep copy
                elif isinstance(v, list):
                    cur = dst.get(k)
                    if isinstance(cur, list):
                        seen = set(); out = []
                        def _key(x):
                            try: return ("json", json.dumps(x, sort_keys=True))
                            except Exception: return ("id", id(x))
                        for item in cur + v:
                            kk = _key(item)
                            if kk not in seen:
                                seen.add(kk); out.append(item)
                        dst[k] = out
                    else:
                        dst[k] = list(v)
                else:
                    dst[k] = v
            return dst

        if alias_defaults:
            _deep_overlay(data, alias_defaults)

        # Write merged data back onto the model
        for k, v in data.items():
            setattr(self, k, v)
        return self   

    @staticmethod
    def transform_owui_tools(__tools__: Dict[str, dict] | None, *, strict: bool = False) -> List[dict]:
        """
        Convert Open WebUI __tools__ registry (dict of entries with {"spec": {...}}) into
        OpenAI Responses-API tool specs: {"type": "function", "name", ...}.

        """
        if not __tools__:
            return []

        tools: List[dict] = []
        for item in __tools__.values():
            spec = item.get("spec") or {}
            name = spec.get("name")
            if not name:
                continue  # skip malformed entries

            params = spec.get("parameters") or {"type": "object", "properties": {}}

            tool = {
                "type": "function",
                "name": name,
                "description": spec.get("description") or name,
                "parameters": _strictify_schema(params) if strict else params,
            }
            if strict:
                tool["strict"] = True

            tools.append(tool)

        return tools

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
    async def transform_messages_to_input(
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

        # Gather all invisible markers from assistant messages (if both `chat_id` and `openwebui_model_id` are provided)
        if chat_id and openwebui_model_id:
            for m in messages:
                if (
                    m.get("role") == "assistant"
                    and m.get("content")
                    and contains_marker(m["content"])
                ):
                    for mk in extract_markers(m["content"], parsed=True):
                        required_item_ids.add(mk["ulid"])

        # Fetch persisted items, if invisible markers are present
        items_lookup: dict[str, dict] = {}
        if chat_id and openwebui_model_id and required_item_ids:
            items_lookup = await fetch_openai_response_items(
                chat_id,
                list(required_item_ids),
                openwebui_model_id=openwebui_model_id,
            )

        # Build the OpenAI input array
        openai_input: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            raw_content = msg.get("content", "")

            # Skip system messages; they will be mapped to `instructions` separately later in from_completions()
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
            if contains_marker(raw_content):
                for segment in split_text_by_markers(raw_content):
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
                if raw_content:
                    openai_input.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": raw_content}],
                        }
                    )

        return openai_input

    @classmethod
    async def from_completions(
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
            "reasoning_effort", "max_tokens",

            # Fields that are dropped and manually handled later in the pipe()
            "tools",
            "extra_tools" # Not a real OpenAI parm. Upstream filters may use it to add tools. The are appended to body["tools"] later in the pipe()
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
            sanitized_params["input"] = await ResponsesBody.transform_messages_to_input(
                completions_dict.get("messages", []),
                chat_id=chat_id,
                openwebui_model_id=openwebui_model_id
            )

        # Build the final ResponsesBody directly
        return ResponsesBody(
            **sanitized_params,
            **extra_params  # Extra parameters that are passed to the ResponsesBody (e.g., custom parameters configured in Open WebUI model settings)
        )

# ─────────────────────────────────────────────────────────────────────────────
# 4. Main Controller: Pipe
# ─────────────────────────────────────────────────────────────────────────────
# Primary interface implementing the Responses manifold
class Pipe:
    # 4.1 Configuration Schemas
    class Valves(BaseModel):
        # Connection & Auth
        BASE_URL: str = Field(
            default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )
        API_KEY: str = Field(
            default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )

        # Models
        MODEL_ID: str = Field(
            default=", ".join(list(ModelFamily._SPECS.keys()) + list(ModelFamily._ALIASES.keys())),
            description=(
                "Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. "
                "Supports all official OpenAI model IDs and pseudo IDs (see README.md for full list)."
            ),
        )
        FETCH_MODELS: bool = Field(
            default=True,
            description=(
                "Fetch the model list from {BASE_URL}/models and hide MODEL_ID entries whose base model "
                "isn't served by the endpoint. Falls back to the full MODEL_ID list when the fetch fails "
                "or when nothing matches. Pseudo-models (e.g. gpt-5-auto) are always kept."
            ),
        )
        MODEL_FETCH_TTL_SECONDS: int = Field(
            default=600,
            description=(
                "How long (in seconds) the fetched model list is cached before it is refreshed. "
                "Prevents hitting /models on every model-picker refresh. Minimum 60 seconds."
            ),
        )
        MODEL_ICON_URL: Optional[str] = Field(
            default=None,
            description=(
                "Optional icon for this manifold's models, applied to each model record's "
                "meta.profile_image_url when the model list refreshes (a DB write; records are "
                "created when missing). Only set when no icon exists — an icon already set by an "
                "admin is never overridden. Accepts http(s) URLs or "
                "data:image/{png,jpeg,gif,webp};base64 URIs (SVG data-URIs are rejected by newer "
                "Open WebUI versions). Leave blank to disable."
            ),
        )

        # Reasoning & summaries
        REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"] = Field(
            default="disabled",
            description="REQUIRES VERIFIED OPENAI ORG. Visible reasoning summary (auto | concise | detailed | disabled). Works on gpt-5, o3, o4-mini; ignored otherwise. Docs: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
        )
        PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"] = Field(
            default="disabled",
            description="REQUIRES VERIFIED OPENAI ORG. If verified, highly recommend using 'response' or 'conversation' for best results. If `disabled` (default) = never request encrypted reasoning tokens; if `response` = request tokens so the model can carry reasoning across tool calls for the current response; If `conversation` = also persist tokens for future messages in this chat (higher token usage; quality may vary).",
        )
        
        # Tool execution behavior
        AUTO_ENABLE_NATIVE_FUNCTION_CALLING: bool = Field(
            default=True,
            description=(
                "When tools are attached and the model's Open WebUI 'Function Calling' setting is unset, "
                "persist it as 'native' in the model record (a DB write). Only applies when the setting is "
                "missing — an explicit admin choice (e.g. 'default') is never overridden. Disable to make "
                "this pipe never modify model records."
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

        # Web search
        ENABLE_WEB_SEARCH_TOOL: bool = Field(
            default=False,
            description="Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini, o3, o4-mini, o4-mini-high).  NOTE: This appears to disable parallel tool calling. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
        )
        WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH_TOOL=True.",
        )
        WEB_SEARCH_USER_LOCATION: Optional[str] = Field(
            default=None,
            description='User location for web search context. Leave blank to disable. Must be in valid JSON format according to OpenAI spec.  E.g., {"type": "approximate","country": "US","city": "San Francisco","region": "CA"}.',
        )

        # Integrations
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
            description="OpenAI truncation strategy for model responses. 'auto' drops middle context items if the conversation exceeds the context window; 'disabled' returns a 400 error instead.",
        )

        # Usage & cost reporting
        SHOW_USAGE_COST: bool = Field(
            default=True,
            description=(
                "Append estimated USD cost to the usage stats shown in Open WebUI "
                "(computed from token counts and the built-in per-model price table). "
                "Estimates only — always verify against your OpenAI invoice."
            ),
        )
        CUSTOM_MODEL_PRICING_JSON: Optional[str] = Field(
            default=None,
            description=(
                "Optional JSON object to override or extend the built-in price table. "
                "Maps base model id → USD per 1M tokens, e.g. "
                '{"gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0}}. '
                "'cached_input' is optional (defaults to the input rate)."
            ),
        )

        # Privacy & caching
        PROMPT_CACHE_KEY: Literal["id", "email"] = Field(
            default="id",
            description=(
                "Controls which user identifier is sent in the 'user' parameter to OpenAI. "
                "Passing a unique identifier enables OpenAI response caching (improves speed and reduces cost). "
                "Choose 'id' to use the OpenWebUI user ID (default; privacy-friendly), or 'email' to use the user's email address."
            ),
        )

        # Logging
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
        # Cache for the fetched /models list (see _get_available_models).
        self._available_models: frozenset[str] | None = None
        self._available_models_fetched_at: float = float("-inf")
        self._models_fetch_lock = asyncio.Lock()
        # Model ids whose icon has already been checked/synced this process (see MODEL_ICON_URL).
        self._icon_synced: set[str] = set()
        self._icon_synced_for: str | None = None  # MODEL_ICON_URL value the cache was built for
        # One-time (per process) rename of legacy 'OpenAI: <id>' workspace records.
        self._legacy_names_renamed = False

    async def pipes(self):
        model_ids = [model_id.strip() for model_id in self.valves.MODEL_ID.split(",") if model_id.strip()]

        # Rename stale auto-generated names in workspace records (runs once per process;
        # uses the unfiltered list so records for currently hidden models are fixed too).
        await self._rename_legacy_model_records(model_ids)

        # Hide configured models the endpoint doesn't actually serve (cached; see valve docs).
        available = await self._get_available_models()
        if available is not None:
            filtered = [
                model_id for model_id in model_ids
                if ModelFamily.base_model(model_id) in available
                or ModelFamily.base_model(model_id) in ModelFamily._PSEUDO_MODELS
            ]
            # Safety net: an endpoint with fully custom ids (e.g. a LiteLLM alias map)
            # would otherwise empty the picker — fall back to the configured list.
            if filtered:
                model_ids = filtered

        await self._sync_model_icons(model_ids)

        return [{"id": model_id, "name": ModelFamily.display_name(model_id)} for model_id in model_ids]

    async def _sync_model_icons(self, model_ids: list[str]) -> None:
        """Write MODEL_ICON_URL to each model record's meta.profile_image_url.

        Set-only-if-missing: an icon already set by an admin is never overridden.
        Models without a workspace record get a minimal one (icon only), attributed
        to the super-admin user. Each model is checked at most once per process
        (cache resets when MODEL_ICON_URL changes); failures are logged and skipped.
        """
        icon = (self.valves.MODEL_ICON_URL or "").strip()
        if not icon:
            return
        if icon != self._icon_synced_for:
            self._icon_synced.clear()
            self._icon_synced_for = icon

        pending = [
            ModelFamily._PREFIX + model_id
            for model_id in model_ids
            if ModelFamily._PREFIX + model_id not in self._icon_synced
        ]
        if not pending:
            return

        # Owner for records we may need to create (workspace models require a user id).
        admin = None
        try:
            admin = Users.get_super_admin_user()
            if inspect.iscoroutine(admin):
                admin = await admin
        except Exception:
            self.logger.exception("Could not resolve an admin user for model icon records")

        for full_id in pending:
            self._icon_synced.add(full_id)  # once per process; also caches failures
            try:
                model = Models.get_model_by_id(full_id)
                if inspect.iscoroutine(model):
                    model = await model

                if model:
                    meta = dict(model.meta or {})
                    if meta.get("profile_image_url"):
                        continue
                    meta["profile_image_url"] = icon
                    form_data = model.model_dump()
                    form_data["meta"] = meta
                    result = Models.update_model_by_id(full_id, ModelForm(**form_data))
                    if inspect.iscoroutine(result):
                        await result
                elif admin is not None:
                    # No workspace record yet — create a minimal one carrying only the icon.
                    form_data = ModelForm(
                        id=full_id,
                        name=ModelFamily.display_name(full_id),
                        meta={"profile_image_url": icon},
                        params={},
                    )
                    result = Models.insert_new_model(form_data, admin.id)
                    if inspect.iscoroutine(result):
                        await result
            except Exception:
                self.logger.exception("Failed to set model icon for %s", full_id)

    async def _rename_legacy_model_records(self, model_ids: list[str]) -> None:
        """One-time cleanup of stale auto-generated names in workspace records.

        Pre-0.9.11 the pipe named models 'OpenAI: <id>'. Workspace records created
        back then (admin edits, native function-calling flips, icon syncs) still
        carry that name and override the parsed display names in the picker
        (Open WebUI overlays record.name over the pipe-provided name). Rename only
        records whose name is still a legacy auto-name; admin-customized names are
        never touched. Runs once per process; failures are logged and skipped.
        """
        if self._legacy_names_renamed:
            return
        self._legacy_names_renamed = True

        for model_id in model_ids:
            full_id = ModelFamily._PREFIX + model_id
            try:
                model = Models.get_model_by_id(full_id)
                if inspect.iscoroutine(model):
                    model = await model
                if not model:
                    continue

                legacy_names = {f"OpenAI: {model_id}", model_id, full_id}
                if (model.name or "") not in legacy_names:
                    continue  # admin-customized (or already migrated) name — keep it

                new_name = ModelFamily.display_name(model_id)
                form_data = model.model_dump()
                form_data["name"] = new_name
                result = Models.update_model_by_id(full_id, ModelForm(**form_data))
                if inspect.iscoroutine(result):
                    await result
                self.logger.info("Renamed legacy model record %s: %r -> %r", full_id, model.name, new_name)
            except Exception:
                self.logger.exception("Failed to rename legacy model record %s", full_id)

    async def _get_available_models(self) -> frozenset[str] | None:
        """Return normalized model ids served by ``{BASE_URL}/models``, or ``None``.

        Results are cached for ``MODEL_FETCH_TTL_SECONDS`` so the endpoint is not
        hit on every model-picker refresh. Failures are also cached for the TTL
        (stale-while-error: the last good list keeps being served) and ``None`` is
        returned when fetching is disabled or has never succeeded, in which case
        callers should skip filtering entirely.
        """
        if not self.valves.FETCH_MODELS:
            return None

        ttl = max(60, int(self.valves.MODEL_FETCH_TTL_SECONDS or 0))
        async with self._models_fetch_lock:
            if monotonic() - self._available_models_fetched_at < ttl:
                return self._available_models
            self._available_models_fetched_at = monotonic()

            url = self.valves.BASE_URL.rstrip("/") + "/models"
            try:
                self.session = await self._get_or_init_http_session()
                headers = {"Authorization": f"Bearer {self.valves.API_KEY}"}
                async with self.session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
                ids = {
                    ModelFamily._norm(entry.get("id", ""))
                    for entry in payload.get("data", [])
                    if isinstance(entry, dict)
                }
                ids.discard("")
                self._available_models = frozenset(ids)
                self.logger.debug("Fetched %d model ids from %s", len(ids), url)
            except Exception as exc:
                self.logger.warning(
                    "Model list fetch from %s failed (%s); using %s.",
                    url,
                    exc,
                    "cached list" if self._available_models is not None else "full MODEL_ID list",
                )
            return self._available_models

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]] | None,
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: Optional[dict[str, Any]] = None,
        __task_body__: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str | dict[str, Any], None] | str | None:
        """Process a user request and return either a stream or final text.

        When ``body['stream']`` is ``True`` the method yields deltas from
        ``_run_streaming_loop``.  Otherwise it falls back to
        ``_run_nonstreaming_loop`` and returns the aggregated response.
        """
        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        openwebui_model_id = __metadata__.get("model", {}).get("id", "") # Full model ID, e.g. "openai_responses.gpt-4o"
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]  # Use 'id' or 'email' as configured
        features = __metadata__.get("features", {}).get("openai_responses", {}) # Custom location that this manifold uses to store feature flags

        # STEP 0: Set up session logger with session_id and log level
        SessionLogger.session_id.set(__metadata__.get("session_id", None))
        SessionLogger.log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        # ------------------------------------------------------------------
        # BONUS: Add support for Multi-line Status Descriptions (plus bold first line)
        #
        #  Open WebUI clamps each emitted status description to one line
        # (Tailwind `line-clamp-1`). This tiny, idempotent CSS patch:
        #   1) Removes the clamp and enables `white-space: pre-wrap` so "\n"
        #      render as real line breaks.
        #   2) Adds gentle, native-feeling emphasis to the *first visual line*
        #      using semibold (600), not full bold.
        #
        # Scope:
        #   • Affects only elements under `.status-description`
        #   • No frontend rebuild; injected at runtime via `execute`
        #   • Runs once per tab (checks for an existing <style> tag)
        # ------------------------------------------------------------------
        await __event_emitter__({
            "type": "execute",
            "data": {
                "code": """
                (() => {
                // Only inject once per tab
                if (document.getElementById("owui-status-unclamp")) return "ok";

                const style = document.createElement("style");
                style.id = "owui-status-unclamp";

                style.textContent = `
                    /* Allow multi-line in the status strip */
                    .status-description .line-clamp-1,
                    .status-description .text-base.line-clamp-1,
                    .status-description .text-gray-500.text-base.line-clamp-1 {
                    display: block !important;
                    overflow: visible !important;
                    -webkit-line-clamp: unset !important;
                    -webkit-box-orient: initial !important;
                    white-space: pre-wrap !important;  /* render \\n as line breaks */
                    word-break: break-word;
                    }

                    /* Bold the first visual line */
                    .status-description .text-base::first-line,
                    .status-description .text-gray-500.text-base::first-line {
                    font-weight: 500 !important;
                    }
                `;

                document.head.appendChild(style);
                return "ok";
                })();
                """
            }
        })
        # ------------------------------------------------------------------


        # STEP 1: Transform request body (Completions API -> Responses API).
        completions_body = CompletionsBody.model_validate(body)
        responses_body = await ResponsesBody.from_completions(
            completions_body=completions_body,

            # If chat_id and openwebui_model_id are provided, from_completions() uses them to fetch previously persisted items (function_calls, reasoning, etc.) from DB and reconstruct the input array in the correct order.
            **({"chat_id": __metadata__["chat_id"]} if __metadata__.get("chat_id") else {}),
            **({"openwebui_model_id": openwebui_model_id} if openwebui_model_id else {}),

            # Additional optional parameters passed directly to ResponsesBody without validation. Overrides any parameters in the original body with the same name.
            truncation=valves.TRUNCATION,
            user=user_identifier,
            **({"max_tool_calls": valves.MAX_TOOL_CALLS} if valves.MAX_TOOL_CALLS is not None else {}),
        )

        # STEP 2: Detect if task model (generate title, generate tags, etc.), handle it separately
        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self._run_task_model_request(responses_body.model_dump(), valves) # Placeholder for task handling logic

        # STEP 3: Build OpenAI Tools JSON (from __tools__, valves, and completions_body.extra_tools)
        __tools__ = await __tools__ if inspect.isawaitable(__tools__) else __tools__  # Await coroutine if needed (required for newer versions of Open WebUI)
        tools = build_tools(
            responses_body,
            valves,
            __tools__=__tools__,
            features=features,
            extra_tools=getattr(completions_body, "extra_tools", None),
        )

        # STEP 4: Auto-enable native function calling if tools are used but the model's `function_calling`
        # setting is missing in Open WebUI model settings. Explicit admin choices are respected.
        if tools and valves.AUTO_ENABLE_NATIVE_FUNCTION_CALLING and ModelFamily.supports("function_calling", openwebui_model_id):
            model = Models.get_model_by_id(openwebui_model_id)
            if inspect.iscoroutine(model):
                model = await model
                
            if model:
                params = dict(model.params or {})
                if params.get("function_calling") is None:
                    await self._emit_notification(
                        __event_emitter__,
                        content=f"Enabling native function calling for model: {openwebui_model_id}. Please re-run your query.",
                        level="info"
                    )
                    params["function_calling"] = "native"
                    form_data = model.model_dump()
                    form_data["params"] = params
                    Models.update_model_by_id(openwebui_model_id, ModelForm(**form_data))

        # STEP 5: Handle GPT-5-Auto routing
        if openwebui_model_id.endswith(".gpt-5-auto-dev"):
            responses_body = await self._route_gpt5_auto(
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                tools=tools,
                valves=valves,
                event_emitter=__event_emitter__
            )
        elif openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self._emit_notification(
                __event_emitter__,
                content=(
                    "Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast)."
                ),
                level="warning"
            )

        # STEP 6: Add tools to responses body, if supported
        if ModelFamily.supports("function_calling", responses_body.model):
            responses_body.tools = tools

        # STEP 7: Enable reasoning summary if enabled and supported
        if ModelFamily.supports("reasoning_summary", responses_body.model) and valves.REASONING_SUMMARY != "disabled":
            # Ensure reasoning param is a mutable dict so we can safely assign to it
            reasoning_params = dict(responses_body.reasoning or {})
            reasoning_params["summary"] = valves.REASONING_SUMMARY
            responses_body.reasoning = reasoning_params

        # STEP 8: Always request encrypted reasoning for in-turn carry (multi-tool) unless disabled
        if (ModelFamily.supports("reasoning", responses_body.model)
            and valves.PERSIST_REASONING_TOKENS != "disabled"
            and responses_body.store is False):
             responses_body.include = responses_body.include or []
             if "reasoning.encrypted_content" not in responses_body.include:
                 responses_body.include.append("reasoning.encrypted_content")

        # If a web_search tool is present, always request sources
        if any(isinstance(t, dict) and t.get("type") == "web_search" for t in (responses_body.tools or [])):
            if ModelFamily.supports("web_search_tool", responses_body.model):
                responses_body.include = list(responses_body.include or [])
                if "web_search_call.action.sources" not in responses_body.include:
                    responses_body.include.append("web_search_call.action.sources")

        # STEP 9: Map WebUI "Add Details" / "More Concise" → text.verbosity (if supported by model), then strip the stub
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
                if ModelFamily.supports("verbosity", responses_body.model):
                    # Set/overwrite verbosity (do NOT remove the stub message)
                    current_text_params = dict(getattr(responses_body, "text", {}) or {})
                    current_text_params["verbosity"] = verbosity_value
                    responses_body.text = current_text_params

                    # Remove the stub user message so the model doesn't see it
                    input_items.pop()  # or: del input_items[-1]

                    # Notify the user in the UI
                    await self._emit_notification(__event_emitter__,f"Regenerating with verbosity set to {verbosity_value}.",level="info")

                    self.logger.debug("Set text.verbosity=%s based on regenerate directive '%s'",verbosity_value, last_user_text)

        # STEP 10: Log the transformed request body
        self.logger.debug(
            "Transformed ResponsesBody: %s",
            json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False),
        )

        # STEP 11: Send to OpenAI Responses API
        if responses_body.stream:
            # Return async generator for partial text
            return await self._run_streaming_loop(responses_body, valves, __event_emitter__, __metadata__, __tools__)
        else:
            # Return final text (non-streaming)
            await self._emit_error(__event_emitter__, "Non-streaming is currently not supported with the OpenAI Responses Manifold.  Please enable streaming and try again", level="warning", show_error_message=True)
            return ""
            #return await self._run_nonstreaming_loop(responses_body, valves, __event_emitter__, __metadata__, __tools__)

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

        thinking_tasks: list[asyncio.Task] = []
        if ModelFamily.supports("reasoning", body.model) and event_emitter:
            async def _later(delay: float, msg: str) -> None:
                await asyncio.sleep(delay)
                await event_emitter({"type": "status", "data": {"description": msg}})

            thinking_tasks = []
            for delay, msg in [
                (0, "Thinking…"),
                (1.5, "Reading the user's question…"),
                (4.0, "Gathering my thoughts…"),
                (6.0, "Exploring possible responses…"),
                (7.0, "Building a plan…"),
            ]:
                thinking_tasks.append(
                    asyncio.create_task(_later(delay + random.uniform(0, 0.5), msg))
                )

        def cancel_thinking() -> None:
            if thinking_tasks:
                for t in thinking_tasks:
                    t.cancel()
                thinking_tasks.clear()

        model_router_result = getattr(body, "model_router_result", None)
        if model_router_result:
            delattr(body, "model_router_result")
            model = model_router_result.get("model", "")
            reasoning_effort = model_router_result.get("reasoning_effort", "")
            if event_emitter:
                await event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": f"Routing to {model} (effort: {reasoning_effort})\nExplanation: {model_router_result.get('explanation', '')}",
                        },
                    }
                )

        start_time = perf_counter()

        # Send OpenAI Responses API request, parse and emit response
        error_occurred = False
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
                            await event_emitter({"type": "chat:message", "data": {"content": assistant_message}})
                        continue

                    # ─── Emit reasoning summary once done ───────────────────────
                    if etype == "response.reasoning_summary_text.done":
                        text = (event.get("text") or "").strip()
                        if text:
                            title_match = re.findall(r"\*\*(.+?)\*\*", text)
                            title = title_match[-1].strip() if title_match else "Thinking…"
                            content = re.sub(r"\*\*(.+?)\*\*", "", text).strip()
                            if event_emitter:
                                cancel_thinking()
                                await event_emitter(
                                    {
                                        "type": "status",
                                        "data": {"description": f"{title}\n{content}"},
                                    }
                                )
                        continue

                    # ─── Citations from inline annotations (simple, no helpers) ───────────────
                    if etype == "response.output_text.annotation.added":
                        ann = event.get("annotation") or {}
                        if ann.get("type") == "url_citation":
                            # Basic fields
                            url = (ann.get("url") or "").strip()
                            if url.endswith("?utm_source=openai"):
                                url = url[: -len("?utm_source=openai")]
                            title = (ann.get("title") or url).strip()

                            # Stable [n] per unique URL
                            if url in ordinal_by_url:
                                n = ordinal_by_url[url]
                            else:
                                n = len(ordinal_by_url) + 1
                                ordinal_by_url[url] = n

                                # First time seeing this URL → emit a 'source' event
                                # Minimal domain extraction (no urlparse)
                                host = url.split("//", 1)[-1].split("/", 1)[0].lower().lstrip("www.")
                                citation = {
                                    "source": {"name": host or "source", "url": url},
                                    "document": [title],
                                    "metadata": [{
                                        "source": url,
                                        "date_accessed": datetime.date.today().isoformat(),
                                    }],
                                }
                                await event_emitter({"type": "source", "data": citation})
                                emitted_citations.append(citation)

                            # TODO: Add support for insert citation markers.
                            marker = f" [{n}]"
                            end_idx = ann.get("end_index")

                        continue


                    # ─── Emit status updates for in-progress items ──────────────────────
                    if etype == "response.output_item.added":
                        item = event.get("item", {})
                        item_type = item.get("type", "")
                        item_status = item.get("status", "")

                        if item_type == "message" and item_status == "in_progress":
                            if event_emitter:
                                await event_emitter(
                                    {
                                        "type": "status",
                                        "data": {"description": "Responding to the user…"},
                                    }
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

                        # Decide persistence policy
                        should_persist = False
                        if item_type == "reasoning":
                            # Persist reasoning only when explicitly allowed
                            should_persist = valves.PERSIST_REASONING_TOKENS == "conversation"

                        elif item_type in ("message", "web_search_call"):
                            # Never persist assistant/user messages or ephemeral search calls
                            should_persist = False

                        else:
                            # Persist all other non-message items if valve enabled
                            should_persist = valves.PERSIST_TOOL_RESULTS

                        if should_persist:
                            hidden_uid_marker = await persist_openai_response_items(
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
                            title = f"Running the {item_name} tool…"
                            arguments = json.loads(item.get("arguments") or "{}")
                            args_formatted = ", ".join(f"{k}={json.dumps(v)}" for k, v in arguments.items())
                            content = wrap_code_block(f"{item_name}({args_formatted})", "python")

                        elif item_type == "web_search_call":
                            action = item.get("action", {}) or {}

                            if action.get("type") == "search":
                                query = action.get("query")
                                sources = action.get("sources") or []
                                urls = [s.get("url") for s in sources if s.get("url")]

                                if event_emitter:
                                    # Emit 'searching' status update along with the search query if available
                                    if query:
                                        await event_emitter({
                                            "type": "status",
                                            "data": {
                                                "action": "web_search_queries_generated",
                                                "description": "Searching",
                                                "queries": [query],
                                                "done": False,
                                            },
                                        })

                                    # If API returned sources (only when include[...] was set), emit the panel now
                                    if urls:
                                        # Mirror upstream middleware: report how many sources were retrieved
                                        await event_emitter({
                                            "type": "status",
                                            "data": {
                                                "action": "sources_retrieved",
                                                "count": len(urls),
                                                "done": False,
                                            },
                                        })
                                        await event_emitter({
                                            "type": "status",
                                            "data": {
                                                "action": "web_search",
                                                "description": "Reading through {{count}} sites",
                                                "query": query,
                                                "urls": urls,
                                                "done": False,
                                            },
                                        })

                            elif action.get("type") == "open_page":
                                #TODO: emit status for open_page.  Only emitted by Deep Research models
                                continue
                            elif action.get("type") == "find_in_page":
                                #TODO: emit status for find_in_page.  Only emitted by Deep Research models
                                continue
                                    
                            continue

                        elif item_type == "file_search_call":
                            title = "Let me skim those files…"
                        elif item_type == "image_generation_call":
                            title = "Let me create that image…"
                        elif item_type == "local_shell_call":
                            title = "Let me run that command…"
                        elif item_type == "mcp_call":
                            title = "Let me query the MCP server…"
                        elif item_type == "reasoning":
                            title = None # Don't emit a title for reasoning items

                        # Emit the status with prepared title and detailed content
                        if title and event_emitter:
                            desc = title if not content else f"{title}\n{content}"
                            if thinking_tasks:
                                cancel_thinking()
                            await event_emitter({"type": "status", "data": {"description": desc}})

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

                    # Estimate cost from cumulative token counts (recomputed each turn,
                    # not merged, to avoid double counting). Prefer the actual served
                    # model reported by the API (e.g. after gpt-5-auto routing).
                    if valves.SHOW_USAGE_COST:
                        served_model = final_response.get("model") or body.model
                        pricing = resolve_model_pricing(served_model, valves.CUSTOM_MODEL_PRICING_JSON)
                        if pricing:
                            total_usage["cost"] = estimate_usage_cost(total_usage, pricing)
                        else:
                            self.logger.debug("No pricing found for model %r; skipping cost estimate.", served_model)

                    await self._emit_completion(event_emitter, content="", usage=total_usage, done=False)

                # Execute tool calls (if any), persist results (if valve enabled), and append to body.input.
                calls = [i for i in final_response["output"] if i["type"] == "function_call"]
                if calls:
                    function_outputs = await self._execute_function_calls(calls, tools)
                    if valves.PERSIST_TOOL_RESULTS:
                        hidden_uid_marker = await persist_openai_response_items(
                            metadata.get("chat_id"),
                            metadata.get("message_id"),
                            function_outputs,
                            openwebui_model,
                        )
                        self.logger.debug("Persisted item: %s", hidden_uid_marker)
                        if hidden_uid_marker:
                            assistant_message += hidden_uid_marker
                            if thinking_tasks:
                                cancel_thinking()
                            await event_emitter({"type": "chat:message", "data": {"content": assistant_message}})


                    for output in function_outputs:
                        result_text = wrap_code_block(output.get("output", ""))
                        if event_emitter:
                            if thinking_tasks:
                                cancel_thinking()
                            await event_emitter(
                                {
                                    "type": "status",
                                    "data": {"description": f"Received tool result\n{result_text}"},
                                }
                            )
                    body.input.extend(function_outputs)
                else:
                    break

        # Catch any exceptions during the streaming loop and emit an error
        except Exception as e:  # pragma: no cover - network errors
            error_occurred = True
            await self._emit_error(event_emitter, f"Error: {str(e)}", show_error_message=True, show_error_log_citation=True, done=True)

        finally:
            cancel_thinking()
            for t in thinking_tasks:
                with contextlib.suppress(Exception):
                    await t
            if not error_occurred and event_emitter:
                elapsed = perf_counter() - start_time
                await event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": f"Thought for {elapsed:.1f} seconds",
                            "done": True,
                        },
                    }
                )

            if valves.LOG_LEVEL != "INHERIT":
                if event_emitter:
                    session_id = SessionLogger.session_id.get()
                    logs = SessionLogger.logs.get(session_id, [])
                    if logs:
                        await self._emit_citation(event_emitter, "\n".join(logs), "Logs")

            # Emit completion (middleware.py also does this so this just covers if there is a downstream error)
            await self._emit_completion(event_emitter, content="", usage=total_usage, done=True)  # There must be an empty content to avoid breaking the UI

            # Clear logs
            SessionLogger.logs.pop(SessionLogger.session_id.get(), None)

            chat_id = metadata.get("chat_id")
            message_id = metadata.get("message_id")
            if chat_id and message_id and emitted_citations:
                await Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id, message_id, {"sources": emitted_citations}
                )

            # Return the final output to ensure persistence.
            #
            # NOTE: this used to `return assistant_message` (a bare str). OWUI's
            # generate_function_chat_completion() (functions.py) wraps a bare-str
            # pipe result in a single content chunk via
            # openai_chat_chunk_message_template(model, res) -- a template that
            # *supports* a usage= kwarg, but that call site never passes one. So
            # `total_usage`/cost computed above was only ever delivered via the
            # _emit_completion() socket event above, which OWUI's event emitter
            # does not persist to the DB message (only status/message/replace/
            # embeds/files/source/citation events are persisted there) -- it's a
            # live-broadcast-only side channel invisible to outlet filters.
            #
            # Returning an async generator instead routes through OWUI's
            # AsyncGenerator branch in functions.py, which passes each yielded
            # item through process_line(): a plain str becomes the same content
            # chunk as before, and a dict becomes a raw SSE JSON chunk. A
            # `{"usage": ...}` chunk (no/empty `choices`) is handled safely by
            # middleware.py's stream parser, which merges `usage` into the
            # accumulator *before* checking `choices` -- so it flows into
            # ctx['assistant_message']['usage'], the exact structure outlet
            # filters receive. functions.py still appends its own closing
            # finish/[DONE] frames afterward, so behavior is otherwise unchanged.
            async def _final_chunks():
                if assistant_message:
                    yield assistant_message
                if total_usage:
                    yield {"usage": total_usage}

            return _final_chunks()

    async def _run_nonstreaming_loop(
        self,
        body: ResponsesBody,
        valves: Pipe.Valves,
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]],
        metadata: Dict[str, Any] = {},
        tools: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str | Dict[str, Any], None]:
        """Unified implementation: reuse the streaming path.

        We force `stream=True` and delegate to `_run_streaming_loop`, but wrap the
        emitter so incremental `chat:message` frames are suppressed. The final
        message text is returned (same contract as before).
        """

        # Force SSE so we can reuse the streaming machinery
        body.stream = True

        # Pass through status / citations / usage, but do NOT emit partial text
        wrapped_emitter = _wrap_event_emitter(
            event_emitter,
            suppress_chat_messages=True,
            suppress_completion=False,
        )

        return await self._run_streaming_loop(
            body,
            valves,
            wrapped_emitter,
            metadata,
            tools or {},
        )

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
            "store": False,
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
        router_model: str,
        responses_body: ResponsesBody,
        tools: list[dict[str, Any]],
        valves: "Pipe.Valves",
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ResponsesBody:
        """Route using first output message only (assumes no tool events)."""

        # --- keep your existing router_body UNCHANGED ---
        router_body = {
            "model": "gpt-5-mini",
            "reasoning": {"effort": "minimal"},
            "instructions": "# Role and Objective\nServe as a **routing helper** for selecting the most appropriate GPT-5 model for user messages, evaluating tool necessity and task complexity.\n\n---\n\n# Instructions\n- If a message may require the use of **any available tool**, select a model with **function calling** capabilities. If **web search** is required, you may only choose **low, medium or high** reasoning, not minimal.\n- When tools are not necessary, favor the **fastest** or **most capable** model according to the complexity of the request.\n\n---\n\n# Available Models and Capabilities\n## Models\n\n- **gpt-5-chat-latest**\n  - Fast, general-purpose, and creative.\n  - Best for writing, drafting, and chat-based interactions.\n  - ⚠️ Does **not** support tool calling—select only when tools are not required.\n\n- **gpt-5-mini**\n  - Lightweight, supports tool usage, and is rapidly responsive.\n  - Suited for **simple tasks that may use tools** but don’t demand extensive reasoning.\n  - ✅ Function calling supported—offers a strong balance between speed and utility.\n\n- **gpt-5**\n  - Strong at reasoning and complex, multi-step analysis.\n  - Designed for **complex or deeply analytical tasks**.\n  - ✅ Supports function calling and advanced operations—choose for tool-reliant or high-complexity reasoning needs.\n\n---\n\n# Routing Checklist\n- Assess whether tool integration could improve the response.\n- Evaluate how much reasoning or problem-solving is required.\n- Match model to requirements:\n  - No tool usage required → use `gpt-5-chat-latest`\n  - Tools required, simple task → use `gpt-5-mini`\n  - Tools required, complex task → use `gpt-5`\n- When in doubt, prioritize a tool-capable model (prefer `gpt-5`).\n- Ask for more information if requirements are ambiguous.\n\n---\n\n# Output Format\nRespond only with a JSON object containing your model selection and a concise explanation. If the requirements are unclear, include an appropriate error message in the JSON response.\n\n---\n\n# Examples\n- **What’s the weather in Vancouver right now?**\n  ```json\n  {\n    \"model\": \"gpt-5-mini\",\n    \"explanation\": \"Quick tool lookup; simple enough for a fast model.\"\n  }\n  ```\n\n- **Compare the newest M3 laptops and cite sources.**\n  ```json\n  {\n    \"model\": \"gpt-5\",\n    \"explanation\": \"Research and synthesis with tools requires reasoning depth.\"\n  }\n  ```\n\n- **Summarize this email draft and make it more formal.**\n  ```json\n  {\n    \"model\": \"gpt-5-chat-latest\",\n    \"explanation\": \"Polishing text only; no tools needed.\"\n  }\n  ```\n\n- **Summarize this uploaded PDF into bullet points.**\n  ```json\n  {\n    \"model\": \"gpt-5\",\n    \"explanation\": \"Document parsing may require tools; complex enough for gpt-5.\"\n  }\n  ```\n\n- **Translate this paragraph into Spanish.**\n  ```json\n  {\n    \"model\": \"gpt-5-chat-latest\",\n    \"explanation\": \"Simple translation; tools not required.\"\n  }\n  ```\n\n- **List my upcoming meetings tomorrow.**\n  ```json\n  {\n    \"model\": \"gpt-5-mini\",\n    \"explanation\": \"Calendar tool lookup is simple; mini is efficient.\"\n  }\n  ```",
            "input": responses_body.input,
            "prompt_cache_key": "openai_responses_gpt5-router",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "gpt5_router",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "model": {
                                "type": "string",
                                "enum": ["gpt-5-chat-latest", "gpt-5", "gpt-5-mini"],
                                "description": "The selected GPT-5 model from the available options."
                            },
                            "reasoning_effort": {
                                "type": "string",
                                "enum": [
                                    "minimal",
                                    "low",
                                    "medium",
                                    "high"
                                ],
                                "description": "The estimated amount of reasoning effort required for the request."
                            },
                            "explanation": {
                                "type": "string",
                                "description": "Short 3-5 word rationale for why this model was selected.",
                                "minLength": 3,
                                "maxLength": 500
                            },
                        },
                        "required": [
                        "model",
                        "explanation",
                        "reasoning_effort"
                        ],
                        "additionalProperties": False
                    },
                    "verbosity": "medium",
                },
            }
        }
        # -------------------------------------------------

        try:
            response = await self.send_openai_responses_nonstreaming_request(
                router_body,
                api_key=valves.API_KEY,
                base_url=valves.BASE_URL,
            )
        except Exception as exc:  # pragma: no cover
            self.logger.warning("GPT-5 router request failed: %s", exc)
            return responses_body

        # Simple shape: output[0].content[0].text
        try:
            text = next((b["text"] for o in reversed(response["output"]) if o["type"]=="message" for b in o["content"] if b["type"]=="output_text"), "")
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Router response missing expected fields: %s; payload keys=%s",
                                exc, list(response.keys()))
            return responses_body

        # Parse JSON (with a tiny fallback to the first {...} block)
        try:
            router_json: Dict[str, Any] = json.loads(text)
        except Exception:
            start, end = text.find("{"), text.rfind("}")
            router_json = json.loads(text[start:end+1]) if start != -1 and end != -1 and end > start else {}

        if router_json:
            responses_body.model = router_json.get("model")
            if ModelFamily.supports("reasoning", responses_body.model):
                reasoning = dict(responses_body.reasoning or {})
                reasoning["effort"] = router_json.get("reasoning_effort")
                responses_body.reasoning = reasoning

            responses_body.model_router_result = router_json
        return responses_body

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
# 5. Utility & Helper Layer (organized, consistent docstrings)
#    NOTE: Logic is unchanged. Only docstrings/comments/sectioning were improved.
# ─────────────────────────────────────────────────────────────────────────────

# 5.1 Logging & Diagnostics
# -------------------------

class SessionLogger:
    """Per-request logger that captures console output and an in-memory log buffer.

    The logger is bound to a logical *session* via contextvars so that log lines
    can be collected and emitted (e.g., as citations) for the current request.

    Attributes:
        session_id: ContextVar storing the current logical session ID.
        log_level:  ContextVar storing the minimum level to emit for this session.
        logs:       Map of session_id -> fixed-size deque of formatted log strings.
    """

    session_id = ContextVar("session_id", default=None)
    log_level = ContextVar("log_level", default=logging.INFO)
    logs = defaultdict(lambda: deque(maxlen=2000))

    @classmethod
    def get_logger(cls, name=__name__):
        """Create a logger wired to the current SessionLogger context.

        Args:
            name: Logger name; defaults to the current module name.

        Returns:
            logging.Logger: A configured logger that writes both to stdout and
            the in-memory `SessionLogger.logs` buffer. The buffer is keyed by
            the current `SessionLogger.session_id`.
        """
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Single combined filter: attach session_id and respect per-session level.
        def filter(record):
            record.session_id = cls.session_id.get()
            return record.levelno >= cls.log_level.get()

        logger.addFilter(filter)

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(levelname)s] [%(session_id)s] %(message)s"))
        logger.addHandler(console)

        # Memory handler (appends formatted lines into logs[session_id])
        mem = logging.Handler()
        mem.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        mem.emit = lambda r: cls.logs[r.session_id].append(mem.format(r)) if r.session_id else None
        logger.addHandler(mem)

        return logger


# ─────────────────────────────────────────────────────────────────────────────
# 6. Framework Integration Helpers (Open WebUI DB operations)
# ─────────────────────────────────────────────────────────────────────────────

async def persist_openai_response_items(
    chat_id: str,
    message_id: str,
    items: List[Dict[str, Any]],
    openwebui_model_id: str,
) -> str:
    """Persist response items to the chat record and return marker strings.

    Each item is stored under the chat's `openai_responses_pipe.items` map and
    indexed by `messages_index[message_id].item_ids`. For each stored item, a
    hidden, empty-link marker is returned so it can be embedded into assistant
    text and later resolved by ID.

    Args:
        chat_id:            Chat identifier used to locate the conversation.
        message_id:         The assistant message ID the items belong to.
        items:              Sequence of payloads to store (tool calls, reasoning, etc.).
        openwebui_model_id: Fully qualified model ID the items originate from.

    Returns:
        str: Concatenated hidden markers (empty-link encoded ULIDs). Returns an
        empty string if nothing was persisted or the chat is missing.

    Notes:
        The storage layout is:
            chat.chat["openai_responses_pipe"] = {
                "__v": 3,
                "items":         {<ulid>: {"model":..., "created_at":..., "payload":..., "message_id":...}},
                "messages_index":{<message_id>: {"role":"assistant","done":True,"item_ids":[<ulid>, ...]}}
            }
    """
    if not items:
        return ""

    chat_model = Chats.get_chat_by_id(chat_id)
    if inspect.iscoroutine(chat_model):
        chat_model = await chat_model
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
# 7. General-Purpose Utilities (data transforms & patches)
# ─────────────────────────────────────────────────────────────────────────────

def _wrap_event_emitter(
    emitter: Callable[[Dict[str, Any]], Awaitable[None]] | None,
    *,
    suppress_chat_messages: bool = False,
    suppress_completion: bool = False,
):
    """
    Wrap the given event emitter and optionally suppress specific event types.

    Use-case: reuse the streaming loop for non-stream requests by swallowing
    incremental 'chat:message' frames while allowing status/citation/usage
    events through.
    """
    if emitter is None:
        async def _noop(_event: Dict[str, Any]) -> None:
            return

        return _noop

    async def _wrapped(event: Dict[str, Any]) -> None:
        etype = (event or {}).get("type")
        if suppress_chat_messages and etype == "chat:message":
            return  # swallow incremental deltas
        if suppress_completion and etype == "chat:completion":
            return  # optionally swallow completion frames
        await emitter(event)

    return _wrapped

def merge_usage_stats(total, new):
    """Recursively merge nested usage statistics.

    For numeric values, sums are accumulated; for dicts, the function recurses;
    other values overwrite the prior value when non-None.

    Args:
        total: Accumulator dictionary to update.
        new:   Newly reported usage block to merge into `total`.

    Returns:
        dict: The updated accumulator dictionary (`total`).
    """
    for k, v in new.items():
        if isinstance(v, dict):
            total[k] = merge_usage_stats(total.get(k, {}), v)
        elif isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        else:
            total[k] = v if v is not None else total.get(k, 0)
    return total


def resolve_model_pricing(model_id: str, custom_pricing_json: str | None = None) -> Optional[Dict[str, float]]:
    """Resolve USD-per-1M-token rates for a model.

    Valve-provided overrides (CUSTOM_MODEL_PRICING_JSON) take precedence over
    the built-in `ModelFamily._PRICING` table. Returns None when the model is
    unknown, in which case no cost is reported.
    """
    if custom_pricing_json:
        with contextlib.suppress(Exception):
            overrides = json.loads(custom_pricing_json)
            entry = overrides.get(ModelFamily.base_model(model_id)) or overrides.get(ModelFamily._norm(model_id))
            if isinstance(entry, dict) and "input" in entry and "output" in entry:
                return {
                    "input": float(entry["input"]),
                    "cached_input": float(entry.get("cached_input", entry["input"])),
                    "output": float(entry["output"]),
                }
    return ModelFamily.pricing(model_id)


def estimate_usage_cost(usage: dict[str, Any], pricing: Dict[str, float]) -> dict[str, Any]:
    """Estimate USD cost from a (possibly accumulated) usage block.

    Cached input tokens (a subset of `input_tokens`) are billed at the cached
    rate; the remainder at the full input rate. Costs are estimates based on
    published per-token rates and exclude tool surcharges (e.g. web search).
    """
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cached_tokens = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    cached_tokens = min(cached_tokens, input_tokens)

    input_cost = (input_tokens - cached_tokens) / 1_000_000 * pricing["input"]
    cached_cost = cached_tokens / 1_000_000 * pricing["cached_input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    total = input_cost + cached_cost + output_cost

    return {
        "input_cost": round(input_cost, 6),
        "cached_input_cost": round(cached_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total, 6),
        "currency": "USD",
    }


def wrap_code_block(text: str, language: str = "python") -> str:
    """Wrap text in a fenced Markdown code block.

    The fence length adapts to the longest backtick run within the text to avoid
    prematurely closing the block.

    Args:
        text:     The code or content to wrap.
        language: Markdown fence language tag.

    Returns:
        str: Markdown code block.
    """
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Persistent Item Markers (ULIDs & encoding helpers)
# ─────────────────────────────────────────────────────────────────────────────

# Constants for ULID-like IDs used in hidden markers.
ULID_LENGTH = 16
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Sentinel and compiled regex for detecting embedded markers in assistant text.
_SENTINEL = "[openai_responses:v2:"
_RE = re.compile(
    rf"\[openai_responses:v2:(?P<kind>[a-z0-9_]{{2,30}}):"
    rf"(?P<ulid>[A-Z0-9]{{{ULID_LENGTH}}})(?:\?(?P<query>[^\]]+))?\]:\s*#",
    re.I,
)


def _qs(d: dict[str, str]) -> str:
    """Encode a dict as a simple query-string (no URL-encoding)."""
    return "&".join(f"{k}={v}" for k, v in d.items()) if d else ""


def _parse_qs(q: str) -> dict[str, str]:
    """Parse a simple `a=b&c=d` string into a dict (no URL-decoding)."""
    return dict(p.split("=", 1) for p in q.split("&")) if q else {}


def generate_item_id() -> str:
    """Generate a short ULID-like ID using the Crockford alphabet.

    Returns:
        str: A random uppercase identifier of length `ULID_LENGTH`.
    """
    return ''.join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))


def create_marker(
    item_type: str,
    *,
    ulid: str | None = None,
    model_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """Construct a bare marker payload (no square-bracket wrapping).

    The format is: `openai_responses:v2:<item_type>:<ULID>[?<k=v&...>]`.

    Args:
        item_type:  2–30 chars of `[a-z0-9_]` that describes the item kind.
        ulid:       Optional pre-generated ULID; a new one is created if omitted.
        model_id:   Optional model ID; when provided, recorded in query metadata.
        metadata:   Optional additional metadata appended as `k=v` pairs.

    Returns:
        str: The marker string (without the `[ ... ]: #` wrapper).

    Raises:
        ValueError: If `item_type` does not match `[a-z0-9_]{2,30}`.
    """
    if not re.fullmatch(r"[a-z0-9_]{2,30}", item_type):
        raise ValueError("item_type must be 2-30 chars of [a-z0-9_]")
    meta = {**(metadata or {})}
    if model_id:
        meta["model"] = model_id
    base = f"openai_responses:v2:{item_type}:{ulid or generate_item_id()}"
    return f"{base}?{_qs(meta)}" if meta else base


def wrap_marker(marker: str) -> str:
    """Wrap a marker in an empty link so it is invisible in rendered markdown.

    Args:
        marker: Raw marker string returned by `create_marker()`.

    Returns:
        str: `\n[<marker>]: #\n` so it can be injected into assistant text.
    """
    return f"\n[{marker}]: #\n"


def contains_marker(text: str) -> bool:
    """Fast check: does the text contain any v2 marker sentinel?

    Args:
        text: Text to scan.

    Returns:
        bool: True if the sentinel substring is present; otherwise False.
    """
    return _SENTINEL in text


def parse_marker(marker: str) -> dict:
    """Parse a raw marker string into its components.

    Args:
        marker: Marker string produced by `create_marker()` (no brackets).

    Returns:
        dict: { "version": "v2", "item_type": ..., "ulid": ..., "metadata": {...} }

    Raises:
        ValueError: If the string does not start with `openai_responses:v2:`.
    """
    if not marker.startswith("openai_responses:v2:"):
        raise ValueError("not a v2 marker")
    _, _, kind, rest = marker.split(":", 3)
    uid, _, q = rest.partition("?")
    return {"version": "v2", "item_type": kind, "ulid": uid, "metadata": _parse_qs(q)}


def extract_markers(text: str, *, parsed: bool = False) -> list:
    """Extract all embedded markers from text.

    Args:
        text:   Source text to scan.
        parsed: If True, return parsed dicts; otherwise raw marker strings.

    Returns:
        list: List of markers (raw strings or parsed dicts).
    """
    found = []
    for m in _RE.finditer(text):
        raw = f"openai_responses:v2:{m.group('kind')}:{m.group('ulid')}"
        if m.group("query"):
            raw += f"?{m.group('query')}"
        found.append(parse_marker(raw) if parsed else raw)
    return found


def split_text_by_markers(text: str) -> list[dict]:
    """Split text into a sequence of literal segments and marker segments.

    Args:
        text: Source text possibly containing embedded markers.

    Returns:
        list[dict]: A list like:
            [
              {"type": "text",   "text": "..."},
              {"type": "marker", "marker": "openai_responses:v2:..."},
              ...
            ]
    """
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


async def fetch_openai_response_items(
    chat_id: str,
    item_ids: List[str],
    *,
    openwebui_model_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load persisted items by ULID for a given chat, with optional model filter.

    Only items originating from the current model are returned when
    `openwebui_model_id` is provided. This avoids leaking incompatible artifacts
    (e.g., encrypted reasoning tokens) across models.

    Args:
        chat_id:             Chat identifier used to look up stored items.
        item_ids:            ULIDs previously embedded in the message text.
        openwebui_model_id:  If provided, only return items for this model ID.

    Returns:
        dict: Mapping of `item_id` -> persisted payload dict.
    """
    chat_model = Chats.get_chat_by_id(chat_id)
    if inspect.iscoroutine(chat_model):
        chat_model = await chat_model
    if not chat_model:
        return {}

    items_store = chat_model.chat.get("openai_responses_pipe", {}).get("items", {})
    lookup: Dict[str, Dict[str, Any]] = {}
    for item_id in item_ids:
        item = items_store.get(item_id)
        if not item:
            continue
        # Only include items that match the current model ID (if specified).
        if openwebui_model_id:
            if item.get("model", "") != openwebui_model_id:
                continue
        lookup[item_id] = item.get("payload", {})
    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# 9. Tool & Schema Utilities (internal)
# ─────────────────────────────────────────────────────────────────────────────
def build_tools(
    responses_body: "ResponsesBody",
    valves: "Pipe.Valves",
    __tools__: Optional[Dict[str, Any]] = None,
    *,
    features: Optional[Dict[str, Any]] = None,
    extra_tools: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Build the OpenAI Responses-API tool spec list for this request.

    - Returns [] if the target model doesn't support function calling.
    - Includes Open WebUI registry tools (strictified if enabled).
    - Adds OpenAI web_search (if allowed + supported + not minimal effort).
    - Adds MCP tools from REMOTE_MCP_SERVERS_JSON.
    - Appends any caller-provided extra_tools (already-valid OpenAI tool specs).
    - Deduplicates by (type,name) identity; last one wins.

    NOTE: This builds the *schema* to send to OpenAI. For executing function
    calls at runtime, you can keep passing the raw `__tools__` registry into
    your streaming/non-streaming loops; those functions expect name→callable.
    """
    logger = logging.getLogger(__name__)
    features = features or {}

    # 1) If model can't do function calling, no tools
    if not ModelFamily.supports("function_calling", responses_body.model):
        return []

    tools: List[Dict[str, Any]] = []

    # 2) Baseline: Open WebUI registry tools → OpenAI tool specs
    if isinstance(__tools__, dict) and __tools__:
        tools.extend(
            ResponsesBody.transform_owui_tools(
                __tools__,
                strict=valves.ENABLE_STRICT_TOOL_CALLING,
            )
        )

    # 3) Optional OpenAI web search tool (guarded + not for minimal effort)
    allow_web = (
        ModelFamily.supports("web_search_tool", responses_body.model)
        and (valves.ENABLE_WEB_SEARCH_TOOL or features.get("web_search", False))
        and ((responses_body.reasoning or {}).get("effort", "").lower() != "minimal")
    )
    if allow_web:
        web_search_tool: Dict[str, Any] = {
            "type": "web_search",
            "search_context_size": valves.WEB_SEARCH_CONTEXT_SIZE,
        }
        if valves.WEB_SEARCH_USER_LOCATION:
            try:
                web_search_tool["user_location"] = json.loads(valves.WEB_SEARCH_USER_LOCATION)
            except Exception as exc:  # don't fail the request if user_location is malformed
                logger.warning("WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring: %s", exc)
        tools.append(web_search_tool)

    # 4) Optional MCP servers
    if valves.REMOTE_MCP_SERVERS_JSON:
        tools.extend(ResponsesBody._build_mcp_tools(valves.REMOTE_MCP_SERVERS_JSON))

    # 5) Optional extra tools (already OpenAI-format)
    if isinstance(extra_tools, list) and extra_tools:
        tools.extend(extra_tools)

    return _dedupe_tools(tools)


def _strictify_schema(schema):
    """
    Minimal, predictable transformer to make a JSON schema strict-compatible.

    Rules for every object node (root + nested):
      - additionalProperties := false
      - required := all property keys
      - fields that were optional become nullable (add "null" to their type)

    We traverse properties, items (dict or list), and anyOf/oneOf branches.
    We do NOT rewrite anyOf/oneOf; we only enforce object rules inside them.

    Returns a new dict. Non-dict inputs return {}.
    """
    import json

    if not isinstance(schema, dict):
        return {}

    # Defensive deep copy
    s = json.loads(json.dumps(schema))

    # Ensure root is an object; if not, wrap under {"value": ...}
    root_t = s.get("type")
    if not (root_t == "object" or (isinstance(root_t, list) and "object" in root_t) or "properties" in s):
        s = {
            "type": "object",
            "properties": {"value": s},
            "required": ["value"],
            "additionalProperties": False,
        }

    stack = [s]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue

        # Treat as object if it declares object type or has properties
        t = node.get("type")
        is_object = ("properties" in node) or (t == "object") or (isinstance(t, list) and "object" in t)
        if is_object:
            props = node.get("properties")
            if not isinstance(props, dict):
                props = {}
                node["properties"] = props

            original_required = set(node.get("required") or [])

            # Close object and mark all props required
            node["additionalProperties"] = False
            node["required"] = list(props.keys())

            # Previously-optional → nullable
            for name, p in props.items():
                if not isinstance(p, dict):
                    continue
                if name not in original_required:
                    ptype = p.get("type")
                    if isinstance(ptype, str) and ptype != "null":
                        p["type"] = [ptype, "null"]
                    elif isinstance(ptype, list) and "null" not in ptype:
                        p["type"] = ptype + ["null"]
                stack.append(p)

        # Dive into array schemas
        items = node.get("items")
        if isinstance(items, dict):
            stack.append(items)
        elif isinstance(items, list):  # tuple validation
            for it in items:
                if isinstance(it, dict):
                    stack.append(it)

        # Traverse union branches (no rewrites, just enforce inside)
        for key in ("anyOf", "oneOf"):
            branches = node.get(key)
            if isinstance(branches, list):
                for br in branches:
                    if isinstance(br, dict):
                        stack.append(br)

    return s


def _dedupe_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """(Internal) Deduplicate a tool list with simple, stable identity keys.

    Identity:
      - Function tools → key = ("function", <name>)
      - Non-function tools → key = (<type>, None)

    Later entries win (last write wins).

    Args:
        tools: List of tool dicts (OpenAI Responses schema).

    Returns:
        list: Deduplicated list, preserving only the last occurrence per identity.
    """
    if not tools:
        return []
    canonical: Dict[tuple, Dict[str, Any]] = {}
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") == "function":
            key = ("function", t.get("name"))
        else:
            key = (t.get("type"), None)
        if key[0]:
            canonical[key] = t
    return list(canonical.values())

    # fmt: on
