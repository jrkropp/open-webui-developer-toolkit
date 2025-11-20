> **Note:** Keep this workpackage current. Check off tasks as they’re completed and add subtasks when new work is discovered.

## Checklist
- [x] Unify system-instruction extraction via a shared helper used by both `HistoryService` and `build_responses_body`.
- [x] Simplify the history resolver so `HistoryService` closes over chat/model metadata and callers only pass `item_ids`.
- [x] Introduce a minimal `HistoryRepository` abstraction that wraps `ItemStore` for persistence lookup/save.
- [x] Split history storage from marker emission so persistence can be tested independently of streaming state.
- [x] Extract a focused marker resolver helper to keep `HistoryBuilder` centered on role-to-item transforms.
- [x] Make `build_responses_body` compositional (base payload builder + history hydrator + validator) without changing behaviour.
- [x] Document the marker contract and add targeted tests for the repository/marker split, history reconstruction, and request builder composition.

---

# Workpackage: History Persistence & Reconstruction Alignment

## Background
The history layer persists structured response items, emits markers into assistant messages, and rebuilds OpenAI Responses-style inputs from stored chat messages. The current structure works but mixes concerns, making persistence, replay, and request building harder to reason about and test in isolation.

## Pain points (current state)
1. **Persistence and marker emission are intertwined with streaming state.** Storage, ULID generation, and marker formatting happen together, coupling item cleanup to response buffer mutation.
2. **Reconstruction logic mixes marker parsing with role-specific shaping.** `HistoryBuilder` resolves markers and also converts user/developer/assistant roles, obscuring the marker contract and complicating testing.
3. **Instruction extraction is duplicated.** Both `HistoryService` and `request_builder` scan for the latest system instructions with separate helpers, increasing drift risk.
4. **Resolver signatures are noisier than needed.** The resolver threads `chat_id`/`model_id` despite `HistoryService` already owning that context.
5. **Request building blends history replay with policy defaults.** `build_responses_body` sets defaults and hydrates history in one place, making the boundaries unclear.
6. **Marker contract is implicit.** Helpers live in `core.markers`, but the mapping between stored items and emitted markers is not described alongside the orchestration logic.

## Incremental refactor steps
1. **Unify system-instruction extraction.** Lift a shared `extract_system_instructions(messages)` helper and wire both `HistoryService` and `build_responses_body` to it to remove duplication.
2. **Tighten the resolver boundary.** Let `HistoryService` close over `chat_id`/`model_id` and accept only `item_ids` (plus optional filters) from callers, reducing parameter threading.
3. **Add a minimal repository shim.** Introduce `HistoryRepository` as a thin adapter over `ItemStore` (`save_output_items`, `load_items`), keeping it intentionally minimal to support in-memory fakes without over-abstracting.
4. **Separate storage from marker emission.** Have persistence clean/normalize and save items, then hand metadata to a marker renderer so streaming code can append markers without storage side effects.
5. **Extract a marker resolver helper.** Move marker parsing + lookup into a focused helper that returns reconstructed items and text segments, letting `HistoryBuilder` focus on role-to-item shaping.
6. **Make request building compositional.** Split `build_responses_body` into base payload construction, optional history hydration (input/instructions), and final validation to clarify responsibilities and testing; keep this step strictly structural with no behavioural changes.
7. **Document and test the contract.** Add short docs describing marker payloads vs stored items and anchor with unit tests for the repository/marker split, history reconstruction paths, and request builder composition.

## Testing anchors
- **Repository/marker split:** items are stored without ids; marker rendering produces expected wrapped strings for stored metadata.
- **History reconstruction:** synthetic transcripts with markers and plain text round-trip into the correct `input` list when the resolver returns matching items.
- **Request builder composition:** base payload defaults apply correctly, history hydration only triggers when `input` is absent, and provided `instructions` overrides are respected.
