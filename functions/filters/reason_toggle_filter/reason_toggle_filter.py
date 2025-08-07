"""
title: Reason
id: reason_filter
description: Think before responding.
git_url: https://github.com/jrkropp/open-webui-developer-toolkit.git
required_open_webui_version: 0.6.10
version: 0.3.1
"""

from __future__ import annotations
from typing import Any, Awaitable, Callable, Literal
from pydantic import BaseModel, Field
from open_webui.models.models import Models

class Filter:
    class Valves(BaseModel):
        MODEL: str = "o4-mini"
        REASONING_EFFORT: Literal["minimal", "low", "medium", "high", "not set"] = "not set"
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.toggle = True
        self.icon = "data:image/svg+xml;base64,PHN2ZyBmaWxsPSJub25lIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgY2xhc3M9ImgtWzE4cHldIHctWzE4cHldIj48cGF0aCBkPSJtMTIgM2MtMy41ODUgMC02LjUgMi45MjI1LTYuNSA2LjUzODUgMCAyLjI4MjYgMS4xNjIgNC4yOTEzIDIuOTI0OCA1LjQ2MTVoNy4xNTA0YzEuNzYyOC0xLjE3MDIgMi45MjQ4LTMuMTc4OSAyLjkyNDgtNS40NjE1IDAtMy42MTU5LTIuOTE1LTYuNTM4NS02LjUtNi41Mzg1em0yLjg2NTMgMTRoLTUuNzMwNnYxaDUuNzMwNnYtMXptLTEuMTMyOSAzSC03LjQ2NDhjMC4zNDU4IDAuNTk3OCAwLjk5MjEgMSAxLjczMjQgMXMxLjM4NjYtMC40MDIyIDEuNzMyNC0xem0tNS42MDY0IDBjMC40NDQwMyAxLjcyNTIgMi4wMTAxIDMgMy44NzQgM3MzLjQzLTEuMjc0OCAzLjg3NC0zYzAuNTQ4My0wLjAwNDcgMC45OTEzLTAuNDUwNiAwLjk5MTMtMXYtMi40NTkzYzIuMTk2OS0xLjU0MzEgMy42MzQ3LTQuMTA0NSAzLjYzNDctNy4wMDIyIDAtNC43MTA4LTMuODAwOC04LjUzODUtOC41LTguNTM4NS00LjY5OTIgMC04LjUgMy44Mjc2LTguNSA4LjUzODUgMCAyLjg5NzcgMS40Mzc4IDUuNDU5MSAzLjYzNDcgNy4wMDIydjIuNDU5M2MwIDAuNTQ5NCAwLjQ0MzAxIDAuOTk1MyAwLjk5MTI4IDF6IiBjbGlwLXJ1bGU9ImV2ZW5vZGQiIGZpbGw9ImN1cnJlbnRDb2xvciIgZmlsbC1ydWxlPSJldmVub2RkIj48L3BhdGg+PC9zdmc+"

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __metadata__: dict | None = None,
    ) -> dict:
        """
        Inlet: Modify the incoming request by setting the model, adding metadata, and optional reasoning effort.
        """

        # Update model in body so downstream pipe knows which model to use
        body["model"] = self.valves.MODEL

        # Set __metadata__ for downstream pipes
        model_info = Models.get_model_by_id(self.valves.MODEL)
        if __metadata__ and model_info:
            __metadata__["model"] = model_info.model_dump()

        effort = self.valves.REASONING_EFFORT
        if effort != "not set":
            body["reasoning_effort"] = effort

        # Pass the updated request body downstream
        return body


    async def outlet(
        self,
        body: dict,
        __metadata__: dict | None = None,
    ) -> dict:
        """
        Outlet: Finalize the response by setting necessary UI-related fields.
        Note:
            1) event emitters are not available here.
            2) the body in the outlet is DIFFERENT from the inlet body.
            Read more here: https://github.com/jrkropp/open-webui-developer-toolkit/blob/development/functions/filters/README.md
        """

        # Ensure the final assistant message has correct model fields for frontend display
        messages = body.get("messages")
        if isinstance(messages, list) and messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                last_msg["model"] = self.valves.MODEL
                last_msg.setdefault("modelName", self.valves.MODEL)

        # Return the finalized response body ready for the UI
        return body
