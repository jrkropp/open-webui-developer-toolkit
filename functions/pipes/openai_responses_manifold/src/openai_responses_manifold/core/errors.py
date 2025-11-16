"""Typed exceptions referenced throughout the manifold."""

from __future__ import annotations


class ManifoldError(Exception):
    """Base class for manifold-specific exceptions."""


class ToolExecutionError(ManifoldError):
    """Raised when a tool invocation fails."""


class RoutingError(ManifoldError):
    """Raised when an automatic model routing step fails."""


class OpenAIStreamError(ManifoldError):
    """Raised when streaming events from OpenAI encounters a fatal error."""


class PersistenceError(ManifoldError):
    """Raised when items fail to persist or resolve."""


__all__ = [
    "ManifoldError",
    "OpenAIStreamError",
    "PersistenceError",
    "RoutingError",
    "ToolExecutionError",
]
