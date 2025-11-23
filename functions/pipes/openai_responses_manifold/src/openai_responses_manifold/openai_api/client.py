"""Thin aiohttp-based client for the OpenAI Responses API."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import aiohttp

from .types import (
    ResponseEvent,
    ResponsesRequest,
    dump_responses_request,
    parse_responses_event,
    validate_responses_request,
)


class OpenAIClient:
    """HTTP client for the OpenAI Responses API."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def stream_responses(
        self,
        request: ResponsesRequest | dict[str, Any],
        *,
        base_url: str,
        api_key: str,
    ) -> AsyncIterator[ResponseEvent]:
        session = await self._get_session()
        url = f"{base_url.rstrip('/')}/responses"
        payload = dump_responses_request(validate_responses_request(request))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.content.iter_any():
                buffer += chunk.decode()
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    data = _extract_data(raw)
                    if data is None:
                        continue
                    event_payload = json.loads(data)
                    yield parse_responses_event(event_payload)

    async def create_response(
        self,
        request: ResponsesRequest | dict[str, Any],
        *,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{base_url.rstrip('/')}/responses"
        payload = dump_responses_request(validate_responses_request(request))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()


def _extract_data(raw: str) -> str | None:
    lines = raw.splitlines()
    data_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    return "\n".join(data_lines)


__all__ = ["OpenAIClient"]
