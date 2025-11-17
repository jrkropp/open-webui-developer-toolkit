"""Compatibility shim: import capability helpers from model_catalog."""

from __future__ import annotations

from ..model_catalog import (
    EMPTY_FEATURES,
    MODEL_ALIASES,
    MODEL_FEATURES,
    alias_defaults,
    features,
    supports,
)

__all__ = [
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "alias_defaults",
    "features",
    "supports",
    "EMPTY_FEATURES",
]
