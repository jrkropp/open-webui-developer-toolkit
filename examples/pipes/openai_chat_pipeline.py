"""
title: OpenAI Chat Pipeline
id: openai_chat_pipeline
description: Minimal pipeline calling the OpenAI chat completions API.
author: open-webui
license: MIT
version: 0.0.0
requirements: requests
"""

from __future__ import annotations

import os
from typing import Any, AsyncGenerator, Awaitable, Callable, Generator, Iterator

import requests
from fastapi import Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse


class Pipe:
    class Valves(BaseModel):
        OPENAI_API_BASE_URL: str = Field(
            "https://api.openai.com/v1", description="Base URL for the OpenAI API"
        )
        OPENAI_API_KEY: str = Field(
            default_factory=lambda: os.getenv("OPENAI_API_KEY", ""),
            description="API key used for authentication",
        )
        MODEL_ID: str = Field(
            "gpt-3.5-turbo", description="Model used when sending chat completions"
        )

    class UserValves(BaseModel):
        SYSTEM_INSTRUCTIONS: str | None = Field(
            default=None, description="Extra system instructions"
        )
        STREAM: bool = Field(
            default=False,
            description="Enable server-sent events from the OpenAI API",
        )

    def __init__(self) -> None:
        # Uncomment to handle file uploads manually
        # self.file_handler = True

        self.valves = self.Valves()
        self.pipes = [{"id": self.valves.MODEL_ID, "name": self.valves.MODEL_ID}]

    async def pipes(self) -> list[dict[str, str]]:
        return self.pipes

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict,
        __request__: Request,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]],
        __task__: str,
        __task_body__: dict[str, Any],
        __files__: list[dict[str, Any]],
        __metadata__: dict[str, Any],
        __tools__: list[Any],
    ) -> (
        str
        | dict[str, Any]
        | StreamingResponse
        | Iterator
        | AsyncGenerator
        | Generator
        | None
    ):
        system = getattr(__user__.get("valves"), "SYSTEM_INSTRUCTIONS", None)
        if system:
            body.setdefault("messages", []).insert(0, {"role": "system", "content": system})

        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {**body, "model": self.valves.MODEL_ID}

        streaming = getattr(__user__.get("valves"), "STREAM", False) or body.get("stream")

        resp = requests.post(
            f"{self.valves.OPENAI_API_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            stream=streaming,
        )
        resp.raise_for_status()

        if streaming:
            async def gen() -> AsyncGenerator[str, None]:
                await __event_emitter__({"type": "status", "data": {"message": "stream-start"}})
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = line.decode()
                    await __event_emitter__(
                        {"type": "message", "data": {"content": chunk}}
                    )
                    yield chunk
                await __event_emitter__(
                    {"type": "status", "data": {"message": "stream-end", "done": True}}
                )

            return StreamingResponse(gen(), media_type="text/event-stream")

        return resp.json()

