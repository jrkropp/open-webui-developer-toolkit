# Changelog

All notable changes to the OpenAI Responses Manifold pipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.2] - 2025-06-05
- Fixed reasoning summaries leaking into subsequent turns.
- Added missing output items to subsequent requests.
- Guarded reasoning event emission when no emitter is provided.

## [0.8.3] - 2025-06-06
- Improved error handling in `_multi_turn_streaming`.
- Flushed partial reasoning when streaming is interrupted.

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
