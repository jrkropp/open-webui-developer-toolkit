> ### Agent instruction (read first)
>
> * This document is **authoritative**. If code and this document disagree, **update this document first**, then the code.
> * Keep the checklist up to date (`[ ]` → `[x]`), and add new items as you discover more work.
> * **Do not modify** `src_old/` or `test_old/` except to read them for reference. All new work must go under `src/` and `tests/`.
> * Prefer small, incremental commits aligned to checklist items. Optionally add commit ids next to completed bullets.

---

## Work Package Checklist

### Phase 0 – Skeleton & wiring

* [ ] Create new `src/openai_responses_manifold/` package with `core`, `openai_api`, `domain`, `openwebui`, `pipe.py`
* [ ] Create mirrored `tests/` structure for the new packages
* [ ] Ensure `Pipe` is importable from `openai_responses_manifold.pipe` and passes a trivial smoke test

### Phase 1 – Core & OpenAI client

* [ ] Implement `core.config` (PipeValves, UserValves, RuntimeConfig, merge helper)
* [ ] Implement `core.logging` (SessionLogger-style context + log buffer)
* [ ] Implement `core.model_catalog` (normalize, aliases, feature flags, supports)
* [ ] Implement `core.markers` (v2 marker format encode/decode/split)
* [ ] Implement `openai_api.types` (ResponsesRequest + ResponsesEvent union)
* [ ] Implement `openai_api.client` (stream + non-stream) with tests using faked HTTP

### Phase 2 – Domain (engine, history, tools, routing)

* [ ] Implement `domain.types` (TurnContext, TurnState, TurnResult, ToolCall, ToolResult, Citation, RuntimeEvents protocol)
* [ ] Implement `domain.history` (HistoryStore + HistoryManager using markers + DB layout compatible with old manifold)
* [ ] Implement `domain.tools` (ToolDefinition, ToolRegistry, ToolExecutor, ToolPolicy incl. `extra_tools` merge & dedupe)
* [ ] Implement `domain.web_search` (build & tune web_search tools)
* [ ] Implement `domain.code_interpreter` (handle code_interpreter events & outputs → status/citation)
* [ ] Implement `domain.routing` (gpt‑5‑auto router helper)
* [ ] Implement `domain.engine.ResponsesEngine` (streaming loop + tool loops + reasoning summary + usage merge)
* [ ] Add unit tests for history, tools, engine (no OpenWebUI imports)

### Phase 3 – OpenWebUI integration

* [ ] Implement `openwebui.store.OpenWebUIHistoryStore` using `Chats` and the `openai_responses_pipe` structure
* [ ] Implement `openwebui.events.OpenWebUIRuntimeEvents` (wrap `__event_emitter__`)
* [ ] Implement `openwebui.tools` (OpenWebUIToolRegistry + OpenWebUIToolExecutor)
* [ ] Implement `openwebui.bridge` (Completions → Responses mapping, including filter `extra_tools`)
* [ ] Implement `pipe.Pipe` wiring everything together, including **task** path
* [ ] Add integration tests for `Pipe.pipe()` with mocked OpenAI client, Chats, Models, and event emitter

### Phase 4 – Persistence, filters, UX & polish

* [ ] Implement marker-based persistence & replay end‑to‑end (tool calls, tool results, reasoning)
* [ ] Ensure compatibility with filter-injected tools via `body.extra_tools`
* [ ] Implement SessionLogger → log-as-citation behavior at the end of the turn
* [ ] Implement citation handling (url_citation annotations, Chats.upsert_message_to_chat_by_id_and_message_id)
* [ ] Implement non-streaming task path via Responses API for `__task__` models (titles, tags, etc.)
* [ ] Optionally re-introduce status UI tweaks (multi-line status line) via `__event_call__`
* [ ] Port any critical behavior from `src_old/` (usage merging, reasoning summary flags, PERSIST_REASONING_TOKENS) into the new layers
* [ ] Add README / developer docs summarizing architecture and flows
* [ ] Clearly mark `src_old/` and `test_old/` as legacy in docs

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
* Respect **Open WebUI’s messages[] and filter system** as the single source of conversation context.
* Recreate and refine **persistence using invisible markers** plus DB storage.
* Ensure **filter-injected tools** remain fully supported and deduplicated.

The result should:

* Have **high cohesion / low coupling** (each module has a clear role).
* Be **obvious to navigate**: a newcomer should understand the system by reading the file tree and a few key modules.

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
     * Deduplicate by `(type, name)` (last/first wins per policy).
     * Convert Open WebUI registry tools into Responses function tools.
     * Preserve support for web_search / MCP tools as separate types.

4. **Open WebUI completion → Responses mapping**

   * Legacy `ResponsesBody.from_completions()`:

     * Drops unsupported completions fields (`frequency_penalty`, `presence_penalty`, `n`, `stop`, `functions`, `function_call`, etc.).
     * Renames `max_tokens` → `max_output_tokens`.
     * Maps `reasoning_effort` → `reasoning.effort`.
     * Extracts last `system` message as `instructions`.
     * Uses `transform_messages_to_input(...)` to produce Responses `input[]`, with marker rehydration.
     * Leaves room for extra parameters (e.g., custom model settings).

5. **Streaming event behavior & statuses**

   * The old manifold:

     * Handles `response.output_text.delta` for incremental deltas.
     * Handles `response.reasoning_summary_text.done` to update a multi-line status (“Thinking…”, explanation).
     * Handles `response.output_text.annotation.added` of type `url_citation` to:

       * Emit `source` events with citations,
       * Record them in `emitted_citations`,
       * Store them with Chats.upsert_message_to_chat_by_id_and_message_id at the end.
     * Handles `response.output_item.added` / `done` to show tool status (“Running tool …”, “Let me skim those files…”).
     * On completion:

       * Persists structured items and injects markers,
       * Merges usage stats and emits `chat:completion`.

6. **Logging**

   * Legacy `SessionLogger`:

     * Uses contextvars (`session_id`, `log_level`).
     * Stores logs in a deque buffer keyed by session_id.
     * Emits logs as a “Logs” citation at the end of the turn if enabled.

7. **Settings & valves**

   * Model list, API base/keys, reasoning summary level, persistence knobs, web search knobs, prompt cache key, etc.
   * PERSIST_REASONING_TOKENS:

     * `disabled`, `response`, `conversation` controlling when to request & persist `reasoning.encrypted_content`.

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

---

# 4. Design (for this workpackage)

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

### 4.2.1 `core.config`

* `PipeValves` (admin-level settings) – include:

  * Connection & auth:

    * `BASE_URL`, `API_KEY`.
  * Models:

    * `MODEL_ID` (comma-separated list of manifold models).
  * Reasoning & summaries:

    * `REASONING_SUMMARY` (`auto|concise|detailed|disabled`).
    * `PERSIST_REASONING_TOKENS` (`disabled|response|conversation`).
  * Tools & tool behavior:

    * `PERSIST_TOOL_RESULTS: bool`
    * `PARALLEL_TOOL_CALLS: bool`
    * `ENABLE_STRICT_TOOL_CALLING: bool`
    * `MAX_TOOL_CALLS: Optional[int]`
    * `MAX_FUNCTION_CALL_LOOPS: int`
  * Web search:

    * `ENABLE_WEB_SEARCH_TOOL: bool`
    * `WEB_SEARCH_CONTEXT_SIZE: Literal["low","medium","high",None]`
    * `WEB_SEARCH_USER_LOCATION: Optional[str]` (JSON string)
  * Integrations:

    * `REMOTE_MCP_SERVERS_JSON: Optional[str]`
  * Truncation:

    * `TRUNCATION: Literal["auto", "disabled"]`
  * Privacy & caching:

    * `PROMPT_CACHE_KEY: Literal["id","email"]`
  * Logging:

    * `LOG_LEVEL: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`

* `UserValves` (per-user overrides):

  * `LOG_LEVEL: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL","INHERIT"]`

* `RuntimeConfig`:

  * The merged, effective configuration for a turn (values from pipe-level valves overridden by user valves that are not `"INHERIT"`).

* `merge_valves(pipe_valves, user_valves) -> RuntimeConfig`

### 4.2.2 `core.logging`

Reintroduce a cleaned-up version of `SessionLogger`:

* Contextvars:

  * `session_id: ContextVar[str | None]`
  * `log_level: ContextVar[int]`
* Log storage:

  * `logs: dict[session_id, deque[str]]` with a fixed max length (e.g., 2000).
* API:

  * `get_logger(name: str) -> logging.Logger`
  * `set_session(session_id: str | None, level: int) -> contextmanager`
  * `get_session_logs(session_id: str | None) -> list[str]`
  * `clear_session_logs(session_id: str | None) -> None`

The engine will:

* Initialize session_id/level at the start of `pipe()`.
* Optionally emit logs as a `citation` or `source` event at the end, depending on valves.

### 4.2.3 `core.model_catalog`

Model alias & feature registry (like `ModelFamily`):

* Functions:

  * `normalize(model_id: str) -> str`
  * `base_model(model_id: str) -> str`
  * `alias_defaults(model_id: str) -> dict`
  * `features(model_id: str) -> set[str]`
  * `supports(feature: str, model_id: str) -> bool`

Use features such as:

* `"function_calling"`, `"reasoning"`, `"reasoning_summary"`,
* `"web_search_tool"`, `"code_interpreter_tool"`, `"deep_research"`, `"verbosity"`.

### 4.2.4 `core.markers`

Implement v2 marker format exactly:

* Constants:

  * `MARKER_PREFIX = "openai_responses:v2:"`
  * `ULID_LENGTH = 16`
  * Crockford alphabet for ULIDs.

* Helpers:

  * `generate_ulid() -> str` – 16-char Crockford ID.
  * `build_marker_payload(item_type: str, ulid: str, metadata: dict[str,str] | None) -> str`:

    * `openai_responses:v2:{item_type}:{ulid}[?k=v&...]`
  * `wrap_marker(payload: str) -> str`:

    * `"\n[{payload}]: #\n"` (newline-delimited).
  * `extract_markers(text: str) -> list[ParsedMarker]`:

    * Use regex to find markers and parse into:

      * `{"item_type": ..., "ulid": ..., "metadata": {...}}`
  * `split_text_by_markers(text: str) -> list[Segment]`:

    * `{"type": "text", "text": "..."}` or
    * `{"type": "marker", "marker": ParsedMarker}`.

These must be compatible with existing persisted chats if they are ever used again.

---

### 4.2.5 `openai_api.types`

* `class ResponsesRequest(BaseModel)`:

  * Key fields:

    * `model: str`
    * `input: str | list[dict[str, Any]]`
    * `instructions: str | None`
    * `stream: bool = True`
    * `store: bool | None`
    * `max_output_tokens: int | None`
    * `max_tool_calls: int | None`
    * `parallel_tool_calls: bool | None`
    * `reasoning: dict | None`
    * `text: dict | None` (format/verbosity)
    * `tools: list[dict] | None`
    * `include: list[str] | None`
    * `metadata: dict[str, str] | None`
    * `truncation: Literal["auto","disabled"] | None`
    * `user: str | None` (cache key)
    * `conversation: str | None`
    * `previous_response_id: str | None`
    * internal: `model_router_result: dict | None` (not sent to API)

  * Validator (`model_validator("after")`):

    * Normalize `model` → base_model.
    * Apply alias defaults overlays (e.g., reasoning.effort for “thinking” aliases).
    * Possibly unify `max_tokens` → `max_output_tokens` if we ever feed it through this model directly.

* `class ResponsesEvent(BaseModel)`:

  * Discriminated by `type`:

    * `response.output_text.delta` (`delta: str`)
    * `response.output_text.done`
    * `response.reasoning_summary_text.done`
    * `response.output_text.annotation.added` (for url_citation annotations)
    * `response.output_item.added`
    * `response.output_item.done`
    * `response.completed` (contains `response` with `output[]`, `usage`)
    * `response.incomplete` / `response.failed` / generic error

  * Include typed subfields where helpful but allow passthrough `dict` for unknown types.

---

### 4.2.6 `openai_api.client`

* `class OpenAIClient`:

  * Manages a shared `aiohttp.ClientSession` with:

    * Connection pooling,
    * Reasonable timeouts (similar to old code: connect=30, sock_read=3600, etc.).

  * `async def stream_responses(self, request: ResponsesRequest, *, base_url: str, api_key: str) -> AsyncIterator[ResponsesEvent]`:

    * POST to `{base_url.rstrip('/')}/responses`.
    * Headers:

      * `Authorization: Bearer {api_key}`
      * `Content-Type: application/json`
      * `Accept: text/event-stream`
    * Read `resp.content.iter_chunked(4096)`, accumulate in a buffer, parse lines starting with `b"data:"`.
    * For each JSON event:

      * Parse with `json.loads`.
      * Convert to `ResponsesEvent` via a helper.
      * Yield.

  * `async def create_response(self, request: ResponsesRequest, *, base_url: str, api_key: str) -> dict`:

    * POST same endpoint with `stream=False`.
    * Return parsed JSON.

---

### 4.2.7 `domain.types`

* `TurnContext`:

  * Holds:

    * `runtime_config: RuntimeConfig`
    * `metadata: dict[str, Any]`:

      * `session_id`, `chat_id`, `message_id`, `user_id`, `owui_model_id` (full model id, e.g., `"openai_responses.gpt-4o"`), etc.
    * `model_id: str` – canonical OpenAI base model.
    * `features: set[str]` – from `core.model_catalog.features(model_id)`.

* `TurnState`:

  * `assistant_visible_text: str`
  * `assistant_internal_text: str` (visible text + markers)
  * `usage: dict[str, Any] | None`
  * `citations: list[Citation]`
  * `tool_calls_executed: int`
  * `error_message: str | None`
  * `structured_items: list[dict]` (output items from Responses)

* `ToolCall`:

  * `call_id: str`
  * `name: str`
  * `arguments_json: str`

* `ToolResult`:

  * `call_id: str`
  * `output: str` (stringified)
  * `status: Literal["ok", "error", "timeout"]`
  * `error_message: str | None`

* `Citation`:

  * `source_name: str`
  * `url: str | None`
  * `document: list[str]`
  * `metadata: dict[str, Any]`

* `TurnResult`:

  * `text: str`
  * `usage: dict[str, Any] | None`
  * `citations: list[Citation]`
  * `error: str | None`

* `RuntimeEvents` Protocol:

  * `async def status(self, description: str, *, done: bool = False) -> None`
  * `async def delta(self, content: str) -> None`
  * `async def replace(self, content: str) -> None`
  * `async def citation(self, data: dict[str, Any]) -> None`
  * `async def source(self, data: dict[str, Any]) -> None`  (for url_citation style)
  * `async def chat_completion(self, data: dict[str, Any]) -> None`
  * `async def notification(self, content: str, *, level: Literal["info","success","warning","error"] = "info") -> None`

---

### 4.2.8 `domain.history`

* `HistoryStore` protocol:

  * `def save_items(self, chat_key: dict, message_id: str, items: list[dict], model_id: str) -> list[str]`
  * `def load_items(self, chat_key: dict, item_ids: list[str], model_id: str | None = None) -> dict[str, dict]`

* `HistoryManager`:

  * `build_input_from_messages(messages: list[dict], chat_key: dict, model_id: str | None, openwebui_model_id: str | None) -> tuple[list[dict], str | None]`

    * Steps:

      1. Collect all markers from assistant messages using `core.markers.extract_markers`.
      2. Use `HistoryStore.load_items(chat_key, ulids, openwebui_model_id)` to get payloads.
      3. For each message:

         * `system` messages:

           * Track last system content as `instructions`.
         * `user` messages:

           * Convert to Responses-style `{"role":"user","content":[...]}` blocks:

             * `text` → `input_text`,
             * `image_url` → `input_image`,
             * `input_file` → `input_file`,
             * leave unknown types as-is.
         * `assistant` messages:

           * Use `split_text_by_markers`:

             * For `marker` segments: append the corresponding persisted item payload into `input`.
             * For `text` segments: if non-empty, push as:

               * `{"role": "assistant", "content": [{"type": "output_text","text": "..."}]}`.

    * Returns:

      * `input_items` list,
      * `instructions` (last system message or None).

  * `persist_items_for_message(chat_key: dict, message_id: str, items: list[dict], model_id: str, openwebui_model_id: str, current_assistant_text: str) -> str`:

    * If `items` empty → return unchanged `current_assistant_text`.
    * Use `HistoryStore.save_items` to persist items and get ULIDs.
    * For each ULID:

      * Determine `item_type` from payload (`payload["type"]`, default `"unknown"`).
      * Build marker payload via `core.markers.build_marker_payload(item_type, ulid, metadata={"model": openwebui_model_id})`.
      * Wrap via `core.markers.wrap_marker`.
    * Append all markers to `current_assistant_text` and return new text.

---

### 4.2.9 `domain.tools`

* `ToolDefinition`:

  * `name: str`
  * `description: str`
  * `parameters: dict`
  * `strict: bool`
  * `source: Literal["registry","filter","body","mcp","builtin"]`

* `ToolRegistry` protocol:

  * `def get(self, name: str) -> ToolDefinition | None`
  * `def iter_definitions(self) -> Iterable[ToolDefinition]`

* `ToolExecutor` protocol:

  * `async def execute(self, calls: list[ToolCall]) -> list[ToolResult]`

* `ToolPolicy`:

  * `@staticmethod def build_responses_tools(model_id: str, features: set[str], cfg: RuntimeConfig, registry: ToolRegistry, body_tools: list[dict] | None, extra_tools: list[dict] | None, mcp_tools: list[dict] | None, web_search_tools: list[dict] | None) -> list[dict]`:

    * Steps:

      * If `not supports("function_calling", model_id)`:

        * Only include non-function tools (web_search, MCP, etc.).
      * Convert Open WebUI registry entries into `{"type": "function", ...}`.
      * Merge:

        1. Tools from model config (`body_tools`).
        2. Registry-derived tools.
        3. `extra_tools` injected by filters.
        4. `mcp_tools` from cfg.REMOTE_MCP_SERVERS_JSON.
        5. `web_search_tools`.
      * If `cfg.ENABLE_STRICT_TOOL_CALLING`:

        * Apply strict JSON Schema transformation (`additionalProperties=False`, `required` = all properties, optional → nullable).
      * Deduplicate by:

        * `("function", name)` for function tools,
        * `(type, None)` for others (web_search, mcp, etc.).
      * Later entries override earlier ones (or vice versa; choose one approach and document it — recommendation: “last wins”).

---

### 4.2.10 `domain.web_search`

* `build_web_search_tools(model_id: str, features: set[str], cfg: RuntimeConfig) -> list[dict]`:

  * Only returns non-empty list if:

    * `supports("web_search_tool", model_id)` is `True`.
    * `cfg.ENABLE_WEB_SEARCH_TOOL` or a feature flag says we want it.

  * Build tool dict:

    ```python
    tool = {
      "type": "web_search",
      "search_context_size": cfg.WEB_SEARCH_CONTEXT_SIZE,
    }
    ```

  * If `cfg.WEB_SEARCH_USER_LOCATION` is present:

    * Try `json.loads`, attach as `user_location` (on parse error, log warning and ignore).

* Additional logic (if needed):

  * When web_search tools exist:

    * Add `"web_search_call.action.sources"` to `request.include` so sources are returned.
    * Optionally adjust `request.parallel_tool_calls` to reduce weird interactions (if observed).

---

### 4.2.11 `domain.code_interpreter`

* Behaviors:

  * Listen for `response.output_item.added` and `response.output_item.done` events of type `code_interpreter_call` (or similar when supported).
  * Maintain in `TurnState`:

    * Current code snippets,
    * Logs,
    * Output files.
  * On `done`:

    * Generate:

      * Status message (e.g., “Finished running code…”),
      * Optional `Citation` summarizing what happened (e.g., "Summarized via code interpreter").

    * Optionally instruct `RuntimeEvents.files` to attach generated files to the UI.

  > Note: If Responses API’s CI output format changes, keep this module as the only place you update that logic.

---

### 4.2.12 `domain.routing`

* `async def route_auto_model(client, request: ResponsesRequest, ctx: TurnContext, tools: list[dict], events: RuntimeEvents) -> ResponsesRequest`:

  * Used when `ctx.metadata["owui_model_id"]` ends in `.gpt-5-auto` or `.gpt-5-auto-dev`.
  * Constructs a routing request similar to your existing `_route_gpt5_auto`:

    * Router model (e.g., `gpt-5-mini` with minimal reasoning).
    * `instructions` describing available models and how to choose one.
    * `input = request.input`.
    * Response format: JSON schema with `model`, `reasoning_effort`, `explanation`.
  * Parses router response and:

    * Sets `request.model`.
    * Sets `request.reasoning["effort"]` if supported.
    * Attaches `model_router_result` to `request`.
  * Emits a `status` event explaining the routing decision.

---

### 4.2.13 `domain.engine.ResponsesEngine`

Core streaming engine.

* Constructor:

  ```python
  class ResponsesEngine:
      def __init__(self, client: OpenAIClient, history_manager: HistoryManager, logger: logging.Logger | None = None):
          ...
  ```

* `async def run_streaming_turn(self, request: ResponsesRequest, ctx: TurnContext, events: RuntimeEvents, history_key: dict, tool_registry: ToolRegistry, tool_executor: ToolExecutor) -> TurnResult`:

  1. Initialize `TurnState`.
  2. Pre-emit “thinking” statuses if model supports reasoning (optional, similar to old code).
  3. For up to `cfg.MAX_FUNCTION_CALL_LOOPS` loops:

     * Call `client.stream_responses(request, base_url, api_key)`.

     * For each `ResponsesEvent`:

       * `response.output_text.delta`:

         * Append to `assistant_visible_text` and `assistant_internal_text`.
         * `events.delta(assistant_visible_text)` or `events.replace(assistant_visible_text)` as desired.
       * `response.reasoning_summary_text.done`:

         * Extract summary, update multi-line status (“Thinking…\n<summary>”).
       * `response.output_text.annotation.added` with `url_citation`:

         * Build a `source` event:

           * `source.name` = host,
           * `source.url` = raw URL (strip tracking parameters as needed).
         * Track citations in `TurnState.citations`.
       * `response.output_item.added`:

         * If type == `"message"` and status `in_progress`:

           * Emit status like “Responding to the user…”.
       * `response.output_item.done`:

         * For type `"function_call"`, `"web_search_call"`, `"file_search_call"`, `"code_interpreter_call"`, etc:

           * Build descriptive status messages (e.g., `Running the {name} tool…` with arguments).
           * Decide whether to persist item (respect `PERSIST_TOOL_RESULTS`, `PERSIST_REASONING_TOKENS`).
           * Add structured items to `TurnState.structured_items`.
       * `response.completed`:

         * Capture final `response` payload (with `output` and `usage`) and break out of event loop.

     * If no `response.completed` was seen, treat as error.

     * Merge usage stats (using `merge_usage_stats` logic) into `TurnState.usage`.

     * Identify function calls:

       ```python
       tool_calls = [
         ToolCall(call_id=i["call_id"], name=i["name"], arguments_json=i["arguments"])
         for i in final_response["output"]
         if i["type"] == "function_call"
       ]
       ```

     * If no tool calls:

       * Break out of outer loop.

     * Else:

       * If `tool_calls_executed + len(tool_calls) > cfg.MAX_TOOL_CALLS`:

         * Emit warning status,
         * Break.
       * Execute via `tool_executor.execute(tool_calls)`.
       * Convert results into `function_call_output` items.
       * Persist results via `HistoryManager.persist_items_for_message`, injecting markers into `assistant_internal_text`.
       * Append these new output items to `request.input`.
  4. After loops:

     * Persist any non-function structured items that should be stored (e.g., reasoning, etc.).
     * Use `HistoryManager.persist_items_for_message` to inject markers into final assistant text.
     * Emit final `chat_completion` with:

       * `done=True`,
       * `content` = `assistant_visible_text`,
       * `usage`, etc.
     * Optionally emit a log citation using buffered logs when enabled.
  5. Return `TurnResult`.

* `async def run_task(self, request: ResponsesRequest, ctx: TurnContext) -> str`:

  * `request.stream = False`.
  * Call `client.create_response(...)`.
  * Extract plain text from `output` items of type `message` with `output_text`.
  * Return concatenated text.

---

### 4.2.14 OpenWebUI adapters

#### `openwebui.store.OpenWebUIHistoryStore`

* Uses `Chats` to persist items under `chat.chat["openai_responses_pipe"]`.
* Implements `HistoryStore`:

  * `save_items(chat_key: dict, message_id: str, items: list[dict], model_id: str) -> list[str]`:

    * `chat_id = chat_key["chat_id"]`.

    * Load chat via `Chats.get_chat_by_id(chat_id)`.

    * Initialize `chat.chat["openai_responses_pipe"]` if missing, as:

      ```python
      {
        "__v": 3,
        "items": {},
        "messages_index": {},
      }
      ```

    * For each item:

      * Generate ULID via `core.markers.generate_ulid()`.
      * Store in `pipe_root["items"][ulid]`:

        * `{"model": model_id, "created_at": now, "payload": item, "message_id": message_id}`.
      * Append ULID to `pipe_root["messages_index"][message_id]["item_ids"]`.

    * `Chats.update_chat_by_id(chat_id, chat.chat)`.

    * Return list of ULIDs.

  * `load_items(chat_key: dict, item_ids: list[str], model_id: str | None = None) -> dict[str, dict]`:

    * Load chat by `chat_id`.
    * Look up `items` under `chat.chat["openai_responses_pipe"]["items"]`.
    * For each `item_id`:

      * If found and (`model_id` is None or item["model"] == model_id):

        * Include `item["payload"]` in the returned dict.

#### `openwebui.events.OpenWebUIRuntimeEvents`

* Wraps `__event_emitter__`:

  * `status` → `{"type": "status", "data": {"description": ..., "done": ...}}`
  * `delta` or `replace` → `"chat:message"` events with `{"content": text}` (delta vs full replacement; choose one consistent approach).
  * `citation` → `{"type": "citation", "data": {...}}`
  * `source` → `{"type": "source", "data": {...}}` (for url-based citations).
  * `chat_completion` → `{"type": "chat:completion", "data": {...}}`
  * `notification` → `{"type": "notification", "data": {"type": level, "content": content}}`

#### `openwebui.tools`

* `OpenWebUIToolRegistry(ToolRegistry)`:

  * Constructed from `__tools__` (may be dict or list).
  * For each tool:

    * Expose `ToolDefinition` with:

      * `name`: `spec["name"]`,
      * `description`: `spec["description"]`,
      * `parameters`: `spec["parameters"]`,
      * `strict`: derived from valve or spec.
  * `iter_definitions()` yields all.

* `OpenWebUIToolExecutor(ToolExecutor)`:

  * Holds same registry, but focusing on `callable` functions.
  * `execute(calls)`:

    * For each `ToolCall`:

      * Parse `call.arguments_json` with `json.loads`.
      * Look up callable by name.
      * If not found: return ToolResult with `status="error"`, `output="Tool not found"`.
      * If coroutine: `await fn(**args)`, else `run_in_executor`.
      * Catch exceptions; set `status="error"`, `error_message=str(e)` and include in output.

#### `openwebui.bridge`

* `build_turn_context(pipe_valves, user_valves, __user__, __metadata__) -> TurnContext`:

  * Merge valves → RuntimeConfig.
  * Determine `user_identifier` from `PROMPT_CACHE_KEY`:

    * `__user__["id"]` or `__user__["email"]`.
  * Determine `openwebui_model_id = __metadata__.get("model", {}).get("id", "")`.
  * Compute `model_id` via `core.model_catalog.base_model(openwebui_model_id or body["model"])`.
  * Build metadata dict with:

    * `session_id`, `chat_id`, `message_id`, `user_id`, `owui_model_id`, etc.
  * Compute features via `core.model_catalog.features(model_id)`.

* `map_completions_to_responses(body: dict, ctx: TurnContext, history_manager: HistoryManager, history_key: dict) -> tuple[ResponsesRequest, list[dict], list[dict]]`:

  * Extract:

    * `messages = body["messages"]`,
    * `base_tools = body.get("tools") or []`,
    * `extra_tools = body.get("extra_tools") or []`.
  * Call `history_manager.build_input_from_messages(messages, history_key, model_id=ctx.model_id, openwebui_model_id=ctx.metadata["owui_model_id"])` to get `input_items` and `instructions`.
  * Drop unsupported completions fields (like the old code).
  * Transform:

    * `max_tokens` → `max_output_tokens`,
    * `reasoning_effort` → `reasoning["effort"]`.
  * Build `ResponsesRequest`:

    * `model = ctx.model_id`,
    * `input = input_items`,
    * `instructions` as derived (last system message),
    * `stream = body.get("stream", True)`,
    * `truncation = cfg.TRUNCATION`,
    * `user = user_identifier`,
    * `max_output_tokens`, `reasoning`, etc.
  * Return `request`, `base_tools`, `extra_tools`.

---

### 4.2.15 `pipe.Pipe`

* `class Pipe` with nested valves:

  ```python
  class Pipe:
      class Valves(PipeValves):
          ...
      class UserValves(UserValves):
          ...
  ```

* `__init__`:

  * Set `self.type = "manifold"`, `self.id = "openai_responses"`.
  * Initialize:

    * `self.valves = Pipe.Valves()`
    * `self.logger = core.logging.get_logger(__name__)`
    * `self.client = OpenAIClient()`
    * `self.history_store = OpenWebUIHistoryStore()`
    * `self.history_manager = HistoryManager(self.history_store)`
    * `self.engine = ResponsesEngine(self.client, self.history_manager, logger=self.logger)`

* `async def pipes(self)`:

  * Split `self.valves.MODEL_ID` on comma.
  * Return `[{"id": model_id.strip(), "name": f"OpenAI Responses: {model_id.strip()}"} ...]`.

* `async def pipe(self, body, __user__, __request__, __event_emitter__, __event_call__, __metadata__, __tools__, __task__=None, __task_body__=None)`:

  * Merge valves: `cfg = merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))`.

  * Setup logging session via `core.logging.set_session(session_id, log_level)`.

  * Wrap `RuntimeEvents` via `OpenWebUIRuntimeEvents(__event_emitter__)`.

  * Build `TurnContext` via `openwebui.bridge.build_turn_context`.

  * Construct `history_key = {"chat_id": __metadata__.get("chat_id"), "pipe_id": self.id}`.

  * Handle **task models**:

    * If `__task__` is not None:

      * Build `ResponsesRequest` via `map_completions_to_responses` but with tools stripped and `stream=False`.
      * Call `engine.run_task`.
      * Return plain string.

  * Normal chat:

    1. Await `__tools__` if coroutine.
    2. Use `OpenWebUIToolRegistry+Executor`.
    3. Map completions to Responses: `request, base_tools, extra_tools = bridge.map_completions_to_responses(...)`.
    4. Build `mcp_tools` from cfg.REMOTE_MCP_SERVERS_JSON.
    5. Build `web_search_tools` via `domain.web_search.build_web_search_tools`.
    6. Build final `tools` via `ToolPolicy.build_responses_tools`.
    7. Attach `request.tools = tools` if any.
    8. Handle reasoning summary + PERSIST_REASONING_TOKENS:

       * If `supports("reasoning_summary", request.model)` and cfg.REASONING_SUMMARY != "disabled":

         * Set `request.reasoning["summary"] = cfg.REASONING_SUMMARY`.
       * If `supports("reasoning", request.model)` and cfg.PERSIST_REASONING_TOKENS != "disabled"`:

         * Ensure `"reasoning.encrypted_content"` is in `request.include`.
    9. Add web_search sources include if necessary.
    10. Auto-enable native function calling on Models entry if:

        * Tools present and
        * `Model.params["function_calling"] != "native"` and
        * Model supports function calling.
    11. Optional: apply auto-router via `domain.routing.route_auto_model`.
    12. Force stream for now (like old manifold; non-stream path can re-use streaming with a wrapped emitter).
    13. Call `engine.run_streaming_turn(...)`.
    14. Attach stored `citations` to the chat message using `Chats.upsert_message_to_chat_by_id_and_message_id`.
    15. Emit logs as citation if cfg.LOG_LEVEL or user valves indicate.
    16. Return final assistant text.

  * Optionally, inject a one-time CSS patch using `__event_call__` to un-clamp status descriptions (as your old manifold did).

---

# 5. Implementation notes for the AI agent

* **Coding style**

  * Use Python 3.10+ type hints.
  * Use `pydantic` for config and request/response models.
  * Use dataclasses or simple classes for pure domain types.

* **Tests**

  * Domain layer and core layer should be testable without importing Open WebUI.
  * OpenWebUI-specific tests should mock Chats/Models/event emitter as needed.

* **Error handling**

  * Never crash the pipe; instead:

    * Emit a `chat:completion` with `error` and `done=True`,
    * Optionally emit log citations.
  * For tool failures, surface errors in tool outputs instead of failing the whole turn.

* **Performance**

  * Reuse a single `aiohttp.ClientSession`.
  * Use `asyncio.gather` when executing tools in parallel; consider timeouts.
  * Respect `MAX_TOOL_CALL_LOOPS` and `MAX_TOOL_CALLS`.

* **Compatibility**

  * Marker format and openai_responses_pipe layout must remain compatible with existing data.
  * Filter-injected tools via `body.extra_tools` must keep working exactly as described.

---