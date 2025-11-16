# ⚙️ Work Package — OpenAI Responses Manifold Refactor (based on Developer Guide v2)

> **For AI agents & humans**
>
> * **Keep this work package up-to-date** as you work.
> * If you discover new tasks or risks, **add them** under the appropriate section and link your changes/commits.
> * Start with the **Assessment** section, then proceed phase-by-phase.
> * This plan implements the structure described in the **Developer Guide (v2 design)** (functions/pipes/openai_responses_manifold/docs/DEVELOPER_GUIDE.md) we just produced.

---

## ✅ Live Checklist (update as you go)

**Phase 0 — Assessment**

* [ ] 0.1 Read current single-file module and confirm all sections present (capabilities, pipe, models, markers, persistence, client, tools, router, session logger, utils).
* [ ] 0.2 Build a **Current→Target mapping** (fill table below with exact function names & line refs).
* [ ] 0.3 Identify any **hidden coupling** (e.g., DB I/O inside transform functions).
* [ ] 0.4 Inventory **OpenWebUI integration points** (events emitted, `Chats` writes, model list, tools registry usage).
* [ ] 0.5 Confirm **marker namespace** and **store key** to maintain backward compatibility (default: `openai_responses:v2` and `openai_responses_pipe`).

**Phase 1 — Project Skeleton**

* [ ] 1.1 Create folders/files per **Project structure** below.
* [ ] 1.2 Add `__init__.py` everywhere.
* [ ] 1.3 Add placeholder docstrings that reference the **Developer Guide v2** sections.

**Phase 2 — Core (pure logic, no I/O)**

* [ ] 2.1 `core/api_models.py`: move `CompletionsBody`, `ResponsesBody` (+ alias defaults validator).
* [ ] 2.2 `core/ids.py`: implement `normalize()`, `base_model()` (prefix/dot/date-safe).
* [ ] 2.3 `core/capabilities.py`: move `MODEL_FEATURES`, `MODEL_ALIASES`, `supports()`.
* [ ] 2.4 `core/messages.py`: user/dev/assistant block helpers (text/image/file → Responses items).
* [ ] 2.5 `core/markers.py`: move marker syntax helpers (no DB).
* [ ] 2.6 `core/errors.py`: define typed exceptions.

**Phase 3 — Infra (I/O implementations)**

* [ ] 3.1 `infra/openai_client.py`: implement `OpenAIResponsesClient.create()` + `.stream()` (aiohttp).
* [ ] 3.2 `infra/openwebui_store.py`: implement `ItemStore.save_items()` / `load_items()` using `open_webui.models.chats.Chats` (stable key).

**Phase 4 — Services (domain services with infra)**

* [ ] 4.1 `services/history.py`:

  * [ ] `HistoryPersistence.persist_items_for_message()` (items→ULIDs→markers).
  * [ ] `HistoryBuilder.build_input_from_messages()` (markers→items).
* [ ] 4.2 `services/tools.py`:

  * [ ] `build_tools(...)` (OpenWebUI registry → OpenAI tools; web_search/MCP; strict JSON Schema).
  * [ ] `execute_tool_calls(...)` (sync/async; safe error mapping).
* [ ] 4.3 `services/routing.py`: `route_auto_model(...)` (helper model to set final model + effort).

**Phase 5 — Engine (single-turn orchestration)**

* [ ] 5.1 `engine.py`: `ResponsesEngine.run_streaming_turn(...)` (SSE, tool loops, persistence, events).
* [ ] 5.2 Event helpers usage (`utils/events.py`) for status/usage/chat:message/citation/completion.
* [ ] 5.3 Integrate `SessionLogger` (`utils/logging.py`) & emit end-of-run “Logs” citation.

**Phase 6 — Adapter (OpenWebUI Pipe)**

* [ ] 6.1 `main.py`: implement `Pipe` with `pipes()` and `pipe()` (thin adapter).
* [ ] 6.2 `settings.py`: move & scope **Valves** (`PipeValves`, `UserValves`), merge logic from old `Pipe`.
* [ ] 6.3 Ensure **no hard-coded Function ID** logic; rely on `core.ids.normalize()` for capabilities.

**Phase 7 — Tests & QA**

* [ ] 7.1 Unit tests (core): ids, markers, api_models.
* [ ] 7.2 Service tests: history (builder/persistence), tools (build/execute), routing.
* [ ] 7.3 Engine smoke test: mock SSE stream; assert emissions and loops.
* [ ] 7.4 Backward compatibility: existing chats still resolve markers; Function ID rename does not break.

**Phase 8 — Packaging / Build**

* [ ] 8.1 (Optional) Add `scripts/bundle.py` and `Makefile` `build` target to produce a single-file `openai_responses_manifold.py`.
* [ ] 8.2 Verify the monolith imports cleanly in OpenWebUI.

**Phase 9 — Documentation**

* [ ] 9.1 Add **Developer Guide v2** to repo (`docs/DEVELOPER_GUIDE.md`).
* [ ] 9.2 Add this **Work Package** to repo (`docs/WORK_PACKAGE.md`).
* [ ] 9.3 Update README with quick-start and structure summary.

**Phase 10 — Rollout**

* [ ] 10.1 PRs organized by phases above, with checklists.
* [ ] 10.2 Backout plan: keep a tag of the current single-file version.
* [ ] 10.3 Announce changes and migration notes for contributors.

---

## 📦 Scope & Goals

* **Goal:** Restructure the manifold per **Developer Guide (v2 design)** into clear, conventional layers that are intuitive to OpenWebUI users, OpenAI API developers, and Python developers.
* **Non-goals:** Rewrite business rules or behavior; we’re refactoring structure. Behavior should remain compatible (markers, store key, features).

---

## 🗂 Target Project Structure (authoritative)

```
openai_responses_manifold/
├─ main.py                      # Pipe (OpenWebUI manifold adapter)
├─ settings.py                  # Valves (PipeValves, UserValves)
├─ engine.py                    # ResponsesEngine (single-turn orchestrator)
├─ core/
│  ├─ __init__.py
│  ├─ api_models.py             # CompletionsBody, ResponsesBody (+ alias defaults)
│  ├─ messages.py               # message block helpers
│  ├─ capabilities.py           # MODEL_FEATURES, MODEL_ALIASES, supports()
│  ├─ ids.py                    # normalize(), base_model() – prefix/dot/date safe
│  ├─ markers.py                # marker format/parse/split
│  └─ errors.py                 # typed exceptions
├─ services/
│  ├─ __init__.py
│  ├─ history.py                # HistoryPersistence, HistoryBuilder
│  ├─ tools.py                  # build_tools(), execute_tool_calls()
│  └─ routing.py                # route_auto_model()
├─ infra/
│  ├─ __init__.py
│  ├─ openai_client.py          # OpenAIResponsesClient.create()/stream()
│  └─ openwebui_store.py        # ItemStore.save_items()/load_items()
├─ utils/
│  ├─ __init__.py
│  ├─ logging.py                # SessionLogger
│  └─ events.py                 # OpenWebUI event helpers
└─ docs/
   ├─ DEVELOPER_GUIDE.md        # Developer Guide (v2 design)
   └─ WORK_PACKAGE.md           # This file
```

---

## 🔁 Current → Target Mapping (fill during Phase 0)

> AI agent: expand this table with line refs or anchors to help reviewers.

| Current section / function                                                  | Target module & symbol                                                                         | Notes / changes                                                          |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `core/capabilities.py` (`MODEL_FEATURES`, `MODEL_ALIASES`, `supports`)      | `core/capabilities.py`                                                                         | Mostly move; drop `MODEL_PREFIX` stripping from here; rely on `core/ids` |
| `core/models.py::CompletionsBody`, `ResponsesBody`                          | `core/api_models.py`                                                                           | Keep validator for alias defaults                                        |
| `core/models.py::transform_messages_to_input`                               | `services/history.py::HistoryBuilder.build_input_from_messages` (+ `core/messages.py` helpers) | Inject resolver; remove DB/Chats coupling                                |
| `core/markers.py`                                                           | `core/markers.py`                                                                              | Move as-is (pure)                                                        |
| `core/session_logger.py`                                                    | `utils/logging.py`                                                                             | Rename to `SessionLogger`, keep ContextVar behavior                      |
| `core/utils.py::wrap_event_emitter`, `merge_usage_stats`, `wrap_code_block` | `utils/events.py` (emission helpers), `engine.py` (aggregate usage)                            | Prefer focused helpers; keep `wrap_code_block` where used                |
| `features/tools.py::build_tools`                                            | `services/tools.py::build_tools`                                                               | Keep strict JSON Schema option; dedupe                                   |
| `features/router.py::route_gpt5_auto`                                       | `services/routing.py::route_auto_model`                                                        | Keep router prompt in-module or separate prompt file                     |
| `infra/client.py::OpenAIResponsesClient`                                    | `infra/openai_client.py`                                                                       | Rename methods to `create`/`stream`                                      |
| `infra/persistence.py` (persist/fetch)                                      | `infra/openwebui_store.py::ItemStore` and `services/history.py::HistoryPersistence`            | Split storage vs markers                                                 |
| `pipe.py::ResponseRunner`                                                   | `engine.py::ResponsesEngine`                                                                   | Orchestrator for turn; event emissions; tool loops                       |
| `pipe.py::Pipe` (+ Valves)                                                  | `main.py::Pipe` and `settings.py`                                                              | Keep `pipes()` and `pipe()` thin; valves moved                           |

---

## 🧭 Execution Phases (details & acceptance criteria)

### Phase 0 — Assessment

* **Deliverables:** Completed Current→Target Mapping table; list of couplings to untangle (DB I/O inside transforms; Function ID assumptions; web_search parallelism side effects).
* **Acceptance:** Table is filled; risks identified; no refactors yet.

### Phase 1 — Project Skeleton

* Create folders/files with module docstrings linking **Developer Guide v2**.
* **Acceptance:** `pytest -q` is runnable (even if empty); import graph is clean.

### Phase 2 — Core

* Migrate pure logic without changing behavior.
* Implement `core/ids.normalize()` correctly (prefix strip only when suffix in known models/aliases; strip `-YYYY-MM-DD`; handle dotted IDs).
* **Acceptance:** Unit tests for ids/markers/models pass; no infra imports in `core/`.

### Phase 3 — Infra

* Implement `OpenAIResponsesClient.create/stream` with aiohttp.
* Implement `ItemStore.save_items/load_items` with stable key `openai_responses_pipe`.
* **Acceptance:** Mocks can verify both APIs; no domain logic in infra.

### Phase 4 — Services

* **HistoryPersistence:** items→ULIDs→markers; returns concatenated marker string.
* **HistoryBuilder:** messages→(scan markers)→resolve→full Responses input.
* **Tools:** build tools (function/web_search/MCP) and execute calls (sync/async).
* **Routing:** auto routing function with JSON schema response.
* **Acceptance:** Service tests cover marker round-trip, tool build/exec, routing merge.

### Phase 5 — Engine

* Orchestrate one turn: build body, attach tools, route if needed, stream SSE, run tools, persist items, emit events, finalize.
* Use `utils/events` and `utils/logging`.
* **Acceptance:** Engine smoke test passes; event order & content as expected; tool loops terminate; usage aggregated.

### Phase 6 — Adapter

* `Pipe.pipes()` from `settings.MODEL_ID`.
* `Pipe.pipe()` thin: wiring + delegation only.
* **Acceptance:** No infra or heavy logic in `main.py`; honors user valves; no Function ID dependency in capabilities.

### Phase 7 — Tests & QA

* Add tests mentioned in **Testing guidance** of the Developer Guide.
* **Acceptance:** All tests pass; covers normalization, markers, tool execution, routing, engine flow.

### Phase 8 — Packaging / Build

* Optional: `scripts/bundle.py` and `Makefile build` to output **single-file** artifact.
* **Acceptance:** Monolith imports and runs in OpenWebUI; smoke test works.

### Phase 9 — Documentation

* Add **Developer Guide v2** and this **Work Package** to `docs/`.
* Update README with structure & quick start.
* **Acceptance:** Docs readable, consistent, and reference code.

### Phase 10 — Rollout

* PRs per phase; backout tag; migration note (Function ID independence; stable marker/store keys).
* **Acceptance:** Merged with approvals; old chats still resolve markers.

---

## 🧪 Testing Matrix (must cover)

* **IDs:**

  * raw: `gpt-5` → `gpt-5`
  * dotted: `gpt-4.1` → `gpt-4.1`
  * dated: `gpt-4.1-2025-11-03` → `gpt-4.1`
  * prefixed: `anyfunc.gpt-4.1-2025-11-03` → `gpt-4.1` (if known suffix)
  * alias: `gpt-5-thinking-high` → base `gpt-5` + defaults merged
* **Markers:** encode/parse/split round-trips; marker segments interleaved with text.
* **HistoryBuilder:** user/dev blocks + assistant with markers restored; resolver absent → ignore markers.
* **Tools:** build specs (strict on/off), web_search gating on reasoning effort minimal, execute sync/async with error mapping.
* **Routing:** parse JSON; merge `model`, `reasoning.effort`; store `model_router_result`.
* **Engine:** SSE happy path (text deltas, usage, tool call loop), error path (emit error + logs citation).
* **Back-compat:** existing markers load; Function ID rename does not affect capability checks or persistence.

---

## 🛡️ Invariants & Risks

**Invariants**

* **Never** hard-code Function ID for normalization/capabilities.
* Marker namespace **stable** (`openai_responses:v2`).
* Store key **stable** (`openai_responses_pipe`).
* Capability checks always via `core.capabilities.supports()` after `core.ids.normalize()`.
* Only attach tools when model supports function calling.

**Risks & Mitigations**

* *Risk:* Hidden infra coupling in transforms.
  *Mitigation:* `HistoryBuilder` uses injected resolver; no infra imports in core/services.
* *Risk:* Web search tool disables parallel tool calls.
  *Mitigation:* Respect valves; document behavior; test both paths.
* *Risk:* Router JSON shape changes.
  *Mitigation:* Tolerant parse; bounds checking; default fallback to original `model`.
* *Risk:* Old chats break on rename.
  *Mitigation:* Keep stable namespace & store key; add fallback loader if needed.

---

## 📣 Agent Operating Notes

* **Update this Work Package** as you proceed:

  * Add subtasks, decisions, risks, and links to commits/PRs.
  * Keep the **Live Checklist** accurate.
* When you complete a phase, **check it off**, add a short summary, and proceed.
* If you discover unplanned work, **add it** under the relevant phase with `[NEW]` and rationale.

---

## 🔚 Definition of Done

* Codebase matches the **Target Project Structure**.
* All **tests pass** and coverage added for new boundaries.
* **Backward compatibility** validated (markers resolve, Function ID rename safe).
* **Docs** (Developer Guide v2 + Work Package + README) updated and accurate.
* (Optional) **Bundle** builds a single-file artifact that works in OpenWebUI.