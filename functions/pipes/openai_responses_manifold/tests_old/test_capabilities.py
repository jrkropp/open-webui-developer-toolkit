"""Tests for model normalization and capability helpers."""

from __future__ import annotations

import pytest

from openai_responses_manifold import base_model, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("gpt-4.1", "gpt-4.1"),
        ("GPT-4.1-2025-11-03", "gpt-4.1"),
        ("openai_responses.gpt-4.1", "gpt-4.1"),
        ("MyPipe.GPT-4.1-2025-11-03", "gpt-4.1"),
        ("customprefix.some-model-2025-01-01", "customprefix.some-model"),
    ],
)
def test_normalize_handles_prefixes_and_dates(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_base_model_handles_prefixed_aliases() -> None:
    assert base_model("ExamplePipe.gpt-5-thinking-high-2025-05-01") == "gpt-5"
