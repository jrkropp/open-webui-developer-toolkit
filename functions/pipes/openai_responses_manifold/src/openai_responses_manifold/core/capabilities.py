"""Model capability registry described in the Developer Guide v2."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..model_catalog import EMPTY_FEATURES, MODEL_ALIASES, MODEL_FEATURES
from .ids import base_model, normalize


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
    "MODEL_ALIASES",
    "MODEL_FEATURES",
    "alias_defaults",
    "features",
    "supports",
]
