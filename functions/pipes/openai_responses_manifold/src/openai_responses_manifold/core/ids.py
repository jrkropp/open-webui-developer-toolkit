"""Model identifier normalization helpers (prefix/dot/date safe)."""

from __future__ import annotations

import re
from typing import Mapping

from ..model_catalog import MODEL_ALIASES, MODEL_FEATURES

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


__all__ = ["base_model", "normalize"]
