"""Shared turn-level context passed across engine, tools, and history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai_responses_manifold.config.settings import PipeValves


@dataclass
class TurnContext:
    valves: PipeValves
    metadata: dict[str, Any]
    user_identifier: str | None
    owui_model_id: str
    features: dict[str, Any]


__all__ = ["TurnContext"]
