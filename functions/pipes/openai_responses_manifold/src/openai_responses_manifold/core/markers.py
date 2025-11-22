"""Helpers for encoding and parsing invisible history markers.

See `docs/markers_and_persistence.md` for the v2 marker format.
"""

from __future__ import annotations

import re
import secrets
from typing import Dict, Iterable, List, TypedDict
from urllib.parse import parse_qsl, urlencode

MARKER_PREFIX = "openai_responses:v2:"
ULID_LENGTH = 16
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_MARKER_PATTERN = re.compile(r"\[(?P<payload>openai_responses:v2:[^\]]+)\]:\s*#")
_ITEM_TYPE_PATTERN = re.compile(r"^[a-z0-9_]{2,30}$")


class ParsedMarker(TypedDict):
    item_type: str
    ulid: str
    metadata: dict[str, str]


def generate_ulid() -> str:
    """Generate a 16-character ULID-style identifier using Crockford Base32."""

    return "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))


def _validate_item_type(item_type: str) -> None:
    if not _ITEM_TYPE_PATTERN.match(item_type):
        raise ValueError(
            "item_type must match [a-z0-9_]{2,30}; got %r" % item_type
        )


def _validate_ulid(ulid: str) -> None:
    if len(ulid) != ULID_LENGTH:
        raise ValueError(f"ulid must be {ULID_LENGTH} characters; got {ulid!r}")
    invalid_chars = [ch for ch in ulid if ch not in CROCKFORD_ALPHABET]
    if invalid_chars:
        raise ValueError(f"ulid contains invalid characters: {invalid_chars!r}")


def build_marker_payload(
    *, item_type: str, ulid: str, metadata: dict[str, str] | None = None
) -> str:
    """Build the raw marker payload string.

    Example: ``openai_responses:v2:function_call:<ULID>?model=openai_responses.gpt-4o``.
    """

    _validate_item_type(item_type)
    _validate_ulid(ulid)

    base = f"{MARKER_PREFIX}{item_type}:{ulid}"
    if metadata:
        return f"{base}?{urlencode(metadata)}"
    return base


def wrap_marker(payload: str) -> str:
    """Wrap a raw marker payload into an invisible Markdown reference."""

    return f"\n[{payload}]: #\n"


def contains_marker(text: str | None) -> bool:
    """Fast sentinel check for marker presence in ``text``."""

    return MARKER_PREFIX in (text or "")


def parse_marker(payload: str) -> ParsedMarker:
    """Parse a raw marker payload string into its components."""

    if not payload.startswith(MARKER_PREFIX):
        raise ValueError("marker payload missing expected prefix")

    marker_body = payload[len(MARKER_PREFIX) :]
    item_and_id, _, query = marker_body.partition("?")
    try:
        item_type, ulid = item_and_id.split(":", 1)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("marker payload missing item type or ulid") from exc

    _validate_item_type(item_type)
    _validate_ulid(ulid)

    metadata: Dict[str, str] = {}
    if query:
        for key, value in parse_qsl(query, keep_blank_values=True):
            metadata[key] = value

    return {
        "item_type": item_type,
        "ulid": ulid,
        "metadata": metadata,
    }


def extract_markers(text: str, *, parsed: bool = False) -> List[str] | List[ParsedMarker]:
    """Extract wrapped markers from ``text``.

    Returns raw payload strings by default, or parsed marker dicts when
    ``parsed=True``.
    """

    if not contains_marker(text):
        return []

    payloads: List[str] = [match.group("payload") for match in _MARKER_PATTERN.finditer(text)]

    if not parsed:
        return payloads

    return [parse_marker(payload) for payload in payloads]


def split_text_by_markers(text: str) -> List[dict[str, str]]:
    """Split ``text`` into ordered segments of visible text and marker payloads."""

    if not contains_marker(text):
        return [{"type": "text", "text": text}]

    segments: List[dict[str, str]] = []
    last_end = 0
    for match in _MARKER_PATTERN.finditer(text):
        start, end = match.span()
        if start > last_end:
            visible = text[last_end:start]
            if visible:
                segments.append({"type": "text", "text": visible})
        segments.append({"type": "marker", "marker": match.group("payload")})
        last_end = end

    if last_end < len(text):
        tail = text[last_end:]
        if tail:
            segments.append({"type": "text", "text": tail})

    if not segments:
        return [{"type": "text", "text": text}]

    return segments


__all__ = [
    "MARKER_PREFIX",
    "ULID_LENGTH",
    "CROCKFORD_ALPHABET",
    "ParsedMarker",
    "generate_ulid",
    "build_marker_payload",
    "wrap_marker",
    "contains_marker",
    "parse_marker",
    "extract_markers",
    "split_text_by_markers",
]
