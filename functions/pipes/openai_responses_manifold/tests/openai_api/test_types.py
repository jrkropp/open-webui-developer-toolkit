from __future__ import annotations

from openai_responses_manifold.openai_api.types import (
    ResponsesRequest,
    ResponseCompletedEvent,
    ResponseOutputTextDeltaEvent,
    dump_responses_request,
    parse_responses_event,
)


class TestResponsesRequest:
    def test_alias_defaults_apply_without_overwriting_explicit_values(self) -> None:
        request = ResponsesRequest(
            model="gpt-5-thinking-high",
            reasoning={"effort": "minimal"},
            include=["output_text"],
        )

        assert request.model == "gpt-5"
        assert request.reasoning == {"effort": "minimal"}
        assert request.include == ["output_text"]

    def test_alias_defaults_fill_missing_fields(self) -> None:
        request = ResponsesRequest(model="openai_responses.gpt-5-thinking-high")

        assert request.model == "gpt-5"
        assert request.reasoning == {"effort": "high"}

    def test_dump_responses_request_excludes_none(self) -> None:
        request = ResponsesRequest(model="gpt-5.1-chat-latest", instructions="hi")

        dumped = dump_responses_request(request)

        assert dumped == {"model": "gpt-5.1-chat-latest", "instructions": "hi", "stream": False}

    def test_alias_default_lists_merge_uniquely(self, monkeypatch) -> None:
        defaults = {"include": ["foo", "bar"]}

        monkeypatch.setattr(
            "openai_responses_manifold.openai_api.types.model_catalog.alias_defaults",
            lambda model: defaults if model == "gpt-5" else {},
        )

        request = ResponsesRequest(model="gpt-5", include=["bar", "baz"])

        assert request.include == ["bar", "baz", "foo"]


class TestResponsesEvents:
    def test_parse_delta_event(self) -> None:
        event = parse_responses_event({"type": "response.output_text.delta", "delta": "hello"})

        assert isinstance(event, ResponseOutputTextDeltaEvent)
        assert event.delta == "hello"

    def test_parse_completed_event(self) -> None:
        payload = {"type": "response.completed", "response": {"id": "123"}, "extra": "ignored"}

        event = parse_responses_event(payload)

        assert isinstance(event, ResponseCompletedEvent)
        assert event.response == {"id": "123"}
        assert event.model_extra == {"extra": "ignored"}

