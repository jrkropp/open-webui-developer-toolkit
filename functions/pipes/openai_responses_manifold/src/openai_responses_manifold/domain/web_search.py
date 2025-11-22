"""Web search tool construction helpers.

See ``docs/web_search_and_citations.md`` for the behavioral contract.
"""

from __future__ import annotations

import json
from typing import Any

from openai_responses_manifold.core.config import RuntimeConfig
from openai_responses_manifold.core.logging import get_logger
from openai_responses_manifold.core.model_catalog import supports

_logger = get_logger(__name__)


def build_web_search_tools(
    model_id: str,
    features: set[str],
    cfg: RuntimeConfig,
    reasoning_effort: str | None = None,
) -> list[dict[str, Any]]:
    """Return a ``web_search`` tool definition when enabled.

    The tool is included only when:
    * The model advertises ``web_search_tool`` capability.
    * Web search is enabled via valves.
    * The effective reasoning effort is not explicitly ``"minimal"``.
    """

    allow_web_search = "web_search_tool" in features or supports(
        "web_search_tool", model_id
    )
    if not allow_web_search:
        return []

    if reasoning_effort == "minimal":
        return []

    if not cfg.ENABLE_WEB_SEARCH_TOOL:
        return []

    tool: dict[str, Any] = {
        "type": "web_search",
        "search_context_size": cfg.WEB_SEARCH_CONTEXT_SIZE,
    }

    if cfg.WEB_SEARCH_USER_LOCATION:
        try:
            tool["user_location"] = json.loads(cfg.WEB_SEARCH_USER_LOCATION)
        except Exception:
            _logger.warning("WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring.")

    return [tool]


__all__ = ["build_web_search_tools"]
