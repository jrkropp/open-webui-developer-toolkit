"""
title: Filter Template
id: filter_template
description: Demonstrates inlet/outlet hooks and per-user valves.
author: suurt8ll
author_url: https://github.com/suurt8ll
funding_url: https://github.com/suurt8ll/open_webui_functions
version: 0.0.0
"""

import json
from pydantic import BaseModel, Field
from typing import Any, Awaitable, Callable


class Filter:

    # Set this to True if you want to manage file uploads yourself
    # file_handler = True

    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Execution priority. Lower runs first."
        )
        max_turns: int = Field(
            default=8, description="Maximum conversation turns allowed."
        )

    class UserValves(BaseModel):
        max_turns: int = Field(
            default=4, description="User specific turn limit."
        )

    def __init__(self):
        self.valves = self.Valves()
        print(f"{[__name__]} Function has been initialized.")

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        """Run before the request is sent to the LLM."""

        print("\n--- Inlet Filter ---")
        print(f"{[__name__]} Original Request Body:")
        print(json.dumps(body, indent=2, default=str))

        if __user__:
            user_valves = getattr(__user__.get("valves"), "max_turns", self.valves.max_turns)
            max_turns = min(user_valves, self.valves.max_turns)
            if len(body.get("messages", [])) > max_turns:
                raise Exception(f"Conversation turn limit exceeded. Max turns: {max_turns}")

        return body

    async def stream(self, event: dict[str, Any]) -> dict[str, Any]:
        # print(f"\n--- Stream Filter ---")
        # print("Event Object:")
        # print(json.dumps(event, indent=2, default=str))
        return event

    async def outlet(
        self, body: dict, __event_emitter__: Callable[[dict], Awaitable[None]]
    ) -> dict:
        """Run after the LLM produced a response."""

        print("\n--- Outlet Filter ---")
        print(f"{[__name__]} Original Response Body:")
        print(json.dumps(body, indent=2, default=str))

        # Example: inject additional text
        body["messages"][-1]["content"] = "Filtered by outlet"

        print(f"{[__name__]} Modified Response Body:")
        print(json.dumps(body, indent=2, default=str))

        await __event_emitter__({"type": "status", "data": {"message": "Outlet done"}})

        return body

    # region ----- Helper methods inside the Pipe class -----

    # endregion

