"""
title: Web Search Toggle Filter
id: web_search_toggle
description: Enable GPT-4o Search Preview when the Web Search toggle is active.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        """Configurable settings for the filter."""

        SEARCH_CONTEXT_SIZE: str = "medium"

    def __init__(self) -> None:
        self.valves = self.Valves()
        # Show a toggle in the UI labelled "Web Search" with a magnifying glass icon
        self.toggle = "Web Search"
        self.icon = (
            "data:image/svg+xml;base64,"
            "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIg"
            "ZmlsbD0ibm9uZSIgc3Ryb2tlPSJjdXJyZW50Q29sb3IiIHN0cm9rZS13aWR0aD0iMiI+PGNpcmNsZSBj"
            "eD0iMTEiIGN5PSIxMSIgcj0iOCIvPjxsaW5lIHgxPSIyMSIgeTE9IjIxIiB4Mj0iMTYuNjUiIHkyPSIx"
            "Ni42NSIvPjwvc3ZnPg=="
        )

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Optional[callable] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        """Modify the request body when the toggle is active."""

        features = body.setdefault("features", {})

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "\ud83d\udd0d Web search detected \u2014 rerouting to GPT-4o Search Preview...",
                        "done": False,
                        "hidden": False,
                    },
                }
            )

        # \U0001f9e0 Override native search and explicitly set GPT-4o route
        features["web_search"] = False
        body["model"] = "gpt-4o-search-preview"

        metadata = __metadata__ or {}
        timezone = metadata.get("variables", {}).get(
            "{{CURRENT_TIMEZONE}}", "America/Vancouver"
        )

        body["web_search_options"] = {
            "user_location": {
                "type": "approximate",
                "approximate": {"country": "CA", "timezone": timezone},
            },
            "search_context_size": self.valves.SEARCH_CONTEXT_SIZE.lower(),
        }

        return body
