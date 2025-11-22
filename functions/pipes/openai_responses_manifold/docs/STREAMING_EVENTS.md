# OpenAI Responses Streaming Events

Quick reference for the OpenAI Responses SSE event types that the manifold consumes and logs when `stream: true`. Use this to map log lines to upstream events or to build tests/fixtures that mimic OpenAI streaming.

**Basics**
- Every event has a `type` and `sequence_number`; the latter is monotonic within a stream.
- Response-level events include the full `response` object; item/content events include `output_index` plus an `item_id` or `content_index`.
- Error events can arrive at any time; handle them the same way you would a failed HTTP call.

## Lifecycle (response-level)
- `response.queued` – Response accepted but not started; payload: `response`, `sequence_number`.
- `response.created` – Initial response stub; `response.status` is usually `in_progress`.
- `response.in_progress` – Periodic heartbeat; payload looks like `response.created`.
- `response.completed` – Final response with `output` and `usage`.
- `response.incomplete` – Ended early; `incomplete_details.reason` explains why (e.g., `max_tokens`).
- `response.failed` – Terminal error with `response.error {code, message}`.
- `error` – Transport-level error event with `{code, message, param, sequence_number}`.

## Output items (messages, tool calls, etc.)
- `response.output_item.added` – New output entry created; payload: `output_index`, `item {id, type, status, role?, content?}`.
- `response.output_item.done` – Item finalized; same shape as `output_item.added` but with completed content.

## Content parts and text streaming
- `response.content_part.added` – New content part placeholder; `output_index`, `item_id`, `content_index`, `part` scaffold.
- `response.content_part.done` – Content part finalized; same indices plus completed `part`.
- `response.output_text.delta` – Text chunk; `delta` string plus `output_index`, `item_id`, `content_index` (optional `logprobs`). Some tenants may see `obfuscation` when upstream padding is enabled.
- `response.output_text.done` – Final text for a content part; payload adds `text` (optional `logprobs`, optional `obfuscation`).
- `response.output_text.annotation.added` – Annotation attached to a text part; includes `annotation_index` and full `annotation` object.
- `response.refusal.delta` / `response.refusal.done` – Partial/final refusal text; carries `refusal` in the done event.

## Function / tool call arguments
- `response.function_call_arguments.delta` – Partial JSON arguments string for a function call; fields: `delta`, `item_id`, `output_index`.
- `response.function_call_arguments.done` – Finalized `arguments` string and function `name`.
- `response.custom_tool_call_input.delta` / `response.custom_tool_call_input.done` – Partial/final input payloads for custom tool calls; fields mirror the function-call variants.

## Search tool calls
- `response.file_search_call.in_progress` / `searching` / `completed` – File search lifecycle; payload: `output_index`, `item_id`.
- `response.web_search_call.in_progress` / `searching` / `completed` – Web search lifecycle; payload: `output_index`, `item_id`.

## Reasoning traces
- `response.reasoning_summary_part.added` / `done` – Summary part scaffold/finalization; fields: `output_index`, `item_id`, `summary_index`, `part`.
- `response.reasoning_summary_text.delta` / `done` – Streaming/full text for a summary part; adds `delta` or `text`.
- `response.reasoning_text.delta` / `done` – Streaming/full reasoning content; keyed by `content_index` instead of `summary_index`.

## Image generation
- `response.image_generation_call.in_progress` / `generating` / `completed` – Image generation lifecycle; payload: `output_index`, `item_id`.
- `response.image_generation_call.partial_image` – Base64 partial image chunk; adds `partial_image_index` and `partial_image_b64`.

## MCP calls
- `response.mcp_call.in_progress` / `completed` / `failed` – Remote MCP tool call lifecycle; payload: `output_index`, `item_id`.
- `response.mcp_call_arguments.delta` / `done` – Partial/final arguments JSON for an MCP call; payload mirrors function-call arguments.
- `response.mcp_list_tools.in_progress` / `completed` / `failed` – Lifecycle for listing remote MCP tools; payload: `output_index`, `item_id`.

## Code interpreter (Python sandbox)
- `response.code_interpreter_call.in_progress` / `interpreting` / `completed` – Call lifecycle; payload: `output_index`, `item_id`.
- `response.code_interpreter_call_code.delta` / `done` – Streaming/final code string emitted by the interpreter; payload: `delta` or `code`.

## Usage counters
- Usage is included on `response.completed`; there is no separate usage event today.
