> **Note:** Keep this workpackage current. Check off tasks as they’re completed and add subtasks when new work is discovered.

## Checklist
[x] Decide and document the final schema layout: `core/requests.py` (outbound DTOs) and `core/events.py` (inbound SSE events); update imports across engine/infra/tests.
[x] Harden outbound request models: Pydantic with `extra="forbid"`, clear validators, and a single serialization path (`model_dump(exclude_none=True)`).
[x] Harden inbound events: discriminated union keyed by `type: Literal[...]`; include only documented OpenAI event types; add parser tests for happy/unknown cases.
[x] Update `OpenAIResponsesClient` to accept request models, serialize strictly, and yield typed events (no raw dict fallbacks in production path).
[x] Refactor `engine.py` to pattern-match on typed events only; remove handling of undocumented/legacy event shapes; ensure streamed text/tool loops work with the new types.
[x] Refresh fakes/fixtures/tests to emit/consume validated schemas; enforce validation in fakes to catch drift.
[x] Update docs (README/STREAMING_EVENTS) describing the schema split and how to extend when OpenAI adds new event types.
[x] Introduce a request builder adapter (e.g., `services/request_builder.py`) to convert OpenWebUI-style payloads + valves/metadata into a validated `ResponsesBody`; wire engine to use it.
[x] Remove legacy shims/back-compat code paths entirely (e.g., no `from_completions` fallbacks, no raw event dict handling); fail fast on unsupported shapes and unknown event types (in progress).
[x] Confirm a full `make test`/`make build` passes with the new structure and regenerate the monolith.
[x] Finalize `core/requests.py` (document intent, ensure only the validated DTOs are exported/used, and align README/docs references).

### Upcoming subtasks
- None (complete)

## Why this matters
- **Safety:** Prevents accidental/unknown fields from being sent (avoids 400s like the `tools[5].name` issue) and catches schema drift early via validation.
- **Clarity:** Clean split of outbound requests vs inbound events makes the engine and client easier to reason about; no dict poking.
- **Maintainability:** Adding/removing event types or request fields becomes localized changes; tests/fakes share the same schemas.
- **Developer experience:** Clear docs/tests reduce onboarding time and speed up debugging (typed events, strict requests, consistent logging).
