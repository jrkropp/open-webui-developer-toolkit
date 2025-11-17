from openai_responses_manifold.core.events import (
    EventType,
    ResponseOutputTextDeltaEvent,
    StreamEvent,
    UnknownStreamEventType,
    parse_event,
)


def test_parse_event_to_typed_model_preserves_fields_and_extras() -> None:
    payload = {
        "type": "response.output_text.delta",
        "output_index": 0,
        "item_id": "msg_123",
        "content_index": 0,
        "delta": "In",
        "sequence_number": 1,
        "logprobs": None,
    }

    event = parse_event(payload)

    assert isinstance(event, ResponseOutputTextDeltaEvent)
    assert event.type is EventType.RESPONSE_OUTPUT_TEXT_DELTA
    assert event.output_index == 0
    assert event.item_id == "msg_123"
    assert event.delta == "In"
    assert event.sequence_number == 1


def test_parse_event_rejects_unknown_types() -> None:
    payload: dict[str, object] = {"type": "response.not_a_real_event"}
    try:
        parse_event(payload)
    except UnknownStreamEventType as exc:
        assert "response.not_a_real_event" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected UnknownStreamEventType")


def test_stream_event_union_accepts_literal_value() -> None:
    payload = {
        "type": "response.output_text.delta",
        "output_index": 0,
        "item_id": "msg_123",
        "content_index": 0,
        "delta": "hello",
    }
    event = parse_event(payload)
    assert isinstance(event, StreamEvent.__args__)  # type: ignore[attr-defined]
