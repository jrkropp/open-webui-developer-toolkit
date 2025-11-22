# Web Search & Citations

**File:** `functions/pipes/openai_responses_manifold/docs/web_search_and_citations.md`

This document explains how **web search** and **URL-based citations** work in the OpenAI Responses manifold, and how they integrate with:

* `domain.web_search` — building the `web_search` tool definition.
* `domain.engine.ResponsesEngine` — streaming loop and event handling.
* `openwebui.events.OpenWebUIRuntimeEvents` — UI events.
* `openwebui.store.OpenWebUIHistoryStore` + `Chats` — persistence of search-related data and citations.

It’s meant for AI agents and humans modifying or extending these areas.

You should read this together with:

* `config_and_valves.md` (web search–related valves).
* `tools_and_extra_tools.md` (tool merging & strict mode).
* `responses_engine.md` (streaming loop, events, tool calls).
* `markers_and_persistence.md` + `history_manager.md` (how history is reconstructed).

---

## 1. What “web search & citations” cover

There are three related but distinct concerns:

1. **Web search tool exposure**
   Deciding *when* to attach a `{"type": "web_search", ...}` tool to the Responses request and how to configure it.

2. **Web search activity & UX**
   Handling `web_search_call` output items from the Responses API and turning them into status updates like:

   * “Searching”
   * “Reading through {{count}} sites”

3. **URL-based citations**
   Handling inline `url_citation` annotations from the model:

   * Turning them into `source` events (for the Sources UI).
   * Persisting them as `sources` metadata on the message.
   * Keeping this separate from marker-based persistence of hidden items.

High-level flow:

```text
domain.web_search.build_web_search_tools(...)
  ↓ (tool definition)
ResponsesRequest.tools
  ↓ (OpenAI Responses call)
ResponsesEngine.run_streaming_turn(...)
  ↙                     ↘
web_search_call items     url_citation annotations
  ↓                       ↓
status events           source events + Citation[]
  ↓                       ↓
OpenWebUI UI           Chats.message["sources"]
```

> **Note:** This doc only covers URL-based citations from the model. “Log citations” (debug logs emitted as `citation` events) are described in `responses_engine.md` and `config_and_valves.md`.

---

## 2. When the web search tool is enabled

The `domain.web_search.build_web_search_tools` helper is responsible for deciding whether to attach a web search tool, and if so, how to configure it.

### 2.1 Inputs

```python
build_web_search_tools(
    model_id: str,
    features: set[str],
    cfg: RuntimeConfig,
) -> list[dict]
```

* `model_id: str`
  Canonical OpenAI base model id (from `core.model_catalog.base_model(...)`).

* `features: set[str]`
  From `core.model_catalog.features(model_id)` — includes flags like `"web_search_tool"` and `"reasoning"`.

* `cfg: RuntimeConfig`
  Merged pipe + user valves (see `config_and_valves.md`):

  * `ENABLE_WEB_SEARCH_TOOL: bool`
  * `WEB_SEARCH_CONTEXT_SIZE: "low" | "medium" | "high" | None`
  * `WEB_SEARCH_USER_LOCATION: Optional[str]` (JSON string)
  * Plus other knobs (not all are relevant here).

### 2.2 Conditions

`build_web_search_tools` returns a list with *zero or one* `web_search` tool.

We only attach a web search tool when **all** of the following are true:

1. The model supports web search:

   ```python
   core.model_catalog.supports("web_search_tool", model_id) is True
   ```

2. Web search is enabled by config:

   * `cfg.ENABLE_WEB_SEARCH_TOOL` is `True`, **or**
   * A per-model feature flag in `features` or metadata indicates web search should be used.

3. Effective reasoning effort is not `"minimal"` (for reasoning-capable models):

   * If the final `ResponsesRequest.reasoning.effort == "minimal"`, we **do not** attach a `web_search` tool, to keep minimal-effort runs cheap and focused.

Where condition (3) is enforced depends on how you thread state through:

* Either:

  * The OpenWebUI adapter checks `request.reasoning.effort` before calling `build_web_search_tools`, **or**
  * You extend `build_web_search_tools` to accept the effective reasoning effort.

The important invariant is: **no web_search tool when reasoning effort is explicitly `"minimal"`**.

### 2.3 Tool spec

When enabled, `build_web_search_tools` returns a single dict:

```python
tool = {
    "type": "web_search",
    "search_context_size": cfg.WEB_SEARCH_CONTEXT_SIZE,  # "low" | "medium" | "high" | None
}
```

If `cfg.WEB_SEARCH_USER_LOCATION` is set, we attempt to parse it as JSON:

```python
try:
    location = json.loads(cfg.WEB_SEARCH_USER_LOCATION)
    tool["user_location"] = location
except Exception:
    logger.warning("WEB_SEARCH_USER_LOCATION is not valid JSON; ignoring.")
```

On parse error, we **log and ignore**; we never fail the request because of a bad location config.

The tools layer (`domain.tools.ToolPolicy.build_responses_tools`) merges this tool with function tools, MCP tools, and filter‑injected `extra_tools`.

---

## 3. Request shaping for web search

Once `domain.web_search` returns a web search tool, the OpenWebUI adapter must ensure the Responses request is set up to return useful web search metadata.

### 3.1 Attaching the tool

In `openwebui.bridge.map_completions_to_responses`:

1. It calls `ToolPolicy.build_responses_tools(...)`, which may include the `web_search` tool.
2. If the final `tools` list contains any item where `tool["type"] == "web_search"`, and the model supports function calling, the adapter assigns:

   ```python
   if tools_for_responses:
       request.tools = tools_for_responses
   ```

### 3.2 `include` fields for sources

To receive **sources** from web search calls, the request must add:

* `"web_search_call.action.sources"` to `request.include`.

Logic:

```python
if any(t.get("type") == "web_search" for t in (request.tools or [])):
    includes = list(request.include or [])
    if "web_search_call.action.sources" not in includes:
        includes.append("web_search_call.action.sources")
    request.include = includes
```

This ensures the Responses API includes, for each `web_search_call` item:

```json
{
  "type": "web_search_call",
  "action": {
    "type": "search",
    "query": "...",
    "sources": [
      { "url": "...", "title": "...", ... },
      ...
    ]
  }
}
```

Later, `ResponsesEngine` uses this to generate status events and citations.

---

## 4. Handling `web_search_call` items in the engine

The streaming logic in `domain.engine.ResponsesEngine.run_streaming_turn` is responsible for interpreting `web_search_call` output items and emitting status events.

### 4.1 Where `web_search_call` items appear

The Responses API surfaces `web_search_call` items via:

* **Streaming events**:

  * `response.output_item.added`
  * `response.output_item.done`

* Final completion payload:

  * `response.completed.response["output"]` includes all output items.

Typical shape:

```json
{
  "type": "web_search_call",
  "status": "completed",
  "name": "web_search",
  "action": {
    "type": "search",
    "query": "user’s query",
    "sources": [
      { "url": "...", "title": "...", ... },
      ...
    ]
  }
}
```

### 4.2 Status events for `action.type == "search"`

For `web_search_call` items where `action["type"] == "search"`:

1. Extract:

   ```python
   action = item.get("action") or {}
   query = action.get("query")
   raw_sources = action.get("sources") or []
   urls = [s.get("url") for s in raw_sources if s.get("url")]
   count = len(urls)
   ```

2. On search start, emit a **searching** status:

   ```python
   if query:
       await events.status("Searching", done=False)
       # Optionally, include query in extra fields if your UI uses them:
       # await events.status("Searching", done=False, query=query)
   ```

3. When sources are available, emit a **reading sources** status:

   ```python
   if count:
       await events.status("Reading through {{count}} sites", done=False)
       # Optionally: await events.status("Reading through {{count}} sites", done=False, urls=urls)
   ```

`{{count}}` is treated as a template by the frontend and replaced with the actual number of URLs.

These status updates give the user a sense of progress while the model is searching and reading.

### 4.3 Other `action.type` values (deep research models)

For deep-research-style models, additional `action.type` values may appear:

* `"open_page"`
* `"find_in_page"`
* Other future types.

Baseline behavior:

* Recognize these types and **do not crash**.
* For now, it’s acceptable to just rely on the general “Thinking…” / “Responding…” statuses from the engine.
* Future extensions may:

  * Show more specific statuses (“Opening page N of M…”, “Searching within page…”).
  * Persist additional structured data if desired.

### 4.4 Persistence of `web_search_call` items

By default:

* `web_search_call` items are **not** persisted via markers and are **not** stored in the `openai_responses_pipe` history.
* They are treated as transient operational details.

When deciding which items to persist in `ResponsesEngine` (see `responses_engine.md`):

* Never persist `web_search_call` items unless you explicitly extend the persistence spec and update `markers_and_persistence.md` accordingly.

---

## 5. URL annotations → citations

Inline URL citations are separate from web search calls: the model can attach **URL annotations** to its text, regardless of whether web search is used.

These arrive as streaming events:

* `response.output_text.annotation.added`

### 5.1 Event shape

A typical URL citation annotation:

```json
{
  "type": "response.output_text.annotation.added",
  "annotation": {
    "type": "url_citation",
    "url": "https://example.com/article?utm_source=openai",
    "title": "Example Article",
    "start_index": 120,
    "end_index": 135
  }
}
```

The engine cares about:

* `annotation["type"] == "url_citation"`
* `annotation["url"]`
* `annotation["title"]` (optional)

### 5.2 Normalizing and tracking citations

Within `ResponsesEngine.run_streaming_turn`:

1. Maintain per-turn state:

   ```python
   citations: list[Citation] = []
   seen_urls: dict[str, int] = {}
   ```

2. On each url_citation annotation:

   ```python
   annotation = event.annotation or {}
   url = annotation.get("url")
   if not url:
       return  # ignore malformed annotation

   # Strip trivial tracking params (implementation-specific):
   url = _strip_trivial_tracking(url)  # e.g. drop '?utm_source=openai'

   title = annotation.get("title") or url
   host = _host_from_url(url)  # e.g., "example.com"
   ```

3. Assign an ordinal index per URL (if you want numbered citations):

   ```python
   if url not in seen_urls:
       seen_urls[url] = len(seen_urls) + 1
   n = seen_urls[url]
   ```

4. Construct a `Citation` (see `domain.types.Citation`):

   ```python
   citation = Citation(
       source_name=host or "source",
       url=url,
       document=[title],
       metadata={
           "source": url,
           "date_accessed": datetime.date.today().isoformat(),
           "ordinal": n,
       },
   )
   ```

5. Emit a **source event** via `RuntimeEvents.source`:

   ```python
   await events.source({
       "source": {"name": citation.source_name, "url": citation.url},
       "document": citation.document,
       "metadata": [citation.metadata],
   })
   ```

6. Append to the engine’s `TurnState.citations`:

   ```python
   state.citations.append(citation)
   ```

> **Note:** The engine doesn’t need to modify the assistant text with explicit `[1]` markers. The UI can choose how to visually associate text with sources using the `source` events and message-level `sources` metadata.

---

## 6. Persisting citations on the message

Citations are **not** persisted via markers. Instead, they are stored as structured metadata (`sources`) on the assistant message via the OpenWebUI chat model.

### 6.1 Where they are stored

At the end of `ResponsesEngine.run_streaming_turn`, after streaming completes:

1. The engine has:

   * `state.citations: list[Citation]`
   * `ctx.metadata["chat_id"]`
   * `ctx.metadata["message_id"]`

2. If `citations` is non‑empty and both identifiers are present, the OpenWebUI adapter calls:

   ```python
   from open_webui.models.chats import Chats

   Chats.upsert_message_to_chat_by_id_and_message_id(
       chat_id,
       message_id,
       {
           "sources": [
               {
                   "source": {"name": c.source_name, "url": c.url},
                   "document": c.document,
                   "metadata": [c.metadata],
               }
               for c in state.citations
           ],
       },
   )
   ```

This updates the stored chat document so that:

* The assistant message for this turn has a `sources` field.
* The frontend can render sources for both **live** and **historical** messages.

### 6.2 Relationship to marker-based persistence

Markers (`[openai_responses:v2:...]: #`) are used for:

* Hidden items like `function_call`, `function_call_output`, `reasoning`, etc.
* Reconstructing `input` for future Responses calls (see `markers_and_persistence.md` and `history_manager.md`).

Citations:

* Are **not** embedded in assistant text as markers.
* Are not part of `openai_responses_pipe.items`.
* Live purely as message-level metadata (`message["sources"]`).

This keeps:

* **Replay & caching** concerns (markers + items) distinct from
* **User-facing references** (citations in `sources`).

---

## 7. Interaction with history & regenerate

On regenerate or follow‑up turns:

* `HistoryManager.build_input_from_messages` reconstructs `input` from:

  * User & assistant text.
  * Markers and persisted items in `openai_responses_pipe`.

Citations (`sources`) are **not** part of this reconstruction; they are not fed back into the model directly.

However:

* Tool calls whose outputs contributed to citations (for example, via web search) **may** be persisted as items if you choose to store their `function_call_output` or reasoning items (see `markers_and_persistence.md`).
* The model can still reintroduce URLs through new tool outputs or because the user references them.

---

## 8. Edge cases & robustness

### 8.1 Malformed or missing URLs

If an annotation:

* Has no `url`, or
* Has an empty / whitespace URL,

then:

* Skip citation creation.
* Do not raise exceptions; the streaming loop must remain robust.

### 8.2 Duplicate URLs

If the same URL is annotated multiple times in a single turn:

* It should produce **one** `source` event and one entry in `state.citations`.
* Subsequent occurrences reuse the same ordinal and do not re‑emit the source.

Implementation detail:

* The `seen_urls` map (URL → index) prevents duplicates.

### 8.3 Missing `sources` in `web_search_call`

If `action["sources"]` is missing or empty:

* Still emit “Searching” status if `query` is present.
* Skip the “Reading through {{count}} sites” status.
* Do not treat this as an error; the model may still respond usefully.

### 8.4 Disabled web search

If no `web_search` tool is attached (conditions in §2 not met):

* The model cannot emit `web_search_call` items.
* It can still emit `url_citation` annotations for URLs it knows from training or prior context.
* The engine continues to handle `url_citation` exactly the same way.

---

## 9. Testing guidelines

When writing tests for web search & citations, cover at least:

1. **Tool enablement**

   * `build_web_search_tools` returns a tool only when:

     * `supports("web_search_tool", model_id)` is True.
     * Config and reasoning effort allow it.

   * It sets `search_context_size` correctly.

   * It parses `WEB_SEARCH_USER_LOCATION` when valid, and logs/ignores invalid JSON.

2. **Request shaping**

   * When a web_search tool is present, `"web_search_call.action.sources"` is added to `request.include`.
   * When no web_search tool is present, `request.include` is unchanged.

3. **Engine status events**

   * Simulate a stream with a `web_search_call` item of `action.type = "search"`:

     * Emits a “Searching” status when `query` is present.
     * Emits “Reading through {{count}} sites” when `sources` are present.
     * Does not crash when `sources` is missing or empty.

4. **URL annotations & citations**

   * Simulated `response.output_text.annotation.added` events for multiple URLs:

     * Distinct URLs → multiple `source` events and citations.
     * Duplicate URLs → only one `source` event and one citation stored.

   * Citation payloads have the expected `source`, `document`, and `metadata` shape.

5. **Message persistence**

   * After streaming completes with citations:

     * `Chats.upsert_message_to_chat_by_id_and_message_id(...)` is called with a `sources` list that matches `state.citations`.

6. **No marker interference**

   * Citations do not produce markers.
   * History reconstruction (`HistoryManager.build_input_from_messages`) is unaffected by the presence or absence of `sources` on messages.

---

## 10. Summary

* `domain.web_search` decides **when** and **how** to attach the `web_search` tool to a Responses request, driven by model capabilities and valves (and effective reasoning effort).

* `domain.engine.ResponsesEngine`:

  * Interprets `web_search_call` items → user-friendly status events.
  * Interprets `url_citation` annotations → `source` events and `Citation` objects.

* The OpenWebUI adapter (`openwebui.events` + `pipe.Pipe`) then:

  * Emits these events to the UI.
  * Persists citations as `sources` via `Chats.upsert_message_to_chat_by_id_and_message_id`.

* Web search behavior and citations are designed to be:

  * **Configurable** (via valves & model features).
  * **Non-intrusive** (misconfiguration shouldn’t crash the turn).
  * **Cleanly separated** from marker-based persistence and history replay.

If you change how web search or citations work, update:

1. This doc (`web_search_and_citations.md`),
2. The relevant sections in `responses_engine.md`, `tools_and_extra_tools.md`, and `config_and_valves.md`,
3. Then the code in `domain.web_search`, `domain.engine`, and the OpenWebUI adapter.