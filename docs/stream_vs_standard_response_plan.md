# Split streaming logic in OpenAI Responses pipe

This document outlines the refactor to handle streaming and non‑streaming
responses separately.

## Motivation
The existing `Pipe.pipe()` mixes logic for normal responses and Server-Sent
Events. Separating these paths will make the code easier to follow and simpler
to extend.

## Proposed changes
1. **Introduce two helper methods**:
   - `_streaming_response(...)` – implements the current streaming loop.
   - `_non_streaming_response(...)` – wraps the existing `get_responses()` call
     and yields the final text once the response completes.
2. **Switch `pipe()`** to check `body.get("stream", False)` and delegate to the
   appropriate helper.
3. Each helper will receive the prepared request parameters, http client and
   emitter so the main method only handles setup and cleanup logic.
4. Keep the existing event emission and usage accounting inside the helpers so
   behaviour remains unchanged.

This refactor keeps the public interface intact while isolating the two code
paths for easier maintenance.

## Implementation Steps
1. Move the non-streaming branch of `pipe()` into
   `Pipe._non_stream_response(...)`. The method should:
   - call `get_responses()`
   - process function calls just like the streaming path
   - emit usage stats and completion events
   - yield the final assistant text when available.
2. Move the current streaming loop into
   `Pipe._stream_response(...)`. It retains the SSE handling and tool
   call logic unchanged.
3. In `Pipe.pipe()`, compute shared variables and assemble the request
   payload. Then delegate to one of the helpers using
   `if body.get("stream", False):`.
4. Both helpers return an async generator yielding text chunks so the
   caller can iterate normally.
## Understanding the Responses API
The OpenAI Responses API behaves differently depending on the `stream` parameter.
When `"stream": true` the server returns a stream of Server Sent Events (SSE).
Events arrive in this order:
- `response.created`
- `response.in_progress`
- a sequence of `response.output_text.delta` events, each containing a chunk of text
- `response.completed` once generation is finished

With `"stream": false` (or when the field is missing) the request resolves
with a single JSON payload containing the final `output` array and usage stats.

Both modes accept the same request parameters. We will check
`body.get("stream", False)` in `Pipe.pipe()` to dispatch to either
`_stream_response` or `_non_stream_response`.

## API Request Schema
- **model**: the short model id (e.g. `gpt-4.1`) without date suffix.
- **instructions**: optional system instructions string.
- **input**: a list of items (`{role, content}`) derived from chat history.
- **tools**: optional list of `{type:"function", name, description, parameters}` definitions.
- **parallel_tool_calls**: boolean controlling parallel tool execution.
- **stream**: when `true` the server emits SSE events, when `false` it returns JSON.

## Example (stream=true)
```
curl https://api.openai.com/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{"model":"gpt-4.1","input":"Hello","stream":true}'
```
The API sends a series of events such as `response.created`, many
`response.output_text.delta` events and finally `response.completed`.

## Example (stream=false)
```
curl https://api.openai.com/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{"model":"gpt-4.1","input":"Hello"}'
```
The response body contains the final `output` array and a `usage` object.

## Non-streaming vs streaming behaviour
The tool calling loop should be identical in both helpers so that
function calls work regardless of the `stream` flag. The
`_stream_response` helper yields text chunks as they arrive, while
`_non_stream_response` waits for the loop to finish and yields the final
assistant text. Usage accounting and event emission remain the same in
both paths.

## Implementation Tips
1. Keep the new helper methods private (`_stream_response` and `_non_stream_response`).
2. Reuse existing utilities: `get_responses`, `stream_responses` and `extract_response_text`.
3. Update `Pipe.pipe()` to only set up state then delegate to the helper based on `stream`.
4. Ensure usage stats aggregation and event emission remain unchanged.
