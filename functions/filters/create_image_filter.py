"""
title: Create an Image
id: create_image_filter
description: Injects the image_generation tool with configurable size and quality.
"""

from __future__ import annotations

from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        SIZE: str = "auto"
        QUALITY: str = "auto"

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.toggle = True
        self.icon = (
            "data:image/svg+xml;base64,"
            "PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHBhdGggZmlsbD0ibm9uZSIgc3Ryb2tlPSJjdXJyZW50Q29sb3IiIHN0cm9rZS13aWR0aD0iMiIgZD0iTTIgNmg0bDYtN2g0bDggOHY5SDJ6Ii8+PC9zdmc+"
        )

    def _add_image_generation_tool(self, body: dict) -> None:
        entry = {
            "type": "image_generation",
            "size": self.valves.SIZE,
            "quality": self.valves.QUALITY,
        }
        tools = body.setdefault("tools", [])
        if not any(t.get("type") == "image_generation" for t in tools):
            tools.append(entry)

    async def inlet(self, body: dict, **_kwargs) -> dict:
        self._add_image_generation_tool(body)
        return body
