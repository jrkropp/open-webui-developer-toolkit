"""Helpers for running non-streamed task models."""

from __future__ import annotations

from typing import Any

from openai_responses_manifold.adapters.openai.client import OpenAIResponsesClient


async def run_task_model(
    client: OpenAIResponsesClient,
    body: dict[str, Any],
    valves: Any,
) -> str:
    """
    Execute a task-style request (non-streamed) and return concatenated assistant text.

    This mirrors client.responses.create for simple “task” invocations where we
    want the final text output without streaming.
    """

    task_body = {
        "model": body.get("model"),
        "instructions": body.get("instructions", ""),
        "input": body.get("input", ""),
        "stream": False,
        "store": False,
    }
    response = await client.create(task_body, api_key=valves.API_KEY, base_url=valves.BASE_URL)
    text_parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text_parts.append(content.get("text", ""))
    return "".join(text_parts)


__all__ = ["run_task_model"]
