"""Helpers for converting OpenWebUI message blocks to Responses items."""

from __future__ import annotations

from typing import Any


def normalize_user_blocks(content: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return a list of user blocks regardless of how OpenWebUI formatted them."""

    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def user_blocks_to_responses_items(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenWebUI user blocks into Responses input items."""

    responses: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            responses.append({"type": "input_text", "text": block.get("text", "")})
        elif block_type == "image_url":
            url = (block.get("image_url") or {}).get("url")
            if url:
                responses.append({"type": "input_image", "image_url": url})
        elif block_type == "input_file":
            file_id = block.get("file_id")
            if file_id:
                responses.append({"type": "input_file", "file_id": file_id})
    return responses


def assistant_blocks_to_responses_items(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenWebUI assistant blocks into Responses output items."""

    responses: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in {"text", "input_text", "output_text"}:
            responses.append({"type": "output_text", "text": block.get("text", "")})
    return responses


def assistant_text_item(text: str) -> dict[str, Any]:
    """Generate an assistant message item for plain text segments."""

    return {
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
            }
        ],
    }


def developer_message(content: str) -> dict[str, Any]:
    """Construct a developer-role message block.

    For the Responses API, developer messages can carry plain string content; we use that simpler form.
    """

    return {"role": "developer", "content": content}


__all__ = [
    "assistant_text_item",
    "assistant_blocks_to_responses_items",
    "developer_message",
    "normalize_user_blocks",
    "user_blocks_to_responses_items",
]
