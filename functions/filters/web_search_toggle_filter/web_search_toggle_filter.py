"""
title: Web Search
id: web_search_toggle_filter
description: Instruct the model to search the web for the latest information.
required_open_webui_version: 0.6.10
version: 0.3.0

Note: Designed to work with the OpenAI Responses manifold
      https://github.com/jrkropp/open-webui-developer-toolkit/tree/main/functions/pipes/openai_responses_manifold
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

# Models that already include the native web_search tool
WEB_SEARCH_MODELS = {
    "openai_responses.gpt-4.1",
    "openai_responses.gpt-4.1-mini",
    "openai_responses.gpt-4o",
    "openai_responses.gpt-4o-mini",
    "openai_responses.o3",
    "openai_responses.o4-mini",
    "openai_responses.o4-mini-high",
    "openai_responses.o3-pro",
    "openai_responses.gpt-5",
    "openai_responses.gpt-5-mini",
    "openai_responses.gpt-5-high",
}

SUPPORT_TOOL_CHOICE_PARAMETER = {
    "openai_responses.gpt-4.1",
    "openai_responses.gpt-4.1-mini",
    "openai_responses.gpt-4o",
    "openai_responses.gpt-4o-mini",
}

class Filter:
    # ── User‑configurable knobs (valves) ──────────────────────────────
    class Valves(BaseModel):
        SEARCH_CONTEXT_SIZE: str = "medium"
        DEFAULT_SEARCH_MODEL: str = "openai_responses.gpt-4o"
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

        # Toggle icon shown in the WebUI
        self.toggle = True
        self.icon = (
            "data:image/svg+xml;base64,"
            "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgZmlsbD0ibm9uZSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj4KICA8Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSIxMCIvPgogIDxsaW5lIHgxPSIyIiB5MT0iMTIiIHgyPSIyMiIgeTI9IjEyIi8+CiAgPHBhdGggZD0iTTEyIDJhMTUgMTUgMCAwIDEgMCAyMCAxNSAxNSAwIDAgMSAwLTIweiIvPgo8L3N2Zz4="
        )

    # ─────────────────────────────────────────────────────────────────
    # 1.  INLET – choose the right model, disable WebUI’s own search
    # ─────────────────────────────────────────────────────────────────
    async def inlet(
        self,
        body: Dict[str, Any],
        __event_emitter__: Optional[callable] = None,
        __metadata__: Optional[dict] = None,
    ) -> Dict[str, Any]:
        
        # 0) Turn off WebUI’s own (legacy) search toggle; we’ll manage tools ourselves.
        if __metadata__:
            __metadata__.setdefault("features", {}).update({"web_search": False})

        # 1) Ensure we’re on a search-capable model
        if body.get("model") not in WEB_SEARCH_MODELS:
            body["model"] = self.valves.DEFAULT_SEARCH_MODEL

        # 2) Add OpenAI’s web-search tool via extra_tools (as-is; manifold will append & strip)
        #    You can later switch "web_search" -> "web_search" when you migrate.
        body.setdefault("extra_tools", []).append({
            "type": "web_search",
            "search_context_size": self.valves.SEARCH_CONTEXT_SIZE
            # Optionally include user_location when you have one:
            # "user_location": {"type": "approximate", "country": "CA", "region": "BC", "city": "Langley"}
        })

        # 3) (Optional) Nudge/force usage:
        #    If the model supports tool_choice for web_search, you can force it;
        #    otherwise add a gentle developer reminder.
        if body.get("model") in SUPPORT_TOOL_CHOICE_PARAMETER:
            body["tool_choice"] = {"type": "web_search"}  # keep if GA; otherwise leave unset
        else:
            body.setdefault("messages", []).append({
                "role": "developer",
                "content": (
                    "Web search is enabled. Use the `web_search` tool whenever you need fresh information."
                )
            })

        return body

