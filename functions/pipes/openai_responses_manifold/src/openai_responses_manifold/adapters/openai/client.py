"""aiohttp-backed client for the OpenAI Responses API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import logging
from pydantic import BaseModel

from openai_responses_manifold.core.logging import get_logger, truncate_for_log
from openai_responses_manifold.adapters.openai.events import StreamEvent, parse_event


class OpenAIResponsesClient:
    """Thin wrapper around ``aiohttp`` with SDK-like method names."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._logger = get_logger(__name__)

    async def stream(
        self,
        request_body: dict[str, Any] | BaseModel,
        *,
        api_key: str,
        base_url: str,
        typed: bool = False,
    ) -> AsyncIterator[StreamEvent | dict[str, Any]]:
        """Yield SSE events from ``POST /responses``.

        Set ``typed=True`` to parse each payload into a structured ``StreamEvent``.
        """

        payload = (
            request_body.model_dump(exclude_none=True)
            if isinstance(request_body, BaseModel)
            else request_body
        )

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"
        if self._logger.isEnabledFor(logging.DEBUG):  # type: ignore[attr-defined]
            input_items = payload.get("input") or []
            instructions = payload.get("instructions") or ""
            self._logger.debug(
                "Streaming request prepared model=%s input_items=%d instructions_len=%d",
                payload.get("model"),
                len(input_items) if isinstance(input_items, list) else 0,
                len(instructions) if isinstance(instructions, str) else 0,
            )
            try:
                trimmed = dict(payload)
                if "instructions" in trimmed:
                    trimmed["instructions"] = f"<omitted len={len(instructions) if isinstance(instructions, str) else 0}>"
                payload_str = json.dumps(trimmed, ensure_ascii=False)
                preview, truncated = truncate_for_log(payload_str, limit=300)
                self._logger.debug(
                    "request.payload_preview enabled=true truncated=%s len=%d payload=%s",
                    truncated,
                    len(payload_str),
                    preview,
                )
            except Exception:
                pass

        buf = bytearray()
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status >= 400:
                await self._log_and_raise(resp, kind="streaming")

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
                    evt: dict[str, Any] = json.loads(payload.decode("utf-8"))
                    if typed:
                        try:
                            yield parse_event(evt)
                            continue
                        except Exception as exc:
                            preview, truncated = truncate_for_log(json.dumps(evt, ensure_ascii=False), 400)
                            self._logger.error(
                                "Failed to parse streaming event type=%s truncated=%s payload=%s error=%s",
                                evt.get("type"),
                                truncated,
                                preview,
                                exc,
                            )
                            raise
                    yield evt
                if start_idx > 0:
                    del buf[:start_idx]

    async def create(
        self,
        request_body: dict[str, Any] | BaseModel,
        *,
        api_key: str,
        base_url: str,
    ) -> dict[str, Any]:
        """Send a non-streaming request to ``POST /responses``."""

        payload = (
            request_body.model_dump(exclude_none=True)
            if isinstance(request_body, BaseModel)
            else request_body
        )

        session = await self._get_or_init_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"
        if self._logger.isEnabledFor(logging.DEBUG):  # type: ignore[attr-defined]
            input_items = payload.get("input") or []
            instructions = payload.get("instructions") or ""
            self._logger.debug(
                "Non-streaming request prepared model=%s input_items=%d instructions_len=%d",
                payload.get("model"),
                len(input_items) if isinstance(input_items, list) else 0,
                len(instructions) if isinstance(instructions, str) else 0,
            )
            try:
                trimmed = dict(payload)
                if "instructions" in trimmed:
                    trimmed["instructions"] = f"<omitted len={len(instructions) if isinstance(instructions, str) else 0}>"
                payload_str = json.dumps(trimmed, ensure_ascii=False)
                preview, truncated = truncate_for_log(payload_str, limit=300)
                self._logger.debug(
                    "request.payload_preview enabled=true truncated=%s len=%d payload=%s",
                    truncated,
                    len(payload_str),
                    preview,
                )
            except Exception:
                pass
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status >= 400:
                await self._log_and_raise(resp, kind="non-streaming")
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

    async def _log_and_raise(self, resp: aiohttp.ClientResponse, *, kind: str) -> None:
        """Log upstream error details and re-raise."""

        try:
            text = await resp.text()
        except Exception:  # pragma: no cover - defensive
            text = "<unable to read error body>"

        preview, _ = truncate_for_log(text, 800)
        self._logger.error("%s request failed status=%s body=%s", kind, resp.status, preview)
        resp.raise_for_status()


__all__ = ["OpenAIResponsesClient"]
