"""Helpers for encoding/decoding hidden response markers."""

from __future__ import annotations

import re
import secrets
from typing import Any

ULID_LENGTH = 16
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SENTINEL = "[openai_responses:v2:"
_MARKER_RE = re.compile(
    r"\[openai_responses:v2:(?P<kind>[a-z0-9_]{2,30}):(?P<ulid>[A-Z0-9]{16})(?:\?(?P<query>[^\]]+))?\]:\s*#",
    re.I,
)


def generate_item_id() -> str:
    """Generate a short ULID-like identifier."""

    return "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))


def _qs(metadata: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in metadata.items()) if metadata else ""


def _parse_qs(query: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in query.split("&")) if query else {}


def create_marker(
    item_type: str,
    *,
    ulid: str | None = None,
    model_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """Create a bare marker payload (without the wrapping newlines)."""

    if not re.fullmatch(r"[a-z0-9_]{2,30}", item_type):
        raise ValueError("item_type must be 2-30 chars of [a-z0-9_]")

    meta = {**(metadata or {})}
    if model_id:
        meta["model"] = model_id

    base = f"openai_responses:v2:{item_type}:{ulid or generate_item_id()}"
    return f"{base}?{_qs(meta)}" if meta else base


def wrap_marker(marker: str) -> str:
    """Wrap a marker string in an empty markdown link."""

    return f"\n[{marker}]: #\n"


def contains_marker(text: str) -> bool:
    """Return True if the sentinel substring is present."""

    return _SENTINEL in text


def parse_marker(marker: str) -> dict[str, Any]:
    """Parse a raw marker string back into its components."""

    if not marker.startswith("openai_responses:v2:"):
        raise ValueError("not a v2 marker")
    _, _, kind, rest = marker.split(":", 3)
    uid, _, query = rest.partition("?")
    return {"version": "v2", "item_type": kind, "ulid": uid, "metadata": _parse_qs(query)}


def extract_markers(text: str, *, parsed: bool = False) -> list[Any]:
    """Extract hidden markers from the assistant text."""

    found: list[Any] = []
    for match in _MARKER_RE.finditer(text):
        raw = f"openai_responses:v2:{match.group('kind')}:{match.group('ulid')}"
        if match.group("query"):
            raw += f"?{match.group('query')}"
        found.append(parse_marker(raw) if parsed else raw)
    return found


def split_text_by_markers(text: str) -> list[dict[str, str]]:
    """Split text into a list of literal segments and marker segments."""

    segments: list[dict[str, str]] = []
    last = 0
    for match in _MARKER_RE.finditer(text):
        if match.start() > last:
            segments.append({"type": "text", "text": text[last : match.start()]})
        raw = f"openai_responses:v2:{match.group('kind')}:{match.group('ulid')}"
        if match.group("query"):
            raw += f"?{match.group('query')}"
        segments.append({"type": "marker", "marker": raw})
        last = match.end()
    if last < len(text):
        segments.append({"type": "text", "text": text[last:]})
    return segments
