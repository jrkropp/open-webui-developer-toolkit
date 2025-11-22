import re

import pytest

from openai_responses_manifold.core import markers


def test_generate_ulid_uses_crockford_alphabet_and_length():
    ulid = markers.generate_ulid()

    assert len(ulid) == markers.ULID_LENGTH
    assert set(ulid) <= set(markers.CROCKFORD_ALPHABET)


def test_build_marker_payload_validates_inputs_and_encodes_metadata():
    ulid = "0123456789ABCDEF"
    payload = markers.build_marker_payload(
        item_type="function_call", ulid=ulid, metadata={"model": "foo bar"}
    )

    assert payload == "openai_responses:v2:function_call:0123456789ABCDEF?model=foo+bar"

    with pytest.raises(ValueError):
        markers.build_marker_payload(item_type="A", ulid=ulid)

    with pytest.raises(ValueError):
        markers.build_marker_payload(item_type="function_call", ulid="invalid")


def test_wrap_and_contains_marker_round_trip():
    payload = markers.build_marker_payload(item_type="reasoning", ulid="0" * 16)
    wrapped = markers.wrap_marker(payload)

    assert wrapped.startswith("\n[") and wrapped.endswith(": #\n")
    assert markers.contains_marker(wrapped)
    assert markers.contains_marker(None) is False


def test_extract_markers_returns_raw_and_parsed_variants():
    ulid = "0" * 16
    payload = markers.build_marker_payload(
        item_type="function_call_output", ulid=ulid, metadata={"model": "m1"}
    )
    text = f"prefix {markers.wrap_marker(payload)} suffix {markers.wrap_marker(payload)}"

    raw = markers.extract_markers(text)
    parsed = markers.extract_markers(text, parsed=True)

    assert raw == [payload, payload]
    assert parsed == [
        {"item_type": "function_call_output", "ulid": ulid, "metadata": {"model": "m1"}},
        {"item_type": "function_call_output", "ulid": ulid, "metadata": {"model": "m1"}},
    ]


def test_parse_marker_rejects_invalid_prefix_and_item_type():
    with pytest.raises(ValueError):
        markers.parse_marker("badprefix:reasoning:0" * 4)

    with pytest.raises(ValueError):
        markers.parse_marker("openai_responses:v2:X:0123456789ABCDEF")

    with pytest.raises(ValueError):
        markers.parse_marker("openai_responses:v2:reasoning:0123456789ABCD!F")

    valid = markers.parse_marker("openai_responses:v2:reasoning:0123456789ABCDEF")
    assert valid["item_type"] == "reasoning"


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Visible text only",
            [{"type": "text", "text": "Visible text only"}],
        ),
        (
            "Before\n[openai_responses:v2:function_call:0123456789ABCDEF]: #\nAfter",
                [
                    {"type": "text", "text": "Before\n"},
                    {
                        "type": "marker",
                        "marker": "openai_responses:v2:function_call:0123456789ABCDEF",
                    },
                    {"type": "text", "text": "\nAfter"},
                ],
            ),
        (
            "[openai_responses:v2:function_call:0123456789ABCDEF]: #",
            [
                {
                    "type": "marker",
                    "marker": "openai_responses:v2:function_call:0123456789ABCDEF",
                }
            ],
        ),
    ],
)
def test_split_text_by_markers(text: str, expected: list[dict[str, str]]):
    assert markers.split_text_by_markers(text) == expected
    # Ensure regex matches only the wrapped pattern
    assert all(
        re.fullmatch(r"openai_responses:v2:[^\]]+", segment.get("marker", ""))
        or "marker" not in segment
        for segment in markers.split_text_by_markers(text)
    )


def test_contains_and_extract_without_markers():
    text = "no markers here"

    assert markers.contains_marker(text) is False
    assert markers.extract_markers(text) == []
    assert markers.split_text_by_markers(text) == [{"type": "text", "text": text}]
