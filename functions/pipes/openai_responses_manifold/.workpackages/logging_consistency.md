> **Note:** Keep this workpackage up to date. Check off items as you finish them and add subtasks if new work appears.

## Checklist
- [ ] Inventory current logging (all modules)
- [ ] Standardize levels/messages
- [ ] Ensure context injection via `get_logger` + `logging_context`
- [ ] Enforce payload hygiene/truncation
- [ ] Verify citations path and breadcrumb
- [ ] Add/adjust tests
- [ ] Update docs/README notes

## Plan: Logging Consistency Sweep

### Goal
Ensure logging across the codebase is consistent, structured, and purposeful: clear context, appropriate levels, and predictable payload handling.

### Scope
- All modules under `src/openai_responses_manifold/`: main, engine, services, infra, core, utils.
- Tests and docs as needed to lock behavior.

### Approach
1) **Inventory current logging**
   - Enumerate all `logger.` calls (INFO/DEBUG/WARN/ERROR) across modules.
   - Note message patterns, context included, and level usage.

2) **Standardize levels & messages**
   - INFO: lifecycle milestones (start/end turn, routing decisions, tool start/end, persistence/citation flush, errors surfaced to user).
   - DEBUG: payload snippets (truncated), retries/backoff, per-event traces (optionally sampled).
   - WARNING/ERROR: malformed inputs, downstream failures, unexpected states.
   - Keep messages short; let formatter carry context fields.

3) **Context injection everywhere**
   - Ensure all loggers are retrieved via `get_logger(__name__)`.
   - Wrap entrypoints (e.g., Pipe.pipe) with `logging_context(...)` so context vars enrich all logs underneath.

4) **Payload hygiene**
   - Use `truncate_for_log` on any payload/body/response snippets.
   - Avoid logging user content or secrets at INFO; keep detailed dumps at DEBUG only.
   - Add `truncated=true` in DEBUG notes if applicable.

5) **Citations path**
   - Confirm `_flush_logs` remains the single emitter of log citations.
   - Add/keep a concise DEBUG breadcrumb before citation emission (lines count, truncated flag).

6) **Tests & docs**
   - Add/adjust tests to assert context injection (fields present), truncation helper behavior, and buffer fill/flush for citations.
   - Update README/docs with logging policy (levels, context, truncation, how to enable DEBUG).

### Deliverables
- Code updates aligning logs to the level/message policy and using `get_logger` + `logging_context`.
- Payload logging wrapped with `truncate_for_log` where needed.
- Tests covering context fields, truncation helper, and citation buffer flow.
- Brief doc/update describing the logging policy and usage tips.
