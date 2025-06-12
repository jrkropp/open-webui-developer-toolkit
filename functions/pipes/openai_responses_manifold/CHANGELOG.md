# Changelog

All notable changes to the OpenAI Responses Manifold pipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.6] - 2025-06-12
- Added helper utilities for zero-width encoded item persistence.
- Implemented database helper functions for new response item schema.
- Refined item encoding and lookup helpers.

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
