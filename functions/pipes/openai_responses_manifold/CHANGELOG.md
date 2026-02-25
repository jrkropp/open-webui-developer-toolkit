# Changelog

All notable changes to the OpenAI Responses Manifold pipeline are documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0] - 2026-02-25
- Added GPT-5.2 family support updates in model metadata and aliases, including `gpt-5.2-codex` and `xhigh`/`none` reasoning aliases.
- Added GPT-5.3-Codex model metadata and aliases (`gpt-5.3-codex-thinking`, `-low`, `-high`, `-xhigh`).
- Mapped legacy alias `gpt-5.2-thinking-minimal` to GPT-5.2 `reasoning.effort="none"` for backwards compatibility with new API semantics.
- Updated `gpt-5-auto` fallback target to `gpt-5.2-chat-latest`.
- Added compatibility guard to strip `temperature`/`top_p` when unsupported for current GPT-5 family model + reasoning effort.
- Prevented native web search tool auto-injection when effective reasoning effort is `none` or `minimal`.

## [0.9.9] - 2025-10-01
- Added status updates for OpenAI web search events, emitting query chips, source counts, and expandable result panels.

## [0.9.8] - 2025-09-30
- Refined status sequence with mixed first-person wording, added "Exploring possible answers…" and "Almost done…", and kept router notices from cancelling thinking updates.

## [0.9.7] - 2025-09-29
- Polished progressive status wording with first-person voice, added random delays, and end with "Thought for N seconds" summary.

## [0.9.6] - 2025-09-28
- Expanded progressive thinking updates with additional status messages and clearer intervals.

## [0.9.5] - 2025-09-27
- Added progressive thinking status updates that appear before the first reasoning summary.
- Replaced the final "Done" notice with a duration-based "Processed in N seconds" message.

## [0.9.4] - 2025-09-26
- Replaced custom expandable status indicator with native status emitter.

## [0.9.1] - 2025-08-28
- Added `ENABLE_STRICT_TOOL_CALLING` valve (default: `True`). When enabled, the manifold converts Open WebUI registry tools to strict JSON Schemas and sets `strict: true` on function tools when passing to the OpenAI Responses API.

## [0.9.2] - 2025-09-25
- Introduced GPT-5 auto router: uses `gpt-4.1-nano` to analyze the prompt and update the request with the best GPT-5 variant.


## [0.9.0] - 2025-08-28
- Added `extra_tools` field for filter-injected tools with a single merge point and deduplication.
- Rewrote logic for how tools are handled.  Simplified and added support for edge cases.

## [0.8.28] - 2025-08-21
- Resolved compatibility with Open WebUI v0.6.23 by awaiting `__tools__` when
  it is provided as a coroutine.

## [0.8.26] - 2025-08-13
- Escaped tool results to prevent Markdown code block escalation.
- Fixed regex replacement in status rendering to handle backslashes safely.

## [0.8.25] - 2025-08-13
- Added placeholder `gpt-5-auto` model that currently routes to `gpt-5-chat-latest`
  and emits a "model router coming soon" notification.
- Fixed `transform_messages_to_input` to skip missing persisted items.
- Used `openwebui_model_id` to detect `gpt-5-auto` and added a stub router helper
  for future model selection.
- Clarified `MODEL_ID` description to mention supported pseudo models.

## [0.8.17] - 2025-07-01
- Added `ExpandableStatusIndicator` updates in the non-streaming loop.

## [0.8.18] - 2025-07-14
- Made `chat_id` and `openwebui_model_id` optional in
  `transform_messages_to_input` so Notes without a chat reference no longer
  raise an exception. This enables full compatibility with the new Open WebUI
  Notes feature.

## [0.8.19] - 2025-07-15
- Added inline citation support with `[n]` markers and `citation` events.

## [0.8.20] - 2025-07-28
- Simplified citation handling and removed duplicate markdown links.
- Added `CITATION_STYLE` valve to choose number or source name markers.

## [0.8.21] - 2025-08-07
- Only include `reasoning` parameter when explicitly provided.

## [0.8.16] - 2025-06-28
- Fixed custom separator handling in `ExpandableStatusEmitter`.
- Corrected `Tuple` import for type hints.
- Sorted changelog entries chronologically.

## [0.8.15] - 2025-06-27
- Switched to 16-character ULIDs and `v2` comment markers.
- Simplified ID generation with `secrets.choice`.
- Updated regex and marker utilities for the new format.
- Persisted items remain under `openai_responses_pipe` with shortened IDs.

## [0.8.14] - 2025-06-23
- Added experimental `MCP_SERVERS` valve to append remote MCP servers
  to the tools list.

## [0.8.13] - 2025-06-19
- Emitted an initial reasoning block when using reasoning models to make
  the interface show progress immediately.

## [0.8.12] - 2025-06-18
- Fixed missing final message when streaming disabled by emitting the
  complete text via `chat:completion`.

## [0.8.11] - 2025-06-17
- Fixed crash in non-streaming loop when metadata lacked a model ID.
- Added invisible link persistence for non-streaming responses.

## [0.8.10] - 2025-06-16
- Replaced zero-width item ID encoding with empty Markdown links.
- Introduced v1 markers with model metadata and removed legacy helpers.

## [0.8.9] - 2025-06-15
- Added helper to safely emit visible chunks after encoded IDs.
- Fixed blank line after reasoning block by delaying encoded ID emission.

## [0.8.8] - 2025-06-14
- Renamed helper functions for clarity and maintainability.
- Simplified rebuilding of input history.
- Added support for custom parameters from Open WebUI.
  - `max_tokens` now maps to `max_output_tokens`.
  - Additional parameters are passed through for future compatibility.
- Refined reasoning block streaming for safe token ordering.
- Replaced streaming loop with a single-flag newline injector for
  predictable token placement.

## [0.8.7] - 2025-06-13
- Embedded zero-width encoded IDs during streaming and non-streaming flows.
- Persisted each output item immediately and yielded the encoded reference.
- Rebuilt chat history using `build_openai_input` for accurate ordering.
- Stored full model ID for each item and stripped prefix only when filtering.

## [0.8.6] - 2025-06-12
- Added helper utilities for zero-width encoded item persistence.
- Implemented database helper functions for new response item schema.
- Refined item encoding and lookup helpers.
- Added `add_openai_response_items_and_get_encoded_ids` to return
  zero-width encoded references when persisting items.
- Filtered persisted item lookups by model ID when rebuilding history.
- Fixed extraction logic for consecutive encoded IDs.
- Adjusted `build_openai_input` to drop system prompts entirely since
  they are passed via the `instructions` parameter. Message whitespace
  is still preserved.

## [0.8.5] - 2025-06-10
- Added `TRUNCATION` valve to configure automatic truncation behaviour.

## [0.8.4] - 2025-06-07
- Fixed missing done flag in `_emit_error` causing hanging requests.
- Emitted log citations using new `SessionLogger` store.
- Simplified progress status messages.
- Redesigned `transform_tools` with strict mode and WebUI tool support.
- Clarified `transform_tools` internals and documented strict mode.

## [0.8.3] - 2025-06-06
- Refactored Responses API integration and introduced typed request models.
- Improved message and tool transformation.
- Added full support for task models via `_handle_task`.
- Fixed initialization of the reasoning dictionary when enabling summaries.

## [0.8.2] - 2025-06-05
- Fixed reasoning summaries leaking into subsequent turns.
- Added missing output items to subsequent requests.
- Guarded reasoning event emission when no emitter is provided.
- Implemented `_multi_turn_non_streaming` with single-request flow.
- Enabled tool-call loops in `_multi_turn_non_streaming` for parity with the streaming path.
- Added basic task model support via `_handle_task`.
- Returned OpenAI-compatible dict from `_handle_task`.
- Fixed per-session log level filtering using `ContextVar`-based filters.
- Reworked logger setup with a custom `Logger` subclass so session-specific log levels work correctly.
- Avoid errors if a streaming response ends without `response.completed`.
- Respect `PERSIST_TOOL_RESULTS` valve when saving tool outputs.

## [0.8.1] - 2025-06-05
- Refactored `_multi_turn_streaming` for simplicity and removed unused output buffer.
- Fixed log citation retrieval when debugging.

## [0.8.0] - 2025-06-04
- Always enable native tool calling for supported models.
- Removed `ENABLE_NATIVE_TOOL_CALLING` valve.
- Simplified native function setup.

## [0.7.0] - 2025-06-02
- Downgraded major version to `0` to indicate pre-production early testing stage.
- Fixed finalization logic so streamed responses always close correctly.
- Stripped `<details>` reasoning blocks from stored history to keep context clean.
- Added type-based removal helper for reasoning details to address caching issues.
- Tagged persisted items with their originating model and filtered history by model
  to avoid feeding incompatible data when switching models.
