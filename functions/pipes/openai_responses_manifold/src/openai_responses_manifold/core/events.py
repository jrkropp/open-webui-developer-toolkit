"""Typed schemas for documented OpenAI Responses streaming events."""

from __future__ import annotations

from enum import Enum
from typing import Any, Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class UnknownStreamEventType(ValueError):
    """Raised when an SSE event ``type`` is not recognized."""


class EventType(str, Enum):
    RESPONSE_QUEUED = "response.queued"
    RESPONSE_CREATED = "response.created"
    RESPONSE_IN_PROGRESS = "response.in_progress"
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_FAILED = "response.failed"
    RESPONSE_INCOMPLETE = "response.incomplete"

    RESPONSE_OUTPUT_ITEM_ADDED = "response.output_item.added"
    RESPONSE_OUTPUT_ITEM_DONE = "response.output_item.done"

    RESPONSE_CONTENT_PART_ADDED = "response.content_part.added"
    RESPONSE_CONTENT_PART_DONE = "response.content_part.done"

    RESPONSE_OUTPUT_TEXT_DELTA = "response.output_text.delta"
    RESPONSE_OUTPUT_TEXT_DONE = "response.output_text.done"
    RESPONSE_OUTPUT_TEXT_ANNOTATION_ADDED = "response.output_text.annotation.added"

    RESPONSE_REFUSAL_DELTA = "response.refusal.delta"
    RESPONSE_REFUSAL_DONE = "response.refusal.done"

    RESPONSE_FUNCTION_CALL_ARGS_DELTA = "response.function_call_arguments.delta"
    RESPONSE_FUNCTION_CALL_ARGS_DONE = "response.function_call_arguments.done"

    RESPONSE_CUSTOM_TOOL_CALL_INPUT_DELTA = "response.custom_tool_call_input.delta"
    RESPONSE_CUSTOM_TOOL_CALL_INPUT_DONE = "response.custom_tool_call_input.done"

    RESPONSE_FILE_SEARCH_CALL_IN_PROGRESS = "response.file_search_call.in_progress"
    RESPONSE_FILE_SEARCH_CALL_SEARCHING = "response.file_search_call.searching"
    RESPONSE_FILE_SEARCH_CALL_COMPLETED = "response.file_search_call.completed"

    RESPONSE_WEB_SEARCH_CALL_IN_PROGRESS = "response.web_search_call.in_progress"
    RESPONSE_WEB_SEARCH_CALL_SEARCHING = "response.web_search_call.searching"
    RESPONSE_WEB_SEARCH_CALL_COMPLETED = "response.web_search_call.completed"

    RESPONSE_REASONING_SUMMARY_PART_ADDED = "response.reasoning_summary_part.added"
    RESPONSE_REASONING_SUMMARY_PART_DONE = "response.reasoning_summary_part.done"
    RESPONSE_REASONING_SUMMARY_TEXT_DELTA = "response.reasoning_summary_text.delta"
    RESPONSE_REASONING_SUMMARY_TEXT_DONE = "response.reasoning_summary_text.done"

    RESPONSE_REASONING_TEXT_DELTA = "response.reasoning_text.delta"
    RESPONSE_REASONING_TEXT_DONE = "response.reasoning_text.done"

    RESPONSE_IMAGE_GENERATION_CALL_IN_PROGRESS = "response.image_generation_call.in_progress"
    RESPONSE_IMAGE_GENERATION_CALL_GENERATING = "response.image_generation_call.generating"
    RESPONSE_IMAGE_GENERATION_CALL_COMPLETED = "response.image_generation_call.completed"
    RESPONSE_IMAGE_GENERATION_CALL_PARTIAL_IMAGE = "response.image_generation_call.partial_image"

    RESPONSE_MCP_CALL_ARGS_DELTA = "response.mcp_call_arguments.delta"
    RESPONSE_MCP_CALL_ARGS_DONE = "response.mcp_call_arguments.done"
    RESPONSE_MCP_CALL_IN_PROGRESS = "response.mcp_call.in_progress"
    RESPONSE_MCP_CALL_COMPLETED = "response.mcp_call.completed"
    RESPONSE_MCP_CALL_FAILED = "response.mcp_call.failed"
    RESPONSE_MCP_LIST_TOOLS_IN_PROGRESS = "response.mcp_list_tools.in_progress"
    RESPONSE_MCP_LIST_TOOLS_COMPLETED = "response.mcp_list_tools.completed"
    RESPONSE_MCP_LIST_TOOLS_FAILED = "response.mcp_list_tools.failed"

    RESPONSE_CODE_INTERPRETER_CALL_IN_PROGRESS = "response.code_interpreter_call.in_progress"
    RESPONSE_CODE_INTERPRETER_CALL_INTERPRETING = "response.code_interpreter_call.interpreting"
    RESPONSE_CODE_INTERPRETER_CALL_COMPLETED = "response.code_interpreter_call.completed"
    RESPONSE_CODE_INTERPRETER_CALL_CODE_DELTA = "response.code_interpreter_call_code.delta"
    RESPONSE_CODE_INTERPRETER_CALL_CODE_DONE = "response.code_interpreter_call_code.done"

    ERROR = "error"


class BaseStreamEvent(BaseModel):
    """Common fields for all streaming events."""

    type: EventType
    sequence_number: int | None = Field(default=None, description="Monotonic within a stream.")

    model_config = ConfigDict(extra="forbid")


class ResponseEnvelopeEvent(BaseStreamEvent):
    response: dict[str, Any]


class ResponseQueuedEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_QUEUED] = EventType.RESPONSE_QUEUED


class ResponseCreatedEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_CREATED] = EventType.RESPONSE_CREATED


class ResponseInProgressEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_IN_PROGRESS] = EventType.RESPONSE_IN_PROGRESS


class ResponseCompletedEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_COMPLETED] = EventType.RESPONSE_COMPLETED


class ResponseFailedEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_FAILED] = EventType.RESPONSE_FAILED


class ResponseIncompleteEvent(ResponseEnvelopeEvent):
    type: Literal[EventType.RESPONSE_INCOMPLETE] = EventType.RESPONSE_INCOMPLETE


class ResponseOutputItemEvent(BaseStreamEvent):
    output_index: int
    item: dict[str, Any]


class ResponseOutputItemAddedEvent(ResponseOutputItemEvent):
    type: Literal[EventType.RESPONSE_OUTPUT_ITEM_ADDED] = EventType.RESPONSE_OUTPUT_ITEM_ADDED


class ResponseOutputItemDoneEvent(ResponseOutputItemEvent):
    type: Literal[EventType.RESPONSE_OUTPUT_ITEM_DONE] = EventType.RESPONSE_OUTPUT_ITEM_DONE


class ResponseContentPartEvent(BaseStreamEvent):
    output_index: int
    item_id: str
    content_index: int
    part: dict[str, Any]


class ResponseContentPartAddedEvent(ResponseContentPartEvent):
    type: Literal[EventType.RESPONSE_CONTENT_PART_ADDED] = EventType.RESPONSE_CONTENT_PART_ADDED


class ResponseContentPartDoneEvent(ResponseContentPartEvent):
    type: Literal[EventType.RESPONSE_CONTENT_PART_DONE] = EventType.RESPONSE_CONTENT_PART_DONE


class ResponseOutputTextDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_OUTPUT_TEXT_DELTA] = EventType.RESPONSE_OUTPUT_TEXT_DELTA
    output_index: int
    item_id: str
    content_index: int
    delta: str
    logprobs: list[Any] | None = None


class ResponseOutputTextDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_OUTPUT_TEXT_DONE] = EventType.RESPONSE_OUTPUT_TEXT_DONE
    output_index: int
    item_id: str
    content_index: int
    text: str
    logprobs: list[Any] | None = None


class ResponseOutputTextAnnotationAddedEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_OUTPUT_TEXT_ANNOTATION_ADDED] = (
        EventType.RESPONSE_OUTPUT_TEXT_ANNOTATION_ADDED
    )
    output_index: int
    item_id: str
    content_index: int
    annotation_index: int
    annotation: dict[str, Any]


class ResponseRefusalDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REFUSAL_DELTA] = EventType.RESPONSE_REFUSAL_DELTA
    output_index: int
    item_id: str
    content_index: int
    delta: str


class ResponseRefusalDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REFUSAL_DONE] = EventType.RESPONSE_REFUSAL_DONE
    output_index: int
    item_id: str
    content_index: int
    refusal: str


class ResponseFunctionCallArgumentsDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_FUNCTION_CALL_ARGS_DELTA] = (
        EventType.RESPONSE_FUNCTION_CALL_ARGS_DELTA
    )
    output_index: int
    item_id: str
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_FUNCTION_CALL_ARGS_DONE] = (
        EventType.RESPONSE_FUNCTION_CALL_ARGS_DONE
    )
    output_index: int
    item_id: str
    name: str
    arguments: str


class ResponseCustomToolCallInputDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_CUSTOM_TOOL_CALL_INPUT_DELTA] = (
        EventType.RESPONSE_CUSTOM_TOOL_CALL_INPUT_DELTA
    )
    output_index: int
    item_id: str
    delta: str


class ResponseCustomToolCallInputDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_CUSTOM_TOOL_CALL_INPUT_DONE] = (
        EventType.RESPONSE_CUSTOM_TOOL_CALL_INPUT_DONE
    )
    output_index: int
    item_id: str
    input: str


class ResponseFileSearchCallEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseFileSearchCallInProgressEvent(ResponseFileSearchCallEvent):
    type: Literal[EventType.RESPONSE_FILE_SEARCH_CALL_IN_PROGRESS] = (
        EventType.RESPONSE_FILE_SEARCH_CALL_IN_PROGRESS
    )


class ResponseFileSearchCallSearchingEvent(ResponseFileSearchCallEvent):
    type: Literal[EventType.RESPONSE_FILE_SEARCH_CALL_SEARCHING] = (
        EventType.RESPONSE_FILE_SEARCH_CALL_SEARCHING
    )


class ResponseFileSearchCallCompletedEvent(ResponseFileSearchCallEvent):
    type: Literal[EventType.RESPONSE_FILE_SEARCH_CALL_COMPLETED] = (
        EventType.RESPONSE_FILE_SEARCH_CALL_COMPLETED
    )


class ResponseWebSearchCallEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseWebSearchCallInProgressEvent(ResponseWebSearchCallEvent):
    type: Literal[EventType.RESPONSE_WEB_SEARCH_CALL_IN_PROGRESS] = (
        EventType.RESPONSE_WEB_SEARCH_CALL_IN_PROGRESS
    )


class ResponseWebSearchCallSearchingEvent(ResponseWebSearchCallEvent):
    type: Literal[EventType.RESPONSE_WEB_SEARCH_CALL_SEARCHING] = (
        EventType.RESPONSE_WEB_SEARCH_CALL_SEARCHING
    )


class ResponseWebSearchCallCompletedEvent(ResponseWebSearchCallEvent):
    type: Literal[EventType.RESPONSE_WEB_SEARCH_CALL_COMPLETED] = (
        EventType.RESPONSE_WEB_SEARCH_CALL_COMPLETED
    )


class ResponseReasoningSummaryPartEvent(BaseStreamEvent):
    output_index: int
    item_id: str
    summary_index: int
    part: dict[str, Any]


class ResponseReasoningSummaryPartAddedEvent(ResponseReasoningSummaryPartEvent):
    type: Literal[EventType.RESPONSE_REASONING_SUMMARY_PART_ADDED] = (
        EventType.RESPONSE_REASONING_SUMMARY_PART_ADDED
    )


class ResponseReasoningSummaryPartDoneEvent(ResponseReasoningSummaryPartEvent):
    type: Literal[EventType.RESPONSE_REASONING_SUMMARY_PART_DONE] = (
        EventType.RESPONSE_REASONING_SUMMARY_PART_DONE
    )


class ResponseReasoningSummaryTextDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REASONING_SUMMARY_TEXT_DELTA] = (
        EventType.RESPONSE_REASONING_SUMMARY_TEXT_DELTA
    )
    output_index: int
    item_id: str
    summary_index: int
    delta: str


class ResponseReasoningSummaryTextDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REASONING_SUMMARY_TEXT_DONE] = (
        EventType.RESPONSE_REASONING_SUMMARY_TEXT_DONE
    )
    output_index: int
    item_id: str
    summary_index: int
    text: str


class ResponseReasoningTextDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REASONING_TEXT_DELTA] = EventType.RESPONSE_REASONING_TEXT_DELTA
    output_index: int
    item_id: str
    content_index: int
    delta: str


class ResponseReasoningTextDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_REASONING_TEXT_DONE] = EventType.RESPONSE_REASONING_TEXT_DONE
    output_index: int
    item_id: str
    content_index: int
    text: str


class ResponseImageGenerationCallEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseImageGenerationCallInProgressEvent(ResponseImageGenerationCallEvent):
    type: Literal[EventType.RESPONSE_IMAGE_GENERATION_CALL_IN_PROGRESS] = (
        EventType.RESPONSE_IMAGE_GENERATION_CALL_IN_PROGRESS
    )


class ResponseImageGenerationCallGeneratingEvent(ResponseImageGenerationCallEvent):
    type: Literal[EventType.RESPONSE_IMAGE_GENERATION_CALL_GENERATING] = (
        EventType.RESPONSE_IMAGE_GENERATION_CALL_GENERATING
    )


class ResponseImageGenerationCallCompletedEvent(ResponseImageGenerationCallEvent):
    type: Literal[EventType.RESPONSE_IMAGE_GENERATION_CALL_COMPLETED] = (
        EventType.RESPONSE_IMAGE_GENERATION_CALL_COMPLETED
    )


class ResponseImageGenerationCallPartialImageEvent(ResponseImageGenerationCallEvent):
    type: Literal[EventType.RESPONSE_IMAGE_GENERATION_CALL_PARTIAL_IMAGE] = (
        EventType.RESPONSE_IMAGE_GENERATION_CALL_PARTIAL_IMAGE
    )
    partial_image_index: int
    partial_image_b64: str


class ResponseMCPCallArgumentsDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_MCP_CALL_ARGS_DELTA] = EventType.RESPONSE_MCP_CALL_ARGS_DELTA
    output_index: int
    item_id: str
    delta: str


class ResponseMCPCallArgumentsDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_MCP_CALL_ARGS_DONE] = EventType.RESPONSE_MCP_CALL_ARGS_DONE
    output_index: int
    item_id: str
    arguments: str


class ResponseMCPCallEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseMCPCallInProgressEvent(ResponseMCPCallEvent):
    type: Literal[EventType.RESPONSE_MCP_CALL_IN_PROGRESS] = EventType.RESPONSE_MCP_CALL_IN_PROGRESS


class ResponseMCPCallCompletedEvent(ResponseMCPCallEvent):
    type: Literal[EventType.RESPONSE_MCP_CALL_COMPLETED] = EventType.RESPONSE_MCP_CALL_COMPLETED


class ResponseMCPCallFailedEvent(ResponseMCPCallEvent):
    type: Literal[EventType.RESPONSE_MCP_CALL_FAILED] = EventType.RESPONSE_MCP_CALL_FAILED


class ResponseMCPListToolsEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseMCPListToolsInProgressEvent(ResponseMCPListToolsEvent):
    type: Literal[EventType.RESPONSE_MCP_LIST_TOOLS_IN_PROGRESS] = (
        EventType.RESPONSE_MCP_LIST_TOOLS_IN_PROGRESS
    )


class ResponseMCPListToolsCompletedEvent(ResponseMCPListToolsEvent):
    type: Literal[EventType.RESPONSE_MCP_LIST_TOOLS_COMPLETED] = (
        EventType.RESPONSE_MCP_LIST_TOOLS_COMPLETED
    )


class ResponseMCPListToolsFailedEvent(ResponseMCPListToolsEvent):
    type: Literal[EventType.RESPONSE_MCP_LIST_TOOLS_FAILED] = EventType.RESPONSE_MCP_LIST_TOOLS_FAILED


class ResponseCodeInterpreterCallEvent(BaseStreamEvent):
    output_index: int
    item_id: str


class ResponseCodeInterpreterCallInProgressEvent(ResponseCodeInterpreterCallEvent):
    type: Literal[EventType.RESPONSE_CODE_INTERPRETER_CALL_IN_PROGRESS] = (
        EventType.RESPONSE_CODE_INTERPRETER_CALL_IN_PROGRESS
    )


class ResponseCodeInterpreterCallInterpretingEvent(ResponseCodeInterpreterCallEvent):
    type: Literal[EventType.RESPONSE_CODE_INTERPRETER_CALL_INTERPRETING] = (
        EventType.RESPONSE_CODE_INTERPRETER_CALL_INTERPRETING
    )


class ResponseCodeInterpreterCallCompletedEvent(ResponseCodeInterpreterCallEvent):
    type: Literal[EventType.RESPONSE_CODE_INTERPRETER_CALL_COMPLETED] = (
        EventType.RESPONSE_CODE_INTERPRETER_CALL_COMPLETED
    )


class ResponseCodeInterpreterCallCodeDeltaEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_CODE_INTERPRETER_CALL_CODE_DELTA] = (
        EventType.RESPONSE_CODE_INTERPRETER_CALL_CODE_DELTA
    )
    output_index: int
    item_id: str
    delta: str


class ResponseCodeInterpreterCallCodeDoneEvent(BaseStreamEvent):
    type: Literal[EventType.RESPONSE_CODE_INTERPRETER_CALL_CODE_DONE] = (
        EventType.RESPONSE_CODE_INTERPRETER_CALL_CODE_DONE
    )
    output_index: int
    item_id: str
    code: str


class ErrorEvent(BaseStreamEvent):
    type: Literal[EventType.ERROR] = EventType.ERROR
    code: str
    message: str
    param: str | None = None


StreamEvent = Annotated[
    ResponseQueuedEvent
    | ResponseCreatedEvent
    | ResponseInProgressEvent
    | ResponseCompletedEvent
    | ResponseFailedEvent
    | ResponseIncompleteEvent
    | ResponseOutputItemAddedEvent
    | ResponseOutputItemDoneEvent
    | ResponseContentPartAddedEvent
    | ResponseContentPartDoneEvent
    | ResponseOutputTextDeltaEvent
    | ResponseOutputTextDoneEvent
    | ResponseOutputTextAnnotationAddedEvent
    | ResponseRefusalDeltaEvent
    | ResponseRefusalDoneEvent
    | ResponseFunctionCallArgumentsDeltaEvent
    | ResponseFunctionCallArgumentsDoneEvent
    | ResponseCustomToolCallInputDeltaEvent
    | ResponseCustomToolCallInputDoneEvent
    | ResponseFileSearchCallInProgressEvent
    | ResponseFileSearchCallSearchingEvent
    | ResponseFileSearchCallCompletedEvent
    | ResponseWebSearchCallInProgressEvent
    | ResponseWebSearchCallSearchingEvent
    | ResponseWebSearchCallCompletedEvent
    | ResponseReasoningSummaryPartAddedEvent
    | ResponseReasoningSummaryPartDoneEvent
    | ResponseReasoningSummaryTextDeltaEvent
    | ResponseReasoningSummaryTextDoneEvent
    | ResponseReasoningTextDeltaEvent
    | ResponseReasoningTextDoneEvent
    | ResponseImageGenerationCallInProgressEvent
    | ResponseImageGenerationCallGeneratingEvent
    | ResponseImageGenerationCallCompletedEvent
    | ResponseImageGenerationCallPartialImageEvent
    | ResponseMCPCallArgumentsDeltaEvent
    | ResponseMCPCallArgumentsDoneEvent
    | ResponseMCPCallInProgressEvent
    | ResponseMCPCallCompletedEvent
    | ResponseMCPCallFailedEvent
    | ResponseMCPListToolsInProgressEvent
    | ResponseMCPListToolsCompletedEvent
    | ResponseMCPListToolsFailedEvent
    | ResponseCodeInterpreterCallInProgressEvent
    | ResponseCodeInterpreterCallInterpretingEvent
    | ResponseCodeInterpreterCallCompletedEvent
    | ResponseCodeInterpreterCallCodeDeltaEvent
    | ResponseCodeInterpreterCallCodeDoneEvent
    | ErrorEvent,
    Field(discriminator="type"),
]

_STREAM_EVENT_ADAPTER = TypeAdapter(StreamEvent)


def parse_event(payload: Mapping[str, Any]) -> StreamEvent:
    """Validate and cast a raw SSE payload into a typed event model."""

    try:
        return _STREAM_EVENT_ADAPTER.validate_python(payload)
    except ValidationError as exc:  # pragma: no cover - defensive
        raise UnknownStreamEventType(f"Unknown or invalid event type: {payload.get('type')}") from exc


__all__ = [
    "BaseStreamEvent",
    "ErrorEvent",
    "EventType",
    "ResponseCodeInterpreterCallCodeDeltaEvent",
    "ResponseCodeInterpreterCallCodeDoneEvent",
    "ResponseCodeInterpreterCallCompletedEvent",
    "ResponseCodeInterpreterCallEvent",
    "ResponseCodeInterpreterCallInProgressEvent",
    "ResponseCodeInterpreterCallInterpretingEvent",
    "ResponseCompletedEvent",
    "ResponseContentPartAddedEvent",
    "ResponseContentPartDoneEvent",
    "ResponseContentPartEvent",
    "ResponseCreatedEvent",
    "ResponseCustomToolCallInputDeltaEvent",
    "ResponseCustomToolCallInputDoneEvent",
    "ResponseEnvelopeEvent",
    "ResponseFailedEvent",
    "ResponseFileSearchCallCompletedEvent",
    "ResponseFileSearchCallInProgressEvent",
    "ResponseFileSearchCallSearchingEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    "ResponseFunctionCallArgumentsDoneEvent",
    "ResponseImageGenerationCallCompletedEvent",
    "ResponseImageGenerationCallEvent",
    "ResponseImageGenerationCallGeneratingEvent",
    "ResponseImageGenerationCallInProgressEvent",
    "ResponseImageGenerationCallPartialImageEvent",
    "ResponseInProgressEvent",
    "ResponseMCPCallArgumentsDeltaEvent",
    "ResponseMCPCallArgumentsDoneEvent",
    "ResponseMCPCallCompletedEvent",
    "ResponseMCPCallEvent",
    "ResponseMCPCallFailedEvent",
    "ResponseMCPCallInProgressEvent",
    "ResponseMCPListToolsCompletedEvent",
    "ResponseMCPListToolsEvent",
    "ResponseMCPListToolsFailedEvent",
    "ResponseMCPListToolsInProgressEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputItemEvent",
    "ResponseOutputTextAnnotationAddedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseOutputTextDoneEvent",
    "ResponseQueuedEvent",
    "ResponseReasoningSummaryPartAddedEvent",
    "ResponseReasoningSummaryPartDoneEvent",
    "ResponseReasoningSummaryPartEvent",
    "ResponseReasoningSummaryTextDeltaEvent",
    "ResponseReasoningSummaryTextDoneEvent",
    "ResponseReasoningTextDeltaEvent",
    "ResponseReasoningTextDoneEvent",
    "ResponseRefusalDeltaEvent",
    "ResponseRefusalDoneEvent",
    "ResponseSearchEvent",
    "ResponseWebSearchCallCompletedEvent",
    "ResponseWebSearchCallInProgressEvent",
    "ResponseWebSearchCallSearchingEvent",
    "StreamEvent",
    "UnknownStreamEventType",
    "parse_event",
]
