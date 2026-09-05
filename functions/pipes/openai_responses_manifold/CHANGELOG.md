# Changelog

All notable changes to the OpenAI Responses Manifold pipeline are documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.15] - 2026-09-05
- Added **GPT-6 Astra** (`gpt-6-astra`), OpenAI's current flagship. Single slug — no tiers and no `gpt-6` routing alias. Same capability set as GPT-5.6 (function calling, reasoning + summaries, web search, image gen, `text.verbosity`, pro mode).
- Added effort aliases `gpt-6-astra-low`, `-high`, `-xhigh`, `-max` and pro-mode aliases `gpt-6-astra-pro`, `-pro-high`, `-pro-xhigh`, `-pro-max`. There is deliberately no `-none` alias: GPT-6 Astra rejects `reasoning.effort="none"` (supported: `low`, `medium` (default), `high`, `xhigh`, `max`).
- Added GPT-6 Astra pricing ($10.00 input / $1.00 cached / $50.00 output per 1M tokens). The >272K-token long-context surcharge and cache-write rate are not modelled; override via `CUSTOM_MODEL_PRICING_JSON` if needed.
- README: new GPT-6 Astra section covering the removed `none` effort, rejected `temperature`/`top_p`/`top_logprobs` (the manifold forwards Custom Parameters untouched — clear them), and Astra-only features the manifold doesn't configure.

## [0.9.14] - 2026-09-01
- Fixed usage/cost stats (`total_usage`, including the `cost` breakdown) never reaching Open WebUI's outlet filters or DB-persisted message. They were only ever emitted via a custom `chat:completion` socket event, which Open WebUI's event emitter broadcasts live but does not persist, and the bare-`str` return from `_run_streaming_loop` gave OWUI's core no channel to attach `usage` to. The loop now returns an async generator yielding the final content followed by a `{"usage": ...}` chunk, which flows through Open WebUI's normal chunk-parsing path into the persisted assistant message (and therefore into outlet filters) exactly like provider-reported usage does.
- Fixed a related bug in the same cleanup path: the `sources` persistence call (`Chats.upsert_message_to_chat_by_id_and_message_id`) was missing `await`, so citations were silently never written to the database.

## [0.9.13] - 2026-09-01
- Fixed stale `OpenAI: <id>` names lingering in the model picker after the 0.9.11 rename: workspace model records created before 0.9.11 store that legacy auto-name and override the pipe-provided display name. `pipes()` now performs a one-time (per process) migration that renames records still carrying a legacy auto-name (`OpenAI: <id>`, the raw id, or the prefixed id) to `ModelFamily.display_name()`. Admin-customized names are never touched.

## [0.9.12] - 2026-09-01
- Added `AUTO_ENABLE_NATIVE_FUNCTION_CALLING` valve (default: `True`) to toggle the STEP 4 side effect where the pipe persists `params.function_calling = "native"` on the model record when tools are attached.
- The auto-enable write now only fires when the model's `function_calling` setting is **missing** (unset). An explicit admin choice (e.g. `"default"`) is respected and never overridden. Previously any non-`"native"` value was overwritten.
- Added `MODEL_ICON_URL` valve (default: unset/disabled) to programmatically set a model-picker icon. `pipes()` writes the URL to each configured model record's `meta.profile_image_url` — only when no icon is set (an admin-set icon is never overridden). Models without a workspace record get a minimal one, attributed to the super-admin user. Accepts http(s) URLs or `data:image/{png,jpeg,gif,webp};base64` URIs; results are cached per process (re-synced when the valve changes) so the DB is checked at most once per model.

## [0.9.11] - 2026-09-01
- Added automatic model-list fetching: `pipes()` now queries `{BASE_URL}/models` and hides `MODEL_ID` entries whose base model isn't served by the endpoint. Pseudo-models (e.g. `gpt-5-auto`) are always kept, and the full configured list is used as a fallback when the fetch fails or nothing matches.
- Added `FETCH_MODELS` valve (default: `True`) to toggle the behavior, and `MODEL_FETCH_TTL_SECONDS` valve (default: `600`, minimum 60) to cache the fetched list so `/models` isn't hit on every model-picker refresh. Failures are cached for the same TTL (stale-while-error).
- Model entries now use human-friendly display names parsed from the id via `ModelFamily.display_name()` (e.g. `gpt-5.6-luna-pro` → "GPT 5.6 Luna Pro", `o4-mini-deep-research` → "o4 Mini Deep Research"), replacing the previous `OpenAI: <id>` format. The `-none` effort suffix is dropped from names (`gpt-5.6-sol-none` → "GPT 5.6 Sol").

## [0.9.10] - 2026-09-01
- Added estimated USD cost to the usage stats emitted to Open WebUI (shown as a `cost` block alongside token counts): `input_cost`, `cached_input_cost`, `output_cost`, and `total_cost`.
- Added a built-in per-model price table (`ModelFamily._PRICING`, USD per 1M tokens) with alias/date-suffix resolution. Cached input tokens are billed at the cached rate; the remainder at the full input rate.
- Added `SHOW_USAGE_COST` valve (default: `True`) to toggle cost reporting.
- Added `CUSTOM_MODEL_PRICING_JSON` valve to override or extend the built-in price table without code changes, e.g. `{"gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0}}`.
- Costs are recomputed from cumulative token counts after each tool-call loop (never merged per-turn) to avoid double counting, and pricing follows the actual served model reported by the API (e.g. after `gpt-5-auto` routing).
- Note: costs are estimates from published token rates and exclude tool surcharges (e.g. web search). Verify the newer GPT-5.x family rates against your OpenAI pricing page and correct via `CUSTOM_MODEL_PRICING_JSON` if needed.

## [0.9.8-5.6] - 2026-07-28
- Added the **GPT-5.6** family: `gpt-5.6-sol` (flagship), `gpt-5.6-terra` (balanced), and `gpt-5.6-luna` (high volume). Same capability set as GPT-5.5 (function calling, reasoning + summaries, web search, image gen, `text.verbosity`).
- Added `gpt-5.6` alias, matching OpenAI's own routing of `gpt-5.6` → `gpt-5.6-sol`.
- Added reasoning-effort aliases for all three tiers, including the new `max` effort: `-none`, `-low`, `-high`, `-xhigh`, `-max`. Unsuffixed IDs use OpenAI's `medium` default.
- Added pro-mode aliases on the flagship tier (`gpt-5.6-sol-pro`, `-pro-high`, `-pro-xhigh`, `-pro-max`). GPT-5.6 has no separate `-pro` model slug; pro is `reasoning.mode: "pro"`, which is independent of `reasoning.effort`.
- Refreshed `README.md` model tables, which still described GPT-5.1 as current and listed `gpt-5-thinking*` aliases that no longer exist in the code.

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
