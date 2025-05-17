"""
title: Turn Limit Filter
id: turn_limit_filter
description: Blocks conversations that exceed a configurable turn limit.
author: open-webui
license: MIT
version: 0.0.0
"""

from typing import Awaitable, Callable

from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        priority: int = Field(0, description="Filter execution priority")
        max_turns: int = Field(8, description="Maximum turns for any user")

    class UserValves(BaseModel):
        max_turns: int = Field(4, description="User specific turn limit")

    def __init__(self) -> None:
        self.valves = self.Valves()

    def inlet(
        self,
        body: dict,
        __user__: dict | None = None,
        __event_emitter__: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        turns = len(body.get("messages", []))
        user_limit = self.valves.max_turns
        if __user__ and __user__.get("valves"):
            user_limit = min(
                getattr(__user__["valves"], "max_turns", user_limit), user_limit
            )
        if turns > user_limit:
            if __event_emitter__:
                __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "message": "Turn limit reached",
                            "done": True,
                        },
                    }
                )
            raise Exception(f"Conversation turn limit exceeded. Max turns: {user_limit}")
        return body

