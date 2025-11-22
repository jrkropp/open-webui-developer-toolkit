"""Domain logic for the OpenAI Responses manifold.

This package hosts history management, tool orchestration, routing,
and the responses engine. Shared domain types are exported here for
convenient reuse by adapters and tests.
"""

from .history import HistoryManager, HistoryStore
from .tools import ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry
from .web_search import build_web_search_tools
from .code_interpreter import (
    emit_pending_code_interpreter_result,
    handle_code_interpreter_event,
    handle_code_interpreter_item,
)
from .routing import route_auto_model
from .engine import ResponsesEngine
from .types import (
    Citation,
    RuntimeEvents,
    ToolCall,
    ToolResult,
    TurnContext,
    TurnResult,
    TurnState,
)

__all__ = [
    "Citation",
    "HistoryManager",
    "HistoryStore",
    "ResponsesEngine",
    "ToolDefinition",
    "ToolExecutor",
    "ToolPolicy",
    "ToolRegistry",
    "build_web_search_tools",
    "emit_pending_code_interpreter_result",
    "handle_code_interpreter_event",
    "handle_code_interpreter_item",
    "route_auto_model",
    "RuntimeEvents",
    "ToolCall",
    "ToolResult",
    "TurnContext",
    "TurnResult",
    "TurnState",
]
