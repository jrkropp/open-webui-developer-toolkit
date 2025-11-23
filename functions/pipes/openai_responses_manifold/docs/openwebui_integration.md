# Open WebUI Integration Guide

`functions/pipes/openai_responses_manifold/docs/openwebui_integration.md`

> **Audience**
>
> * AI agents and humans modifying the OpenAI Responses manifold’s **Open WebUI integration**.
> * Anyone debugging how `openai_responses_manifold` plugs into Open WebUI.

> **Scope**
>
> This document explains how the **OpenAI Responses manifold** integrates with Open WebUI:
>
> * The `Pipe` contract and call flow.
> * How the `openwebui.*` adapters work (`store`, `events`, `tools`, `bridge`).
> * How chats, models, tools, filters, tasks, and events are wired together.
> * Where persistence and citations touch the Open WebUI data model.

It complements:

* `manifold_refactor.md` (canonical architecture & checklist)
* `markers_and_persistence.md`
* `history_manager.md`
* `responses_engine.md`
* `tools_and_extra_tools.md`
* `web_search_and_citations.md`
* `config_and_valves.md`

> **Legacy note:** `src_old/` and `tests_old/` contain the prior monolithic implementation and its tests. Keep them untouched; all changes should target the layered source under `src/` and the new tests under `tests/`.

---

## 1. Big picture: where this manifold sits

Open WebUI sees the manifold as a **pipe**:

1. It loads `Pipe` from the manifold’s Python module.
2. It calls `Pipe.pipes()` to enumerate the “models” exposed by the pipe.
3. For each chat turn or task, it calls `Pipe.pipe(...)` with:

   * A Completions‑style `body` (`messages`, `tools`, `extra_tools`, etc.).
   * Additional context: `__user__`, `__metadata__`, `__tools__`, `__event_emitter__`, `__event_call__`, and optionally `__task__`.

Internally, the manifold is layered:

```text
Open WebUI frontend
   ↑               ↑
   |             events (chat:message, status, source, citation, ...)
   |
Pipe.pipe(...)
   ↓
openwebui.*        (adapters: bridge, store, events, tools)
   ↓
domain.*           (engine, history manager, tools policy, routing)
   ↓
openai_api.*       (ResponsesRequest, OpenAIClient, streaming HTTP)
   ↓
core.*             (config/valves, logging, model catalog, markers)
   ↓
OpenAI Responses API
   ↓
Chats DB (via OpenWebUIHistoryStore + markers)
```

**Invariants:**

* Open WebUI’s **`body.messages`** is the **single source of history** that filters and the pipe operate on.
* All Open WebUI–specific logic lives in `openwebui.*` and `pipe.Pipe`.
* `domain.*` + `openai_api.*` are UI‑agnostic and testable without importing Open WebUI.

---

## 2. Where `Pipe` lives and what it exposes

### 2.1 Module & file layout

Library layout (simplified):

```text
src/
  openai_responses_manifold/
    __init__.py          # re-exports Pipe
    pipe.py              # defines class Pipe

    core/
      config.py          # PipeValves, UserValves, RuntimeConfig, merge_valves
      logging.py         # session-aware logging
      model_catalog.py   # model alias + feature registry
      markers.py         # marker encode/decode

    openai_api/
      types.py           # ResponsesRequest, ResponsesEvent
      client.py          # OpenAIClient (stream + create)

    domain/
      types.py           # TurnContext, TurnResult, RuntimeEvents, etc.
      history.py         # HistoryStore + HistoryManager
      tools.py           # ToolDefinition/Registry/Executor/Policy
      web_search.py      # web_search tool construction
      code_interpreter.py
      routing.py         # gpt‑5‑auto router helper
      engine.py          # ResponsesEngine

    openwebui/
      store.py           # OpenWebUIHistoryStore
      events.py          # OpenWebUIRuntimeEvents
      tools.py           # OpenWebUIToolRegistry/Executor
      bridge.py          # Completions → Responses mapping
```

The pipe entrypoint in `functions/pipes/openai_responses_manifold/` imports and re‑exports `openai_responses_manifold.pipe.Pipe` so Open WebUI can load it.

### 2.2 `Pipe` class shape

`Pipe` has the standard Open WebUI pipe interface:

```python
class Pipe:
    class Valves(core.config.PipeValves):
        ...

    class UserValves(core.config.UserValves):
        ...

    def __init__(self):
        self.type = "manifold"
        self.id = "openai_responses"

        self.valves = Pipe.Valves()
        self.logger = core.logging.get_logger(__name__)

        self.client = OpenAIClient()
        self.history_store = OpenWebUIHistoryStore()
        self.history_manager = HistoryManager(self.history_store)
        self.engine = ResponsesEngine(
            client=self.client,
            history_manager=self.history_manager,
            logger=self.logger,
        )

    async def pipes(self) -> list[dict]:
        ...

    async def pipe(
        self,
        body,
        __user__,
        __request__,
        __event_emitter__,
        __event_call__,
        __metadata__,
        __tools__,
        __task__=None,
        __task_body__=None,
    ):
        ...
```

Open WebUI only ever calls `pipes()` and `pipe()`.

---

## 3. `Pipe.pipes()` — which models show up in Open WebUI

`Pipe.pipes()` tells Open WebUI which logical models this manifold exposes.

**Behavior:**

1. Read pipe‑level valves:

   ```python
   cfg = self.valves  # Pipe.Valves instance
   ```

2. Split `cfg.MODEL_ID` (comma‑separated):

   ```python
   ids = [m.strip() for m in cfg.MODEL_ID.split(",") if m.strip()]
   ```

3. Return one dict per id:

   ```python
   return [
       {
           "id": model_id,                       # e.g. "gpt-5.1-chat-latest"
           "name": f"OpenAI Responses: {model_id}",
       }
       for model_id in ids
   ]
   ```

Open WebUI wraps this with the pipe id, so the actual model id becomes:

```text
openai_responses.<model_id>
# e.g. "openai_responses.gpt-5.1-chat-latest"
```

This value comes back on each `pipe()` call in:

```python
__metadata__["model"]["id"]  # e.g. "openai_responses.gpt-5.1-chat-latest"
```

---

## 4. `Pipe.pipe()` — normal chat lifecycle

For **normal chat turns** (`__task__` is `None`), `Pipe.pipe()` coordinates:

* valves → runtime config,
* logging,
* Open WebUI adapters,
* domain engine.

High‑level flow:

1. **Merge valves → RuntimeConfig**

   ```python
   pipe_valves = self.valves
   user_valves_data = (__user__ or {}).get("valves") or {}
   user_valves = Pipe.UserValves.model_validate(user_valves_data)

   cfg = core.config.merge_valves(pipe_valves, user_valves)
   ```

2. **Set logging context**

   ```python
   session_id = (__metadata__ or {}).get("session_id")
   level = core.logging.level_from_string(cfg.LOG_LEVEL)

   with core.logging.set_session(session_id, level):
       ...
   ```

   Inside this context, all log output is captured per session and can be surfaced as a log citation if desired.

3. **Wrap event emitter**

   ```python
   events = OpenWebUIRuntimeEvents(__event_emitter__)
   ```

   This object implements `RuntimeEvents` (see §6) and converts domain‑level events into Open WebUI events.

4. **Build `TurnContext`**

   Let the bridge build a context object:

   ```python
   ctx = openwebui.bridge.build_turn_context(
       pipe_valves=pipe_valves,
       user_valves=user_valves,
       runtime_cfg=cfg,
       __user__=__user__,
       __metadata__=__metadata__,
   )
   ```

   `TurnContext` contains:

   * `runtime_config` (merged valves),
   * `model_id` (canonical OpenAI base model, e.g. `"gpt-5.1"`),
   * `features` (from `core.model_catalog`),
   * `metadata`:

     * `session_id`, `chat_id`, `message_id`,
     * `user_id`, `user_email`,
     * `owui_model_id` (e.g. `"openai_responses.gpt-5.1-chat-latest"`).

5. **Prepare a history key**

   ```python
   history_key = {
       "chat_id": (__metadata__ or {}).get("chat_id"),
       "pipe_id": self.id,
   }
   ```

   `OpenWebUIHistoryStore` uses `chat_id` plus the `openai_responses_pipe` layout (see `markers_and_persistence.md`).

6. **Normalize `__tools__` and build registry/executor**

   ```python
   if inspect.isawaitable(__tools__):
       __tools__ = await __tools__

   registry = OpenWebUIToolRegistry(__tools__ or {})
   executor = OpenWebUIToolExecutor(__tools__ or {})
   ```

   * `registry` implements `ToolRegistry` (definitions).
   * `executor` implements `ToolExecutor` (callables).

7. **Task short‑circuit**

   If `__task__` is not `None`, skip the streaming chat logic and follow the **task path** (see §5).

8. **Map Completions → Responses**

   For normal chat, convert the Completions‑style `body` into a `ResponsesRequest` and tool lists:

   ```python
   request, base_tools, extra_tools = openwebui.bridge.map_completions_to_responses(
       body=body,
       ctx=ctx,
       history_manager=self.history_manager,
       history_key=history_key,
   )
   ```

   The bridge:

   * Uses `body["messages"]` (after filters).

   * Calls `HistoryManager.build_input_from_messages`:

     * Rehydrates markers + persist items from `openai_responses_pipe`.
     * Returns `request.input` and `request.instructions`.

   * Drops unsupported Completions fields.

   * Maps `max_tokens` → `max_output_tokens`, `reasoning_effort` → `reasoning.effort`.

   * Separately returns `base_tools` (from `body.tools`) and `extra_tools` (from `body.extra_tools`).

9. **Build MCP + web search tools**

   * MCP tools from valves:

     ```python
     mcp_tools = openwebui.bridge.build_mcp_tools(cfg)
     ```

   * Web search tools from domain layer:

     ```python
     web_search_tools = domain.web_search.build_web_search_tools(
         model_id=ctx.model_id,
         features=ctx.features,
         cfg=cfg,
     )
     ```

10. **Build final `tools` list**

    Use domain tool policy:

    ```python
    tools_for_responses = domain.tools.ToolPolicy.build_responses_tools(
        model_id=ctx.model_id,
        features=ctx.features,
        cfg=cfg,
        registry=registry,
        body_tools=base_tools,
        extra_tools=extra_tools,
        mcp_tools=mcp_tools,
        web_search_tools=web_search_tools,
    )
    ```

    * Skips function tools when the model doesn’t support them.
    * Converts registry tools to function tools.
    * Applies strict schemas if `cfg.ENABLE_STRICT_TOOL_CALLING`.
    * Merges registry, body, `extra_tools`, MCP, and web_search tools.
    * Deduplicates by `(type, name)` with last‑wins semantics.

    Attach if non‑empty:

    ```python
    if tools_for_responses:
        request.tools = tools_for_responses
    ```

11. **Configure reasoning, persistence, and includes**

    * Reasoning summary:

      ```python
      if "reasoning_summary" in ctx.features and cfg.REASONING_SUMMARY != "disabled":
          request.reasoning = request.reasoning or {}
          request.reasoning["summary"] = cfg.REASONING_SUMMARY
      ```

    * Encrypted reasoning tokens:

      ```python
      if "reasoning" in ctx.features and cfg.PERSIST_REASONING_TOKENS != "disabled":
          request.include = list(request.include or [])
          if "reasoning.encrypted_content" not in request.include:
              request.include.append("reasoning.encrypted_content")
      ```

    * Web search sources:

      ```python
      if any(t.get("type") == "web_search" for t in (request.tools or [])):
          request.include = list(request.include or [])
          if "web_search_call.action.sources" not in request.include:
              request.include.append("web_search_call.action.sources")
      ```

12. **Model routing for `.gpt-5-auto*`**

    If `ctx.metadata["owui_model_id"]` ends in `.gpt-5-auto-dev` or `.gpt-5-auto`:

    ```python
    request = await domain.routing.route_auto_model(
        client=self.client,
        request=request,
        ctx=ctx,
        tools=request.tools or [],
        events=events,
    )
    ```

    The router may:

    * Set `request.model` (concrete model).
    * Set `request.reasoning["effort"]`.
    * Attach `model_router_result` that the engine will use to emit a routing status.

13. **Auto‑enable native function calling (Models)**

    For backwards compatibility with existing Open WebUI model configs:

    * Inspect model config:

      ```python
      from open_webui.models.models import Models
      owui_model_id = ctx.metadata["owui_model_id"]
      model = Models.get_model_by_id(owui_model_id)
      ```

    * If tools exist, model supports tools, and `params["function_calling"] != "native"`:

      * Update the model record (e.g. `function_calling="native"`).
      * Emit a `notification` event telling the user to re‑run.
      * Short‑circuit this request (don’t call OpenAI this time).

    This keeps Open WebUI’s persistent model settings in sync with how the manifold expects to run tools.

14. **CSS injection for multi‑line status (optional)**

    Using `__event_call__`, `Pipe.pipe` can inject a tiny JS/CSS patch once per tab to:

    * Allow multi‑line status descriptions (`white-space: pre-wrap`).
    * Remove any built‑in line clamping for status text.

    This is optional but keeps status UX consistent with the legacy manifold.

15. **Run the streaming engine**

    Finally, call the domain engine:

    ```python
    result = await self.engine.run_streaming_turn(
        request=request,
        ctx=ctx,
        events=events,
        history_key=history_key,
        tool_executor=executor,
    )
    ```

    `run_streaming_turn` will:

    * Stream output text (`chat:message`).
    * Emit statuses, sources, and citations.
    * Persist items via `HistoryManager` (markers) as needed.
    * Return a `TurnResult` with:

      * `text` (assistant visible text),
      * `usage`,
      * `citations`,
      * `error` (if any).

16. **Persist citations onto the message**

    If citations exist and we know `chat_id` and `message_id`, `Pipe.pipe` persists them using `Chats`:

    ```python
    from open_webui.models.chats import Chats

    if result.citations and __metadata__.get("chat_id") and __metadata__.get("message_id"):
        Chats.upsert_message_to_chat_by_id_and_message_id(
            __metadata__["chat_id"],
            __metadata__["message_id"],
            {
                "sources": [
                    {
                        "source": {"name": c.source_name, "url": c.url},
                        "document": c.document,
                        "metadata": [c.metadata],
                    }
                    for c in result.citations
                ]
            },
        )
    ```

    Citation shape is aligned with `web_search_and_citations.md`.

17. **Return assistant text**

    `Pipe.pipe` returns `result.text` (the visible assistant text) to Open WebUI. The UI uses this as the message content.

---

## 5. `Pipe.pipe()` — task lifecycle (`__task__`)

When Open WebUI calls the pipe for **tasks** (e.g. titles, tags), it passes a non‑`None` `__task__`.

Task flow:

1. Still merge valves, build `TurnContext`, and set logging context as in chat mode.

2. Use the bridge to build a small `ResponsesRequest`:

   * Based on `__task_body__` or a minimal subset of `body`.
   * Often just the last message or prompt.
   * `stream = False`
   * `store = False`
   * No tools.

3. Call:

   ```python
   text = await self.engine.run_task(request, ctx)
   ```

   `run_task`:

   * Uses `OpenAIClient.create_response` (non‑streaming).
   * Extracts plain text from `output` message items.
   * Returns a string.

4. `Pipe.pipe` returns that string directly for the task consumer.

**Tasks do not:**

* Modify `Chats` history.
* Use markers or `openai_responses_pipe`.
* Emit streaming events (unless you choose to extend this).

---

## 6. Event mapping: `OpenWebUIRuntimeEvents`

`OpenWebUIRuntimeEvents` wraps `__event_emitter__` and implements `RuntimeEvents` for the domain engine.

### 6.1 Methods → Open WebUI events

**`status(description: str, done: bool = False, **extra)`**

Emits a status payload:

```jsonc
{
  "type": "status",
  "data": {
    "description": "Thinking…",
    "done": false
    // plus any extra fields (action, urls, etc.) if needed
  }
}
```

Used for:

* “Thinking…” and other reasoning statuses.
* Tool activity (“Running the weather_lookup tool…”).
* Web search status (“Searching”, “Reading through {{count}} sites”).

---

**`delta(content: str)` / `replace(content: str)`**

For simplicity, both typically map to a **full message update**:

```jsonc
{
  "type": "chat:message",
  "data": { "content": "<full assistant text so far>" }
}
```

The engine usually passes the full accumulated text, so the UI can treat each event as “replace current assistant message content”.

---

**`chat_completion(data: dict)`**

Final completion / bookkeeping:

```jsonc
{
  "type": "chat:completion",
  "data": {
    "content": "",
    "done": true,
    "usage": { /* ... */ },
    "error": { /* optional */ }
  }
}
```

The engine guarantees a logical completion with `done: true` once per turn (even on error).

---

**`citation(data: dict)`**

For textual citations (e.g. logs):

```jsonc
{
  "type": "citation",
  "data": {
    "document": ["line 1", "line 2"],
    "metadata": [{ "source": "Logs" }],
    "source": { "name": "Logs" }
  }
}
```

---

**`source(data: dict)`**

For URL-based citations:

```jsonc
{
  "type": "source",
  "data": {
    "source": { "name": "example.com", "url": "https://example.com/article" },
    "document": ["Example Article"],
    "metadata": [
      {
        "source": "https://example.com/article",
        "date_accessed": "2025-11-22"
      }
    ]
  }
}
```

---

**`notification(content: str, level: "info" | "success" | "warning" | "error" = "info")`**

Toast‑style notifications:

```jsonc
{
  "type": "notification",
  "data": {
    "type": "info",
    "content": "Enabling native function calling for this model; please re-run your query."
  }
}
```

---

## 7. Chat persistence & `OpenWebUIHistoryStore`

Integration with **Chats** is isolated in `openwebui.store.OpenWebUIHistoryStore`, which implements the `HistoryStore` protocol used by `HistoryManager`.

### 7.1 Persisting items (`save_items`) and markers

When the engine wants to persist structured items (tool outputs, reasoning, etc.), it calls `HistoryManager.persist_items_for_message`, which:

1. Calls `OpenWebUIHistoryStore.save_items` with:

   * `chat_key` (includes `chat_id`),
   * `message_id`,
   * `items`,
   * `openwebui_model_id`.

2. `OpenWebUIHistoryStore.save_items`:

   * Loads the chat via `Chats.get_chat_by_id(chat_id)`.
   * Ensures `chat.chat["openai_responses_pipe"]` exists in the shape documented in `markers_and_persistence.md`.
   * Generates ULIDs via `core.markers.generate_ulid`.
   * Stores items under `openai_responses_pipe["items"][ulid]`.
   * Updates `messages_index[message_id]["item_ids"]`.
   * Saves the chat via `Chats.update_chat_by_id`.

3. `HistoryManager.persist_items_for_message` builds marker strings for each ULID and appends them to the assistant text. The **stored message content** contains:

   * Visible assistant text,
   * Plus invisible markers.

### 7.2 Loading items (`load_items`) for history reconstruction

On subsequent turns, `HistoryManager.build_input_from_messages`:

1. Scans assistant messages for markers.
2. Collects all ULIDs.
3. Calls `OpenWebUIHistoryStore.load_items(chat_key, item_ids, model_id=openwebui_model_id)`.

`load_items`:

* Reads `chat.chat["openai_responses_pipe"]["items"]`.
* Returns a dict `{ulid: payload}` for matching `model_id`.

`HistoryManager` then re‑interleaves these payloads with visible text to produce the Responses `input[]` array. See `history_manager.md` and `markers_and_persistence.md` for details.

---

## 8. Models & native function calling

The Open WebUI **Models** table still controls per‑model settings like `function_calling`.

**Integration pattern:**

* `__metadata__["model"]["id"]` gives the full Open WebUI model id (e.g. `"openai_responses.gpt-5.1-chat-latest"`).
* The manifold uses `core.model_catalog` to understand **capabilities** (tools, reasoning, web search).
* `Pipe.pipe` may:

  * Look up model config via `Models.get_model_by_id(owui_model_id)`.
  * If tools are present and `function_calling` is not `"native"`:

    * Optionally patch the model (`Models.update_model_by_id`).
    * Emit a `notification` telling the user to re-run.

This keeps the source of truth for per‑model flags inside Open WebUI, with the manifold nudging it into a compatible state.

---

## 9. Filters, `body`, and `extra_tools`

Filters can mutate the incoming `body` before the manifold sees it.

Integration rules:

* `body.messages` (plus markers in stored messages) is the **only** conversation history the manifold uses. It does **not** maintain a separate shadow history.
* `body.tools` and `body.extra_tools` are treated as real tool sources:

  * `openwebui.bridge.map_completions_to_responses` passes both into `ToolPolicy.build_responses_tools`.
  * Filter‑injected tools in `body.extra_tools` can override registry tools with the same identity.
  * `extra_tools` do **not** automatically become executable; they need matching entries in `__tools__` if they should run locally.

This preserves the existing filter model while upgrading the underlying API to Responses.

---

## 10. Non‑streaming chat (`body.stream == False`)

The manifold is designed for **streaming** chat (`stream=True`). Non‑streaming chat handling is a policy choice.

Two common options:

1. **Simple explicit error (safe default)**

   If `body.get("stream") is False` and this is a chat turn:

   * Emit a `notification` or `chat_completion` with an error like:

     > “Non‑streaming chat is not supported by the OpenAI Responses manifold. Please enable streaming and try again.”

   * Return an empty string or a short error message.

2. **Full non‑stream support (optional)**

   * Use `OpenAIClient.create_response` instead of streaming.
   * Or run the streaming engine with a `RuntimeEvents` implementation that buffers text and emits only a final `chat_completion`.

The workpackage leaves this as an optional enhancement; you can start with option (1) and evolve later.

---

## 11. Error handling & logs

Errors are handled across:

* `core.logging` (session‑scoped log buffering),
* `ResponsesEngine`,
* `Pipe`.

Typical behavior:

* `Pipe.pipe` wraps the call in `set_session` so logs are tied to a `session_id`.

* `ResponsesEngine.run_streaming_turn`:

  * Catches client / tool errors.
  * Sets `TurnState.error_message` on failure.
  * Emits a final `chat_completion` with `done=True` and an error (depending on how `RuntimeEvents.chat_completion` is implemented).

* Optional **log citation**:

  * At the end of a turn, if log‑as‑citation is enabled by valves, logs for this session can be joined and emitted via `events.citation` as a “Logs” source.

After each turn, logs for the session are cleared to avoid unbounded growth.

---

## 12. Quick checklist when modifying integration

When you change the Open WebUI integration:

* Keep **all** Open WebUI‑specific code in `openwebui.*` and `pipe.Pipe`.

* Treat `body.messages` + markers + `Chats` as the **single history source**.

* Use:

  * `OpenWebUIHistoryStore` ⇄ `HistoryManager` for persistence and replay,
  * `OpenWebUIToolRegistry` / `OpenWebUIToolExecutor` for tools,
  * `OpenWebUIRuntimeEvents` for events.

* Don’t call `__event_emitter__` directly from outside `OpenWebUIRuntimeEvents`.

* Don’t talk to `Chats` or `Models` from domain or core layers.

If you keep these boundaries intact, you can safely evolve the manifold, swap in new UI behaviors, and add features without re‑entangling the architecture.
