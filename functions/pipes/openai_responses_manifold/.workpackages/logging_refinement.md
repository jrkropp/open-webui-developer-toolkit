## Workpackage: Simpler, Standard Logging

### Goal
Keep logging simple, consistent, and easy to reason about while preserving requirements (diagnostics, citations, and minimal noise).

### Principles
- Single logger namespace: everything under `openai_responses_manifold`.
- One adapter/filter to inject context (session_id, chat_id, message_id, user_id) into all records.
- One formatter; two handlers (console + memory buffer for citations).
- Clear level policy: INFO for milestones, DEBUG for detail; ERROR/WARNING for problems.
- One truncation helper for any large payloads.
- One place to emit log citations (`_flush_logs`).

### Plan / Tasks
1) **Namespace & adapter**
   - Ensure `get_logger(__name__)` always returns a logger under `openai_responses_manifold.*`.
   - Add a simple logging Filter/Adapter that injects context from ContextVars into every record (session_id, chat_id, message_id, user_id).

2) **Handler/formatter simplification**
   - Keep exactly two handlers: console and memory (for citations), both using the same key-value formatter (JSON or k=v style).
   - Remove any special-case per-module formatting.

3) **Level policy sweep**
   - INFO: start/end turn, routing decisions, tool start/end, persistence/upsert, citation flush, non-fatal recoveries, final duration.
   - DEBUG: payload snippets (trimmed), retries/backoff, per-event traces if needed.
   - WARNING/ERROR: downstream failures or malformed inputs.

4) **Truncation helper**
   - Add a shared helper to cap large payloads and annotate `truncated=true`.
   - Use it before logging request/response snippets at DEBUG.

5) **Citations hook**
   - `_flush_logs` remains the only place to emit log citations.
   - Add a DEBUG breadcrumb on flush with `lines_count` and `truncated` flags.

6) **Tests**
   - Logger namespace mapping: `function_openai_responses` → `openai_responses_manifold.*`.
   - Session context injection: records carry session_id/chat_id/message_id when set; skip cleanly when not set.
   - Buffer fill/flush: logs land in memory handler and emit via `_flush_logs`; missing session_id skips without error.
   - Truncation helper trims and sets `truncated=true`.

7) **Docs**
   - Brief logging policy: namespace, handlers, level expectations, how to enable DEBUG safely, and PII cautions (avoid logging user content at INFO and trim at DEBUG).

### Acceptance
- One namespace, one formatter, two handlers, one truncation helper, one citation emitter.
- Logs carry context automatically via filter/adapter.
- INFO surface is concise; DEBUG holds detail with truncation.
- Tests cover namespace, context injection, buffer flow, and truncation helper.
