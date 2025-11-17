> **Note:** Keep this workpackage up to date. Check off items as you finish them and add subtasks if new work appears.

## Checklist
- [x] Add turn.start INFO log
- [x] Add opt-in payload previews (request/response) with truncation/redaction
- [x] Add tool lifecycle logs (calls_started, start/complete, args preview, output_len, warn on failure)
- [x] Add turn.error line and include last_error in summary
- [x] Add tokens_sec to summary when usage+duration available
- [x] Keep delta stride configurable (default 200)
- [ ] (Optional) Add retry/backoff log hook if/where retries happen
- [x] Update example.log if needed after changes
- [x] Run make build

## Plan
1) Telemetry scaffolding
   - Add turn.start INFO at the top of `run_streaming_turn`.
   - Add tokens/sec computation and last_error in `turn.summary` (INFO).
   - Add `turn.error` ERROR line on failure.
2) Payload previews (opt-in)
   - Introduce a valve/env flag (e.g., LOG_PAYLOAD_PREVIEW or DEBUG_PAYLOADS) to gate previews.
   - Emit one DEBUG `request.payload_preview` and one DEBUG `response.payload_preview` with truncate/redact.
3) Tool lifecycle logging
   - Log `tool.calls_started count=N` (INFO) before execution.
   - For each call: DEBUG start, DEBUG args preview (already truncated), DEBUG completion with output_len, WARN on failure.
4) Delta/stride configurability
   - Keep stride configurable via env/valve; maintain default 200.
5) (Optional) Retry/backoff hook
   - If retries exist, emit INFO/DEBUG `retry.attempt` lines. Otherwise note not implemented.
6) Docs/example
   - Update `.workpackages/example.log` to reflect any format tweaks.
7) Validate
   - Run `make build`.
