> ### Agent instruction (read first)
>
> * This document is **authoritative**. If code and this document disagree, **update this document first**, then the code.
> * Keep the checklist up to date (`[ ]` → `[x]`), and add new items as you discover more work.
> * **Do not modify** `src_old/` or `test_old/` except to read them for reference. All new work must go under `src/` and `tests/`.
> * Prefer small, incremental commits aligned to checklist items. Optionally add commit ids next to completed bullets.
> * When in doubt about a specific subsystem, check the corresponding doc under
>   `functions/pipes/openai_responses_manifold/docs/`.

---

## Supporting docs (where to look for details)

These Markdown docs live under:

> `functions/pipes/openai_responses_manifold/docs/`

They provide focused deep‑dives for each critical part of the manifold:

* **Index & map**

  * `index.md`
    High‑level overview + links to all the docs and this workpackage.

* **Persistence & history**

  * `markers_and_persistence.md`
    Marker format, ULIDs, DB layout, how invisible markers and stored items interact.
  * `history_manager.md`
    How `messages[]` are transformed into Responses `input[]` and back, using markers.

* **Tools & engine**

  * `tools_and_extra_tools.md`
    Tool sources, filter `extra_tools`, strict schemas, dedupe behavior.
  * `responses_engine.md`
    Streaming loop, tool call loop, reasoning summary, usage merging.

* **Search, citations, routing**

  * `web_search_and_citations.md`
    Web search tool behavior, status events, and citation recording.
  * `routing_and_model_catalog.md`
    Model aliases, capabilities, and gpt‑5 auto routing behavior.

* **Integration & config**

  * `openwebui_integration.md`
    How this manifold plugs into Open WebUI (Chats, Models, events, Pipe contract).
  * `config_and_valves.md`
    PipeValves/UserValves reference and operational guidance.

> **Agent:** When implementing or modifying a subsystem (markers, tools, engine, etc.), read the corresponding doc as well as this workpackage, and keep them in sync.

---

## Work Package Checklist

### Phase 0 – Skeleton & wiring

* [ ] Create new `src/openai_responses_manifold/` package with `core`, `openai_api`, `domain`, `openwebui`, `pipe.py`
* [ ] Create mirrored `tests/` structure for the new packages
* [ ] Ensure `Pipe` is importable from `openai_responses_manifold.pipe` and passes a trivial smoke test
* [ ] Create initial docs index at `functions/pipes/openai_responses_manifold/docs/index.md` and link this workpackage

### Phase 1 – Core & OpenAI client

* [ ] Implement `core.config` (PipeValves, UserValves, RuntimeConfig, merge helper) — see `docs/config_and_valves.md`
* [ ] Implement `core.logging` (SessionLogger-style context + log buffer) — see `docs/config_and_valves.md` (logging section)
* [ ] Implement `core.model_catalog` (normalize, aliases, feature flags, supports) — see `docs/routing_and_model_catalog.md`
* [ ] Implement `core.markers` (v2 marker format encode/decode/split) — see `docs/markers_and_persistence.md`
* [ ] Implement `openai_api.types` (ResponsesRequest + ResponsesEvent union)
* [ ] Implement `openai_api.client` (stream + non-stream) with tests using faked HTTP — see `docs/responses_engine.md` (event expectations)

### Phase 2 – Domain (engine, history, tools, routing)

* [ ] Implement `domain.types` (TurnContext, TurnState, TurnResult, ToolCall, ToolResult, Citation, RuntimeEvents protocol)
* [ ] Implement `domain.history` (HistoryStore + HistoryManager using markers + DB layout compatible with old manifold) — see `docs/history_manager.md` + `docs/markers_and_persistence.md`
* [ ] Implement `domain.tools` (ToolDefinition, ToolRegistry, ToolExecutor, ToolPolicy incl. `extra_tools` merge & dedupe) — see `docs/tools_and_extra_tools.md`
* [ ] Implement `domain.web_search` (build & tune web_search tools) — see `docs/web_search_and_citations.md`
* [ ] Implement `domain.code_interpreter` (handle code_interpreter events & outputs → status/citation)
* [ ] Implement `domain.routing` (gpt‑5‑auto router helper) — see `docs/routing_and_model_catalog.md`
* [ ] Implement `domain.engine.ResponsesEngine` (streaming loop + tool loops + reasoning summary + usage merge) — see `docs/responses_engine.md`
* [ ] Add unit tests for history, tools, engine (no OpenWebUI imports)

### Phase 3 – OpenWebUI integration

* [ ] Implement `openwebui.store.OpenWebUIHistoryStore` using `Chats` and the `openai_responses_pipe` structure — see `docs/openwebui_integration.md` + `docs/markers_and_persistence.md`
* [ ] Implement `openwebui.events.OpenWebUIRuntimeEvents` (wrap `__event_emitter__`) — see `docs/openwebui_integration.md`
* [ ] Implement `openwebui.tools` (OpenWebUIToolRegistry + OpenWebUIToolExecutor) — see `docs/tools_and_extra_tools.md`
* [ ] Implement `openwebui.bridge` (Completions → Responses mapping, including filter `extra_tools`) — see `docs/history_manager.md` + `docs/tools_and_extra_tools.md`
* [ ] Implement `pipe.Pipe` wiring everything together, including **task** path — see `docs/openwebui_integration.md`
* [ ] Add integration tests for `Pipe.pipe()` with mocked OpenAI client, Chats, Models, and event emitter

### Phase 4 – Persistence, filters, UX & polish

* [ ] Implement marker-based persistence & replay end‑to‑end (tool calls, tool results, reasoning) — see `docs/markers_and_persistence.md` + `docs/history_manager.md`
* [ ] Ensure compatibility with filter-injected tools via `body.extra_tools` — see `docs/tools_and_extra_tools.md`
* [ ] Implement SessionLogger → log-as-citation behavior at the end of the turn — see `docs/config_and_valves.md`
* [ ] Implement citation handling (url_citation annotations, Chats.upsert_message_to_chat_by_id_and_message_id) — see `docs/web_search_and_citations.md`
* [ ] Implement non-streaming task path via Responses API for `__task__` models (titles, tags, etc.) — see `docs/openwebui_integration.md`
* [ ] Optionally re-introduce status UI tweaks (multi-line status line) via `__event_call__` — see `docs/openwebui_integration.md`
* [ ] Port any critical behavior from `src_old/` (usage merging, reasoning summary flags, PERSIST_REASONING_TOKENS) into the new layers — cross-check with `docs/responses_engine.md` and `docs/config_and_valves.md`
* [ ] Add README / developer docs summarizing architecture and flows — link from `docs/index.md`
* [ ] Clearly mark `src_old/` and `test_old/` as legacy in docs — e.g., in `docs/index.md` and `docs/openwebui_integration.md`

> **Agent note:**
> Update bullets as you go, e.g.:
> `- [x] Implement core.markers — v2-compatible parsing (commit abc123)`

---

# 1. Objective

### Goal

Rebuild the **OpenAI Responses API manifold** for Open WebUI as a clean, layered, testable system that:

* Exposes a **Pipe** compatible with Open WebUI’s pipe/function API.
* Speaks the **OpenAI Responses API** natively (streaming, tools, reasoning, web_search, MCP, etc.).
* Preserves and extends behavior from the older production manifold:

  * Marker-based persistence and replay,
  * Filter-injected tools via `extra_tools`,
  * Reasoning summaries and encrypted reasoning tokens,
  * Web search and citations,
  * Per-session logging.

You will:

* Implement a **modular architecture** (core → openai_api → domain → openwebui → Pipe).
* Respect **Open WebUI’s `messages[]` and filter system** as the single source of conversation context.
* Recreate and refine **persistence using invisible markers** plus DB storage.
* Ensure **filter-injected tools** remain fully supported and deduplicated.

The result should:

* Have **high cohesion / low coupling** (each module has a clear role).
* Be **obvious to navigate**: a newcomer should understand the system by reading the file tree, this workpackage, and the docs under `functions/pipes/openai_responses_manifold/docs/`.

---

# 2. Context (what you are starting from)

You have:

* A prior modular design (from earlier iterations) that already separated:

  * config, logging, model catalog, markers,
  * openai client,
  * domain engine/history/tools,
  * openwebui adapters.
* A **legacy monolithic implementation** (`src_old/openai_responses_manifold.py`) which is:

  * Production-proven,
  * Feature-complete,
  * But large and less readable.

> For deeper background on the old behavior and how it maps to the new layout, see:
>
> * `docs/markers_and_persistence.md`
> * `docs/history_manager.md`
> * `docs/responses_engine.md`
> * `docs/openwebui_integration.md`

Key aspects from the legacy manifold you **must reproduce** or adapt:

1. **Open WebUI integration points**

   * Chat store and updates:

     * `from open_webui.models.chats import Chats`
     * `Chats.update_chat_by_id(...)`
     * `Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, {"sources": ...})` for attaching citations.

   * Model settings:

     * `from open_webui.models.models import ModelForm, Models`
     * Used to auto-enable `params["function_calling"] = "native"` when tools are present and model supports function calling.

   * `get_last_user_message` may be used for certain flows (optional; not mandatory to re-use).

   > See `docs/openwebui_integration.md` for the full mapping of these calls into `openwebui.store`, `openwebui.bridge`, and `pipe.Pipe`.

2. **Marker & persistence mechanism**

   * Hidden markers embedded in assistant `content`:

     ```text
     [openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #
     ```

   * Marker spec:

     ```text
     [openai_responses:v2:<item_type>:<ULID16>[?k=v&...]]: #
     ```

   * DB layout under `chat.chat["openai_responses_pipe"]`:

     ```python
     {
       "__v": 3,
       "items": {
         "<id>": {
           "model": "<openwebui_model_id>",
           "created_at": <unix_timestamp>,
           "payload": { ... raw Responses item ... },
           "message_id": "<message_id>",
         },
         ...
       },
       "messages_index": {
         "<message_id>": {
           "role": "assistant",
           "done": True,
           "item_ids": ["<id1>", "<id2>", ...],
         },
         ...
       },
     }
     ```

   * Helpers:

     * `persist_openai_response_items(...)` — persists one or more items, returns concatenated markers.

     * `fetch_openai_response_items(...)` — loads items by ULIDs; can filter by `openwebui_model_id`.

     * Marker parsing / splitting functions.

   > See `docs/markers_and_persistence.md` for the full spec and invariants.

3. **Filter-injected tools**

   * Filters can add tools into `body.extra_tools` and expect the manifold to merge:

     ```python
     body.setdefault("extra_tools", []).append({
         "type": "function",
         "name": "weather_lookup",
         "description": "Get current weather by city.",
         "parameters": {...},
     })
     ```

   * The manifold must:

     * Merge `body.tools` + `body.extra_tools` into a final `tools` list.

     * Deduplicate by `(type, name)` (last/first wins per policy, documented in `domain.tools`).

     * Convert Open WebUI registry tools into Responses function tools.

     * Preserve support for web_search / MCP tools as separate types.

   > See `docs/tools_and_extra_tools.md` for details and examples.

4. **Open WebUI completion → Responses mapping**

   * Legacy `ResponsesBody.from_completions()`:

     * Drops unsupported completions fields (`frequency_penalty`, `presence_penalty`, `n`, `stop`, `functions`, `function_call`, etc.).

     * Renames `max_tokens` → `max_output_tokens`.

     * Maps `reasoning_effort` → `reasoning.effort`.

     * Extracts last `system` message as `instructions`.

     * Uses `transform_messages_to_input(...)` to produce Responses `input[]`, with marker rehydration.

     * Leaves room for extra parameters (e.g., custom model settings).

   > See `docs/history_manager.md` and `docs/openwebui_integration.md` for how this logic is re-expressed in `openwebui.bridge` + `domain.history`.

5. **Streaming event behavior & statuses**

   * The old manifold:

     * Handles `response.output_text.delta` for incremental deltas.
     * Handles `response.reasoning_summary_text.done` to update a multi-line status (“Thinking…”, explanation).
     * Handles `response.output_text.annotation.added` of type `url_citation` to:

       * Emit `source` events with citations,
       * Record them in `emitted_citations`,
       * Store them with `Chats.upsert_message_to_chat_by_id_and_message_id` at the end.
     * Handles `response.output_item.added` / `done` to show tool status (“Running tool …”, “Let me skim those files…”).
     * On completion:

       * Persists structured items and injects markers,

       * Merges usage stats and emits `chat:completion`.

   > See `docs/responses_engine.md` and `docs/web_search_and_citations.md` for the new engine design and status/citation behavior.

6. **Logging**

   * Legacy `SessionLogger`:

     * Uses contextvars (`session_id`, `log_level`).

     * Stores logs in a deque buffer keyed by session_id.

     * Emits logs as a “Logs” citation at the end of the turn if enabled.

   > See `docs/config_and_valves.md` (logging section) for how this is expected to work now.

7. **Settings & valves**

   * Model list, API base/keys, reasoning summary level, persistence knobs, web search knobs, prompt cache key, etc.
   * `PERSIST_REASONING_TOKENS`:

     * `disabled`, `response`, `conversation` controlling when to request & persist `reasoning.encrypted_content`.

   > See `docs/config_and_valves.md` for a full description of each valve and its impact.

---

# 3. Target architecture / structure (ideal)

We keep the 4-layer structure:

1. **core** — generic infrastructure (config, logging, model catalog, markers).
2. **openai_api** — OpenAI Responses types + HTTP client.
3. **domain** — engine, history, tools, routing; completely UI-agnostic.
4. **openwebui** — adapters for Open WebUI (Chats, Models, events, tools, bridging).

```text
PROJECT_ROOT/
  src/
    openai_responses_manifold/
      __init__.py                # Re-export Pipe
      pipe.py                    # Pipe implementation loaded by Open WebUI

      core/
        __init__.py
        config.py                # PipeValves, UserValves, RuntimeConfig, merge_valves()
        logging.py               # SessionLogger-like logging + log buffer
        model_catalog.py         # ModelFamily-style alias + features
        markers.py               # Marker encode/decode/split (v2-compatible)

      openai_api/
        __init__.py
        types.py                 # ResponsesRequest + ResponsesEvent models
        client.py                # OpenAIClient (stream + create)

      domain/
        __init__.py
        types.py                 # TurnContext, TurnState, TurnResult, ToolCall, ToolResult, Citation, RuntimeEvents
        history.py               # HistoryStore + HistoryManager (marker rehydration + persistence)
        tools.py                 # ToolDefinition, ToolRegistry, ToolExecutor, ToolPolicy (tools + extra_tools + strict schemas)
        web_search.py            # Web search tool construction + policy
        code_interpreter.py      # CI-specific event/item handling
        routing.py               # GPT-5 auto-router helper
        engine.py                # ResponsesEngine orchestrating streaming + tool loops

      openwebui/
        __init__.py
        store.py                 # OpenWebUIHistoryStore (uses Chats + openai_responses_pipe layout)
        events.py                # OpenWebUIRuntimeEvents (wraps __event_emitter__)
        tools.py                 # OpenWebUIToolRegistry + OpenWebUIToolExecutor
        bridge.py                # Completions → Responses mapping (messages + tools + extra_tools)

  tests/
    test_core_config.py
    test_core_model_catalog.py
    test_core_markers.py
    test_core_logging.py

    openai_api/
      test_client_streaming.py
      test_client_nonstream.py

    domain/
      test_history_manager.py
      test_tools_policy.py
      test_engine_no_tools.py
      test_engine_with_tools.py
      test_engine_reasoning_and_citations.py

    openwebui/
      test_bridge_mapping.py
      test_store_persistence.py
      test_pipe_integration_streaming.py
      test_pipe_task_model.py
```

> **Docs cross‑refs:**
>
> * Overall architecture & map → `docs/index.md`
> * core.* → `docs/config_and_valves.md`, `docs/routing_and_model_catalog.md`, `docs/markers_and_persistence.md`
> * domain.* → `docs/history_manager.md`, `docs/tools_and_extra_tools.md`, `docs/responses_engine.md`, `docs/web_search_and_citations.md`, `docs/routing_and_model_catalog.md`
> * openwebui.* → `docs/openwebui_integration.md`

---

# 4. Design (for this workpackage)

Below is a condensed version of the design, with explicit references to the detailed docs.

## 4.1 Design goals

* **Clarity**

  * Each module has a single, obvious job.
  * OpenAI-specific, OpenWebUI-specific, and pure-domain logic are cleanly separated.

* **Maintainability**

  * Adding a new OpenAI feature (e.g. new output item type) touches the **domain + openai_api** layers.
  * Implementing a new UI integration touches only the **openwebui** layer.

* **Scalability**

  * Supports dynamic tools, MCP, web_search, code_interpreter, reasoning, and routing without becoming monolithic again.
  * Marker + DB persistence scales to long conversations while keeping the wire payload small.

---

## 4.2 Key components / modules

> **Agent:** Use the doc references as deeper guides; this section stays as the canonical, high‑level contract.

### 4.2.1 `core.config`  — see `docs/config_and_valves.md`

* `PipeValves` (admin-level settings).
* `UserValves` (per-user overrides).
* `RuntimeConfig` (merged effective settings).
* `merge_valves(pipe_valves, user_valves) -> RuntimeConfig`.

Semantics for each valve (e.g. `PERSIST_TOOL_RESULTS`, `PERSIST_REASONING_TOKENS`, `PROMPT_CACHE_KEY`) are spelled out in the config doc.

### 4.2.2 `core.logging`  — see `docs/config_and_valves.md` (logging section)

* Session-aware logging with:

  * `session_id` and `log_level` contextvars.
  * Buffered logs (per session) for optional emission as a citation (“Logs”).

### 4.2.3 `core.model_catalog`  — see `docs/routing_and_model_catalog.md`

* Canonical mapping for:

  * Base models → features.
  * Aliases → base + default params.
* Helpers: `base_model`, `features`, `supports`.

### 4.2.4 `core.markers`  — see `docs/markers_and_persistence.md`

* Implements v2 marker format:

  * ULIDs, payload encoding, wrapper `[payload]: #`, regex, splitting into segments.
* Must stay compatible with legacy markers.

---

### 4.2.5 `openai_api.types`

* `ResponsesRequest`:

  * The shape we send to OpenAI `/responses`.
  * Handles alias normalization and overlayed alias params.

* `ResponsesEvent`:

  * Typed/schematized representation of SSE `data:` frames.
  * Recognizes key `type` values but allows passthrough of unknown fields.

> See `docs/responses_engine.md` for which event types we rely on in the engine.

---

### 4.2.6 `openai_api.client`

* `OpenAIClient`:

  * Shared `aiohttp` session.
  * `stream_responses()` for SSE streaming.
  * `create_response()` for non-streaming calls (task models, etc.).

> Streaming format and error handling are described in `docs/responses_engine.md`.

---

### 4.2.7 `domain.types`

* Turn-level types:

  * `TurnContext`, `TurnState`, `TurnResult`, `ToolCall`, `ToolResult`, `Citation`.
* RuntimeEvents protocol that `openwebui.events` will implement.

> `docs/responses_engine.md` uses these types to describe the engine loop.

---

### 4.2.8 `domain.history` — see `docs/history_manager.md` + `docs/markers_and_persistence.md`

* `HistoryStore` (abstract).
* `HistoryManager`:

  * `build_input_from_messages(...)`:

    * Maps Open WebUI `messages[]` to Responses `input[]` using markers and DB store.
    * Extracts last `system` message as `instructions`.

  * `persist_items_for_message(...)`:

    * Saves items via `HistoryStore`.
    * Builds markers via `core.markers`.
    * Appends markers to assistant text.

---

### 4.2.9 `domain.tools` — see `docs/tools_and_extra_tools.md`

* `ToolDefinition`, `ToolRegistry`, `ToolExecutor`, `ToolPolicy`.
* Responsibility:

  * Merge:

    * Model‑defined tools,
    * Registry tools,
    * Filter `extra_tools`,
    * MCP and web_search tools,
  * Apply strict schema when enabled.
  * Deduplicate tools by identity.

---

### 4.2.10 `domain.web_search` — see `docs/web_search_and_citations.md`

* Builds `web_search` tools for models that support it.
* Adds appropriate `include[...]` fields (e.g. `"web_search_call.action.sources"`).

---

### 4.2.11 `domain.code_interpreter` — see `docs/responses_engine.md` (CI section, if present)

* Handles `code_interpreter_*` item types and their statuses.
* (Can be minimal until CI output is used.)

---

### 4.2.12 `domain.routing` — see `docs/routing_and_model_catalog.md`

* Implements GPT-5 auto-router behavior, mapping high-level requests to `gpt-5-chat-latest`, `gpt-5-mini`, or `gpt-5` with reasoning effort.

---

### 4.2.13 `domain.engine.ResponsesEngine` — see `docs/responses_engine.md`

* Core streaming logic:

  * Multiple tool-call loops.
  * Reasoning summary statuses.
  * Web search and tool statuses.
  * URL citations.
  * Usage aggregation.
  * Persistence of items and marker injection.

---

### 4.2.14 OpenWebUI adapters — see `docs/openwebui_integration.md`

* `openwebui.store.OpenWebUIHistoryStore`:

  * Implements `HistoryStore` using Open WebUI’s `Chats` model and `openai_responses_pipe` layout.

* `openwebui.events.OpenWebUIRuntimeEvents`:

  * Wraps `__event_emitter__` into the `RuntimeEvents` protocol.

* `openwebui.tools`:

  * Bridges Open WebUI function registry (`__tools__`) into `ToolRegistry` + `ToolExecutor`.

* `openwebui.bridge`:

  * Transforms Completions-style requests (body) into `ResponsesRequest` + separate tool lists.
  * Knows about `messages[]`, `body.tools`, `body.extra_tools`.

---

### 4.2.15 `pipe.Pipe` — see `docs/openwebui_integration.md`

* Exposes the actual Open WebUI pipe:

  * Nested `Valves` and `UserValves`.
  * `pipes()` returns model list.
  * `pipe()` wires:

    * Valve merging,
    * Logging context,
    * History store,
    * Bridge,
    * Engine,
    * Task/non-task routing,
    * Auto‑enabling native function calling when needed.

---

# 5. Implementation notes for the AI agent

* **Docs vs code**

  * This workpackage + the docs under `functions/pipes/openai_responses_manifold/docs/` are your **source of truth**.
  * If you change behavior, update:

    1. This workpackage (architecture/intent),
    2. The relevant doc(s),
    3. Then the code.

* **Coding style**

  * Use type hints and pydantic models where appropriate.
  * Keep layers clean:

    * No Open WebUI imports in `core` or `openai_api`.
    * `domain` is UI-agnostic.
    * `openwebui` is the only place that knows about `Chats`, `Models`, `__event_emitter__`, etc.

* **Testing**

  * `core` and `domain` tests should not need Open WebUI.
  * `openwebui` tests should mock out DB models and emitters.

* **Error handling**

  * Never let an exception crash `pipe()`:

    * Emit a `chat:completion` with an error description.
    * Optionally emit log citations.
  * Tool errors should produce tool outputs with error status, not kill the whole turn.

* **Performance**

  * Reuse `aiohttp.ClientSession`.
  * Parallelize tool calls where safe.
  * Respect `MAX_FUNCTION_CALL_LOOPS` and `MAX_TOOL_CALLS`.

* **Compatibility**

  * Marker regex, prefix, and DB layout must remain compatible with existing chats.
  * Filter-injected tools via `body.extra_tools` must remain fully supported.