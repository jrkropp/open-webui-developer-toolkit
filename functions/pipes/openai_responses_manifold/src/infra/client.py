"""HTTP client for interacting with the OpenAI Responses endpoint."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp


class OpenAIResponsesClient:
    """Thin wrapper around ``aiohttp`` that streams Responses API events."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._logger = logging.getLogger(__name__)

    async def stream_events(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE events as soon as they arrive."""

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"

        buf = bytearray()
        async with session.post(url, json=request_body, headers=headers) as resp:
            resp.raise_for_status()

            async for chunk in resp.content.iter_chunked(4096):
                buf.extend(chunk)
                start_idx = 0
                while True:
                    newline_idx = buf.find(b"\n", start_idx)
                    if newline_idx == -1:
                        break
                    line = buf[start_idx:newline_idx].strip()
                    start_idx = newline_idx + 1
                    if not line or line.startswith(b":") or not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        return
                    yield json.loads(payload.decode("utf-8"))
                if start_idx > 0:
                    del buf[:start_idx]

    async def request(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
    ) -> dict[str, Any]:
        """Send a non-streaming Responses API request."""

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"
        async with session.post(url, json=request_body, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self) -> None:
        """Close the underlying client session."""

        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_or_init_http_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            self._logger.debug("Reusing existing aiohttp session")
            return self._session

        connector = aiohttp.TCPConnector(
            limit=50,
            limit_per_host=10,
            keepalive_timeout=75,
            ttl_dns_cache=300,
        )
        timeout = aiohttp.ClientTimeout(
            connect=30,
            sock_connect=30,
            sock_read=3600,
        )
        self._logger.debug("Creating new aiohttp session")
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            json_serialize=json.dumps,
        )
        return self._session
