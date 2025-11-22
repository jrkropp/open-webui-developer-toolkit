# Responses Engine & Streaming Loop

`functions/pipes/openai_responses_manifold/docs/responses_engine.md`

> **Module:** `src/openai_responses_manifold/domain/engine.py`
> **Primary class:** `ResponsesEngine`
> **Scope:** Domain‑layer orchestration for the OpenAI **Responses API**:
>
> * Streaming loop over SSE events
> * Tool‑call orchestration (multi‑loop)
> * Usage aggregation
> * Reasoning summary & “thinking” statuses
> * URL citations
> * Marker‑based persistence via `HistoryManager`

This module is **UI‑agnostic**. It knows nothing about Open WebUI’s `Chats`, `Models`, or event emitters. It only:

* Talks to the **OpenAI client** (`openai_api.client.OpenAIClient`),
* Uses the **HistoryManager** (`domain.history`) + `HistoryStore`,
* Operates on **domain types** (`domain.types`: `TurnContext`, `TurnState`, `TurnResult`, `RuntimeEvents`, `ToolCall`, `ToolResult`, `Citation`),
* Delegates tool execution to a **ToolExecutor** (`domain.tools`).

All Open WebUI‑specific wiring (Chats, event emitter, CSS tweaks, etc.) lives in the `openwebui` layer and `pipe.Pipe`, not here.

---

## 1. Responsibilities & boundaries

`ResponsesEngine` turns a prepared **Responses API request** into:

* A stream of **RuntimeEvents**:

  * `status`, `delta`/`replace`, `source`, `citation`, `chat_completion`, `notification`.
* A final **TurnResult** with:

  * The final assistant **message text** (including invisible markers),
  * Aggregated usage,
  * Collected citations,
  * Optional error information.

It is responsible for:

1. **Streaming** SSE events from the Responses API.
2. **Maintaining TurnState** as events arrive:

   * Visible text buffer,
   * Structured items (tool outputs, reasoning, etc.),
   * Citations,
   * Usage counters.
3. **Tool loops**:

   * Detect `function_call` items,
   * Execute tools via `ToolExecutor`,
   * Convert tool results into output items,
   * Persist tool outputs via `HistoryManager`,
   * Append outputs to `request.input` and repeat.
4. **Reasoning & web search UX**:

   * “Thinking…” statuses,
   * Reasoning summary status,
   * Web search statuses (“Searching”, “Reading through {{count}} sites”).
5. **URL citations**:

   * `url_citation` annotations → `source` events,
   * Returning citations in `TurnResult` so the OpenWebUI layer can persist them on messages.
6. **Persistence integration**:

   * Using `HistoryManager.persist_items_for_message` to store structured items and inject **invisible markers** into the assistant text.

It does **not**:

* Build `ResponsesRequest` from Open WebUI `messages[]` (that’s `openwebui.bridge` + `domain.history`),
* Decide which tools exist (that’s `domain.tools.ToolPolicy` + `openwebui.tools`),
* Talk to `Chats` or `Models` directly (that’s `openwebui.store` + `pipe.Pipe`).

For more context, see:

* `openwebui_integration.md` for adapter wiring,
* `history_manager.md` + `markers_and_persistence.md` for how markers & items are persisted,
* `tools_and_extra_tools.md` for tool policy,
* `web_search_and_citations.md` for web search specifics.

---

## 2. Collaborators & domain types

### 2.1 OpenAI client

From `openai_responses_manifold/openai_api/client.py`:

```python
class OpenAIClient:
    async def stream_responses(
        self,
        request: ResponsesRequest,
        *,
        base_url: str,
        api_key: str,
    ) -> AsyncIterator[ResponsesEvent]:
        ...

    async def create_response(
        self,
        request: ResponsesRequest,
        *,
        base_url: str,
        api_key: str,
    ) -> dict:
        ...
```

* `ResponsesRequest` / `ResponsesEvent` live in `openai_api.types`.
* The client handles HTTP + SSE parsing and yields typed `ResponsesEvent` objects.

### 2.2 History manager

From `openai_responses_manifold/domain/history.py`:

```python
class HistoryManager:
    def __init__(self, store: HistoryStore): ...

    def persist_items_for_message(
        self,
        history_key: dict[str, Any],
        message_id: str,
        items: list[dict],
        model_id: str,
        openwebui_model_id: str,
        current_assistant_text: str,
    ) -> str:
        ...
```

* `history_key` is opaque to the engine (e.g. `{"chat_id": ..., "pipe_id": "openai_responses"}`).
* `persist_items_for_message`:

  * Persists items via `HistoryStore`,
  * Builds markers via `core.markers`,
  * Appends the markers to `current_assistant_text` and returns the updated string.

The engine never touches `Chats` directly; Chats are behind `HistoryStore` and the OpenWebUI adapter.

### 2.3 Core domain types

From `openai_responses_manifold/domain/types.py`:

* **`TurnContext`**:

  * `runtime_config: RuntimeConfig` (merged valves),
  * `model_id: str` (canonical OpenAI base model),
  * `features: set[str]` (capability flags from `core.model_catalog`),
  * `metadata: dict[str, Any]` (e.g. `chat_id`, `message_id`, `session_id`, `owui_model_id`, `user_id`).

* **`TurnState`** (engine‑internal, per turn):

  ```python
  @dataclass
  class TurnState:
      assistant_visible_text: str
      assistant_internal_text: str     # visible text + markers
      usage: dict | None
      citations: list[Citation]
      structured_items: list[dict]
      tool_calls_executed: int
      error_message: str | None
  ```

* **`ToolCall` & `ToolResult`**:

  ```python
  @dataclass
  class ToolCall:
      call_id: str
      name: str
      arguments_json: str

  @dataclass
  class ToolResult:
      call_id: str
      output: str
      status: Literal["ok", "error", "timeout"]
      error_message: str | None = None
  ```

* **`Citation`**:

  ```python
  @dataclass
  class Citation:
      source_name: str
      url: str | None
      document: list[str]
      metadata: dict[str, Any]
  ```

* **`TurnResult`** (returned from `run_streaming_turn`):

  ```python
  @dataclass
  class TurnResult:
      text: str                  # final assistant text, including markers
      usage: dict | None
      citations: list[Citation]
      error: str | None
  ```

  > **Important:** `TurnResult.text` is the exact string that should be stored as the assistant message body in `Chats`. It includes invisible markers appended by `HistoryManager` so that future turns can reconstruct history. When rendered as Markdown, the markers do **not** show up to users.

* **`RuntimeEvents`** protocol:

  ```python
  class RuntimeEvents(Protocol):
      async def status(self, description: str, *, done: bool = False, **extra): ...
      async def delta(self, content: str): ...
      async def replace(self, content: str): ...
      async def citation(self, data: dict[str, Any]): ...
      async def source(self, data: dict[str, Any]): ...
      async def chat_completion(self, data: dict[str, Any]): ...
      async def notification(
          self,
          content: str,
          *,
          level: Literal["info", "success", "warning", "error"] = "info",
      ): ...
  ```

### 2.4 Tools

The engine does **not** care where tools come from; it just consumes:

```python
class ToolRegistry(Protocol):
    def get(self, name: str) -> ToolDefinition | None: ...
    def iter_definitions(self) -> Iterable[ToolDefinition]: ...

class ToolExecutor(Protocol):
    async def execute(self, calls: list[ToolCall]) -> list[ToolResult]: ...
```

The OpenWebUI layer provides `OpenWebUIToolExecutor`, which runs the Python callables.

---

## 3. Public API & invariants

```python
class ResponsesEngine:
    def __init__(
        self,
        client: OpenAIClient,
        history_manager: HistoryManager,
        logger: logging.Logger | None = None,
    ): ...

    async def run_streaming_turn(
        self,
        request: ResponsesRequest,
        ctx: TurnContext,
        events: RuntimeEvents,
        history_key: dict[str, Any],
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
    ) -> TurnResult:
        ...

    async def run_task(
        self,
        request: ResponsesRequest,
        ctx: TurnContext,
    ) -> str:
        ...
```

### 3.1 Inputs to `run_streaming_turn`

* `request: ResponsesRequest` — fully prepared:

  * `model` is already a **base** OpenAI id (aliases resolved by `core.model_catalog`),
  * `input` built by `HistoryManager.build_input_from_messages(...)`,
  * `tools` from `ToolPolicy.build_responses_tools(...)`,
  * `reasoning`, `include`, etc. already set by the adapter.

* `ctx: TurnContext`:

  * `ctx.runtime_config` → effective valves (`MAX_TOOL_CALL_LOOPS`, `PERSIST_TOOL_RESULTS`, `PERSIST_REASONING_TOKENS`, web search knobs, etc.),
  * `ctx.metadata` has `chat_id`, `message_id`, `session_id`, `owui_model_id`.

* `events: RuntimeEvents` — abstraction over Open WebUI’s event emitter.

* `history_key: dict` — opaque key passed to `HistoryManager` for persistence (e.g. `{"chat_id": ..., "pipe_id": "openai_responses"}`).

* `tool_registry` — currently not needed in the core loop, but available for richer tool UX if ever needed.

* `tool_executor` — used to actually execute tool calls.

### 3.2 Invariants

`run_streaming_turn` **must**:

* Always return a `TurnResult` (never let exceptions bubble to the pipe in normal cases).
* Keep streaming robust: a malformed event or annotation should not crash the turn.
* Emit a **final** `chat_completion` event with `done=True` exactly once per turn (the OpenWebUI adapter wraps this to Open WebUI semantics).
* Ensure that `TurnResult.text` is safe to persist and re-use:

  * It includes invisible markers (if any),
  * It’s the full message content to store in `Chats` for this turn.

---

## 4. Streaming turn algorithm

### 4.1 Setup & TurnState

At the beginning of `run_streaming_turn`:

1. Extract config:

   ```python
   cfg = ctx.runtime_config
   base_url = cfg.BASE_URL
   api_key = cfg.API_KEY
   ```

2. Initialize state:

   ```python
   state = TurnState(
       assistant_visible_text="",
       assistant_internal_text="",   # will later get markers appended
       usage=None,
       citations=[],
       structured_items=[],
       tool_calls_executed=0,
       error_message=None,
   )
   ```

3. Optionally schedule UX‑friendly “thinking” statuses (see §4.5) if the model supports reasoning and `cfg.REASONING_SUMMARY` is not `"disabled"`.

4. If `request.model_router_result` is present (set by `domain.routing`):

   * Emit a status summarizing the routing decision (model + reasoning effort + explanation),
   * Then clear `request.model_router_result` so it is not sent to OpenAI.

### 4.2 Outer tool‑call loop

The engine supports multiple tool‑call rounds per turn:

```python
for loop_idx in range(cfg.MAX_FUNCTION_CALL_LOOPS):
    final_response = await _stream_single_response(
        request=request,
        state=state,
        ctx=ctx,
        events=events,
        base_url=base_url,
        api_key=api_key,
    )
    if final_response is None:
        # treat as error; break outer loop
        break

    _merge_usage(state, final_response)

    tool_calls = _extract_tool_calls(final_response, cfg)
    if not tool_calls:
        break  # no more tools requested; done

    if cfg.MAX_TOOL_CALLS is not None:
        if state.tool_calls_executed + len(tool_calls) > cfg.MAX_TOOL_CALLS:
            await events.status(
                f"Tool call limit ({cfg.MAX_TOOL_CALLS}) reached. Stopping further tool calls.",
                done=False,
            )
            break

    tool_results = await _execute_tool_calls(tool_calls, tool_executor)
    state.tool_calls_executed += len(tool_results)

    result_items = _tool_results_to_output_items(tool_results)
    state.structured_items.extend(result_items)

    # Feed tool outputs back into model context for the next loop
    request.input.extend(result_items)
```

Loop ends when:

* The model no longer requests tools,
* `MAX_FUNCTION_CALL_LOOPS` or `MAX_TOOL_CALLS` is hit,
* Or a fatal error occurs (see §7).

**Persistence of items happens once at the end of the turn** (see §4.4), not inside the loop. During the loop, we just accumulate `state.structured_items`.

### 4.3 Streaming a single Responses call

`_stream_single_response` encapsulates one streaming request to `/responses` and processes its events:

```python
async def _stream_single_response(
    request: ResponsesRequest,
    state: TurnState,
    ctx: TurnContext,
    events: RuntimeEvents,
    base_url: str,
    api_key: str,
) -> dict | None:
    final_response: dict | None = None

    async for event in client.stream_responses(
        request, base_url=base_url, api_key=api_key
    ):
        etype = event.type

        if etype == "response.output_text.delta":
            _handle_text_delta(event, state, events)

        elif etype == "response.reasoning_summary_text.done":
            _handle_reasoning_summary(event, events)

        elif etype == "response.output_text.annotation.added":
            _handle_text_annotation(event, state, events)

        elif etype == "response.output_item.added":
            _handle_output_item_added(event, events)

        elif etype == "response.output_item.done":
            _handle_output_item_done(event, state, ctx, events)

        elif etype == "response.completed":
            final_response = event.response
            break

        elif etype in ("response.incomplete", "response.failed"):
            state.error_message = event.error_message or (
                "Responses API returned incomplete/failed."
            )
            break

    return final_response
```

Key handlers:

#### 4.3.1 Text streaming (`response.output_text.delta`)

* Append to both visible and internal text:

  ```python
  delta = event.delta or ""
  state.assistant_visible_text += delta
  state.assistant_internal_text += delta
  ```

* Emit either:

  * `events.replace(state.assistant_visible_text)` (common pattern: always send full text), or
  * `events.delta(delta)` (if the UI expects deltas).

The reference implementation uses **full replacement** for simplicity: every call to `replace` carries the full visible text so far.

#### 4.3.2 Reasoning summary (`response.reasoning_summary_text.done`)

* Cancel any outstanding “thinking” timers (see §4.5).

* Extract the summary text and build a multi‑line status:

  * First non‑empty line → title (or default `"Thinking…"`)
  * Remaining lines → body.

* Emit:

  ```python
  await events.status(f"{title}\n{body}")
  ```

This is **UI‑facing** reasoning summary text (not the encrypted reasoning tokens requested via `include`).

#### 4.3.3 Text annotations (`response.output_text.annotation.added`)

`_handle_text_annotation` inspects the `annotation` payload.

For URL citations (`annotation.type == "url_citation"`):

* See `web_search_and_citations.md` for the full logic. Briefly:

  1. Extract and normalize `url` (strip trivial tracking params like `utm_source=openai`).

  2. Determine `host` (e.g. `example.com`) and a title.

  3. Create a `Citation` with:

     * `source_name = host or "source"`,
     * `url`,
     * `document = [title]`,
     * `metadata = {"source": url, "date_accessed": ..., "ordinal": n}`.

  4. Emit `events.source(...)` with the source + metadata.

  5. Append the citation to `state.citations`.

Other annotation types are ignored by default but must not crash the loop.

#### 4.3.4 Output items (`response.output_item.added` / `.done`)

* `output_item.added`:

  * Typically used for simple UX hints like:

    ```python
    await events.status("Responding to the user…", done=False)
    ```

    when the model starts generating a message item. This is optional.

* `output_item.done`:

  * Inspect `event.item` and:

    * If it’s a tool‑related item (e.g. `function_call`, `web_search_call`, `file_search_call`, `code_interpreter_call`):

      * Emit tool‑specific statuses (e.g. “Running the weather_lookup tool…”, “Searching”, “Reading through {{count}} sites” — see `web_search_and_citations.md`),
      * Add it to `state.structured_items` if it’s something we might want to persist later (e.g. `function_call_output`, and optionally `function_call`, `reasoning`, etc.).

    * For deep‑research models, additional item types may appear; default behavior is to log and ignore them unless explicitly supported.

The engine does **not** decide what to persist here; it just collects candidates into `state.structured_items` and defers persistence to §4.4.

#### 4.3.5 Completion (`response.completed`)

* Capture `final_response = event.response`.
* Do **not** mutate `request.input` here — it’s done by the outer loop once we extract and execute tool calls.

---

### 4.4 Persistence of structured items & markers

The engine **persists structured items once per turn**, after all tool loops are done and streaming is complete.

1. Build the list of items to persist:

   ```python
   items_to_persist = [
       item for item in state.structured_items
       if _should_persist_item(item, cfg)
   ]
   ```

   `_should_persist_item` typically:

   * Respects `cfg.PERSIST_TOOL_RESULTS` for `function_call_output` (and optionally `function_call`),
   * Respects `cfg.PERSIST_REASONING_TOKENS` for `reasoning` items,
   * Skips ephemeral operational items (like `web_search_call`) unless explicitly configured.

   See `config_and_valves.md` and `markers_and_persistence.md` for what’s recommended to persist.

2. If there are items to persist **and** we have a `chat_id` + `message_id`:

   ```python
   if items_to_persist and ctx.metadata.get("message_id") and history_key.get("chat_id"):
       state.assistant_internal_text = history_manager.persist_items_for_message(
           history_key=history_key,
           message_id=ctx.metadata["message_id"],
           items=items_to_persist,
           model_id=ctx.model_id,
           openwebui_model_id=ctx.metadata["owui_model_id"],
           current_assistant_text=state.assistant_internal_text,
       )
   ```

   * Before this call, `assistant_internal_text` == `assistant_visible_text`.
   * After this call, `assistant_internal_text` is the visible text **plus invisible markers** appended by `HistoryManager`.

3. The OpenWebUI adapter (`pipe.Pipe`) then uses `TurnResult.text` (which will be set to `assistant_internal_text`) as the message body to store in `Chats`.

> **Key invariant**
> Markers are only created and appended via `HistoryManager.persist_items_for_message`. The engine itself never hand‑crafts marker strings.

---

### 4.5 “Thinking…” statuses

To provide a better UX on reasoning‑capable models, the engine can emit a small sequence of “thinking” statuses early in the turn, before any text is streamed.

Recommended behavior (optional but supported by this doc):

* Only if:

  * `core.model_catalog.supports("reasoning", ctx.model_id)`, and
  * `cfg.REASONING_SUMMARY != "disabled"` (or some similar gate).

* Schedule a few delayed tasks:

  ```python
  async def _delayed_status(delay_s: float, description: str):
      await asyncio.sleep(delay_s + jitter)
      await events.status(description, done=False)

  thinking_tasks = [
      asyncio.create_task(_delayed_status(0.0, "Thinking…")),
      asyncio.create_task(_delayed_status(1.5, "Reading the user's question…")),
      asyncio.create_task(_delayed_status(4.0, "Gathering my thoughts…")),
      asyncio.create_task(_delayed_status(6.0, "Exploring possible responses…")),
  ]
  ```

* Cancel all `thinking_tasks` when:

  * A reasoning summary arrives,
  * The model starts streaming user‑visible text,
  * Or an error/early completion occurs.

The exact messages and timing can be adjusted as long as they don’t conflict with `responses.reasoning_summary_text.done` events.

---

### 4.6 Usage aggregation

The Responses API may include usage information on each completion:

```json
{
  "usage": {
    "input_tokens": 123,
    "output_tokens": 456,
    "cache_creation_input_tokens": 10,
    ...
  }
}
```

The engine aggregates this across loops:

1. From each `final_response`:

   ```python
   usage = final_response.get("usage") or {}
   _merge_usage(state, usage)
   ```

2. `_merge_usage` sums numeric counters (e.g., token counts) and uses last‑write‑wins for non‑numeric fields.

3. `state.usage` becomes the canonical usage summary for the entire turn.

4. At the end of the turn, `run_streaming_turn`:

   * Puts `state.usage` into `TurnResult.usage`,
   * Emits a final `chat_completion` via `events.chat_completion`:

     ```python
     await events.chat_completion({
         "content": "",
         "done": True,
         "usage": state.usage,
         "error": None or {...},
     })
     ```

Intermediate usage events (e.g. `done=False`) are optional; the adapter can choose to expose them or not.

---

### 4.7 Finalization & TurnResult

After the outer tool loop ends (normally or due to limits / error), the engine:

1. Cancels any outstanding “thinking” timers.
2. Optionally emits a last status (e.g. with elapsed time) if not in an error state.
3. Ensures a final `chat_completion` event is emitted.
4. Returns:

   ```python
   return TurnResult(
       text=state.assistant_internal_text or state.assistant_visible_text,
       usage=state.usage,
       citations=state.citations,
       error=state.error_message,
   )
   ```

* `text` is the string that should be stored as the message body in `Chats`. It **includes markers** if persistence ran; otherwise it’s just the visible text.
* Citations in `TurnResult.citations` are later persisted by the OpenWebUI adapter using `Chats.upsert_message_to_chat_by_id_and_message_id(..., {"sources": [...]})` (see `web_search_and_citations.md` and `openwebui_integration.md`).

---

## 5. Tool execution semantics

The engine only coordinates tool execution; it doesn’t know how tools are implemented.

### 5.1 Extracting tool calls

After each streamed response:

```python
def _extract_tool_calls(final_response: dict, cfg: RuntimeConfig) -> list[ToolCall]:
    calls = []
    for item in final_response.get("output", []):
        if item.get("type") != "function_call":
            continue
        calls.append(
            ToolCall(
                call_id=item.get("call_id", ""),
                name=item.get("name", ""),
                arguments_json=item.get("arguments", "{}"),
            )
        )
    return calls
```

### 5.2 Executing tool calls

Tool execution is delegated to `ToolExecutor`:

```python
tool_results: list[ToolResult] = await tool_executor.execute(tool_calls)
```

`OpenWebUIToolExecutor`:

* Looks up the Python callable by `name` in `__tools__`,
* Parses `arguments_json`,
* Executes the function (async or via a thread),
* Catches exceptions and timeouts,
* Returns `ToolResult` with appropriate `status` and `error_message`.

### 5.3 Converting results to output items

The engine converts `ToolResult` into Responses output items:

```python
def _tool_results_to_output_items(results: list[ToolResult]) -> list[dict]:
    items = []
    for result in results:
        items.append({
            "type": "function_call_output",
            "call_id": result.call_id,
            "output": result.output,
            "status": result.status,
            "error_message": result.error_message,
        })
    return items
```

These items:

* Are appended to `request.input` for the next loop,
* May be persisted via markers depending on `cfg.PERSIST_TOOL_RESULTS` and `_should_persist_item`.

---

## 6. Task models (`run_task`)

Task models (titles, tags, etc.) use non‑streaming Responses calls and **skip** tool loops and persistence.

```python
async def run_task(
    self,
    request: ResponsesRequest,
    ctx: TurnContext,
) -> str:
    ...
```

Behavior:

1. Force non‑streaming, non‑stored behavior:

   ```python
   request.stream = False
   request.store = False
   ```

2. Call:

   ```python
   response = await client.create_response(
       request,
       base_url=ctx.runtime_config.BASE_URL,
       api_key=ctx.runtime_config.API_KEY,
   )
   ```

3. Extract text from `response["output"]` message items:

   ```python
   parts = []
   for item in response.get("output", []):
       if item.get("type") != "message":
           continue
       for block in item.get("content", []):
           if block.get("type") == "output_text":
               parts.append(block.get("text", ""))
   return "".join(parts)
   ```

4. `run_task` emits no `RuntimeEvents` by default; the caller (`pipe.Pipe`) decides how to surface task results.

Tasks do **not**:

* Touch `HistoryManager`,
* Persist markers or citations,
* Update `Chats`.

They are intended to be ephemeral helpers (titles, tags, summarization jobs, etc.).

---

## 7. Error handling & invariants

The engine should be defensive and predictable:

* Wraps calls to `client.stream_responses` / `client.create_response` in try/except.

* On error:

  * Logs via `logger.error`,
  * Sets `state.error_message`,
  * Emits a `chat_completion` event with an error payload (depending on how `RuntimeEvents.chat_completion` is wired by the adapter),
  * Returns a `TurnResult` with `error` set and best‑effort `text` / `usage` / `citations`.

* Must **not** let a malformed SSE event or annotation crash the process.

**Invariants to preserve:**

1. **Single logical completion** per turn:

   * The adapter should see exactly one final `chat_completion(done=True, ...)`.

2. **Markers only via HistoryManager**:

   * The engine never hand‑constructs markers; it only calls `HistoryManager.persist_items_for_message`.

3. **Reconstructable history**:

   * `TurnResult.text` is exactly what we want stored in `Chats.message["content"]`, including markers,
   * Future turns can reconstruct full `input` using `HistoryManager.build_input_from_messages` on `messages[]`.

---

## 8. Testing guidelines

When testing `domain.engine.ResponsesEngine`, use test doubles for all collaborators.

**1. Mock `OpenAIClient`**

* For streaming:

  * Have `stream_responses` yield sequences of `ResponsesEvent` for:

    * Text‑only runs (`output_text.delta`, `completed`),
    * Runs with function calls + outputs,
    * Runs with `url_citation` annotations,
    * Runs with `web_search_call` items.

* For `run_task`:

  * Return canned `response["output"]` arrays.

**2. Fake `HistoryManager`**

* Provide a stub whose `persist_items_for_message`:

  * Records `history_key`, `items`, `current_assistant_text`,
  * Returns `current_assistant_text + "<MARKERS>"` to make assertions easy.

**3. Fake `RuntimeEvents`**

* Capture:

  * All calls to `status`, `delta`/`replace`, `source`, `citation`, `chat_completion`, `notification`.
* Assert:

  * Visible text grows as expected,
  * At least one `chat:message`‑style event is emitted when there is text,
  * A final `chat_completion(done=True, ...)` is emitted,
  * Status messages for tools + web search match expectations (see `web_search_and_citations.md`).

**4. Fake `ToolExecutor`**

* Implement:

  * One tool that succeeds (`status="ok"`),
  * One that raises to test error mapping (`status="error"`).

* Assert:

  * Engine still progresses to the next loop,
  * Resulting items reflect `status` and `error_message`,
  * `tool_calls_executed` increments properly,
  * Tool outputs are reflected in `request.input` for the next loop.

**5. Error paths**

* Simulate client exceptions mid‑stream.
* Assert:

  * `TurnResult.error` is set,
  * The engine does not crash,
  * Any scheduled “thinking” tasks are cancelled,
  * A final `chat_completion` is still emitted (depending on adapter behavior).

---

With `ResponsesEngine` implemented according to this document, the manifold has a **clean, testable domain core**:

* The OpenWebUI adapter only needs to:

  * Build a `ResponsesRequest` from `messages[]`,
  * Build `TurnContext`, `history_key`, and a `ToolExecutor`,
  * Wrap the Open WebUI event emitter into `RuntimeEvents`,
  * Call `run_streaming_turn` / `run_task`,
  * Persist `TurnResult.text` as the message body and `TurnResult.citations` as `sources`.

Everything else—streaming, tool loops, reasoning, web search, citations, and marker persistence—is encapsulated here.