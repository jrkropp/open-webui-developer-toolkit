"""Open WebUI integration layer for the OpenAI Responses manifold.

Adapters in this package connect the domain layer to Open WebUI models,
events, and tool registries.
"""

from .bridge import build_mcp_tools, build_turn_context, map_completions_to_responses
from .events import OpenWebUIRuntimeEvents
from .store import OpenWebUIHistoryStore
from .tools import OpenWebUIToolExecutor, OpenWebUIToolRegistry

__all__ = [
    "build_turn_context",
    "map_completions_to_responses",
    "build_mcp_tools",
    "OpenWebUIRuntimeEvents",
    "OpenWebUIHistoryStore",
    "OpenWebUIToolRegistry",
    "OpenWebUIToolExecutor",
]
