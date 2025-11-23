# OpenAI Responses Manifold — Config & Valves Reference

**File:** `functions/pipes/openai_responses_manifold/docs/config_and_valves.md`
**Scope:** All configuration knobs (valves) that control the manifold’s behavior.

This document explains:

* What each valve does.
* How it affects cost, latency, privacy, and UX.
* How **pipe‑level** and **per‑user** valves interact.
* How the manifold uses these values internally via `RuntimeConfig`.

It is the **single source of truth** for the configuration surface of the OpenAI Responses manifold.

Use this together with:

* `openwebui_integration.md` (how valves are used in `Pipe`)
* `routing_and_model_catalog.md` (model behavior)
* `tools_and_extra_tools.md` (tool behavior)
* `web_search_and_citations.md` (web search behavior)
* `responses_engine.md` (engine behavior)
* `markers_and_persistence.md` (what “persistence” means)

---

## 1. Configuration model overview

The configuration types live in:

```text
src/openai_responses_manifold/core/config.py
```

The manifold exposes **three layers of configuration state**:

1. **Pipe‑level valves (`PipeValves`)**

   * Defined in `core.config.PipeValves`.
   * Re‑exposed as `Pipe.Valves` on the Open WebUI `Pipe` class.
   * Shared defaults for all users of this pipe.

2. **User valves (`UserValves`)**

   * Defined in `core.config.UserValves`.
   * Re‑exposed as `Pipe.UserValves`.
   * Per‑user overrides, stored under `__user__["valves"]`.

3. **Runtime configuration (`RuntimeConfig`)**

   * Defined in `core.config.RuntimeConfig`.
   * The **effective** config for a single turn, produced by merging pipe valves and user valves.
   * This is what the engine and adapters actually consume (via `TurnContext.runtime_config`).

### 1.1 Pipe‑level valves (`PipeValves` / `Pipe.Valves`)

Conceptually:

```python
class PipeValves(BaseModel):
    # Connection & auth
    BASE_URL: str
    API_KEY: str

    # Models
    MODEL_ID: str  # Comma-separated list of logical model ids

    # Reasoning & summaries
    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"]
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"]

    # Tools / execution
    PERSIST_TOOL_RESULTS: bool
    PARALLEL_TOOL_CALLS: bool
    ENABLE_STRICT_TOOL_CALLING: bool
    MAX_TOOL_CALLS: Optional[int]
    MAX_FUNCTION_CALL_LOOPS: int

    # Web search
    ENABLE_WEB_SEARCH_TOOL: bool
    WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None]
    WEB_SEARCH_USER_LOCATION: Optional[str]
    WEB_SEARCH_ALLOWED_DOMAINS: Optional[str]
    WEB_SEARCH_EXTERNAL_WEB_ACCESS: bool
    WEB_SEARCH_INCLUDE_SOURCES: bool

    # Built-in tools
    ENABLE_CODE_INTERPRETER_TOOL: bool
    CODE_INTERPRETER_CONTAINER_JSON: Optional[str]

    # Integrations
    REMOTE_MCP_SERVERS_JSON: Optional[str]

    # Truncation & context management
    TRUNCATION: Literal["auto", "disabled"]

    # Privacy & caching
    PROMPT_CACHE_KEY: Literal["id", "email"]

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
```

`Pipe.Valves` on the Open WebUI `Pipe` class subclasses or wraps `PipeValves` directly. Typical defaults are wired from env vars, but this doc is the source of truth for **meaning**, not specific default values.

### 1.2 User valves (`UserValves` / `Pipe.UserValves`)

Per‑user overrides (currently just logging):

```python
class UserValves(BaseModel):
    LOG_LEVEL: Literal[
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"
    ] = "INHERIT"
```

* When `LOG_LEVEL == "INHERIT"` (case‑insensitive), the user inherits the pipe‑level `LOG_LEVEL`.
* Otherwise the user’s chosen level is used for that user’s sessions only.

User valves are stored under `__user__["valves"]` and passed into the pipe by Open WebUI.

### 1.3 Runtime configuration (`RuntimeConfig`) & merging

`RuntimeConfig` represents the **effective config** for a single request/turn:

```python
class RuntimeConfig(BaseModel):
    # Same fields as PipeValves (plus any derived/aux fields if needed)
    BASE_URL: str
    API_KEY: str
    MODEL_ID: str
    REASONING_SUMMARY: Literal["auto", "concise", "detailed", "disabled"]
    PERSIST_REASONING_TOKENS: Literal["response", "conversation", "disabled"]
    PERSIST_TOOL_RESULTS: bool
    PARALLEL_TOOL_CALLS: bool
    ENABLE_STRICT_TOOL_CALLING: bool
    MAX_TOOL_CALLS: Optional[int]
    MAX_FUNCTION_CALL_LOOPS: int
    ENABLE_WEB_SEARCH_TOOL: bool
    WEB_SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None]
    WEB_SEARCH_USER_LOCATION: Optional[str]
    WEB_SEARCH_ALLOWED_DOMAINS: Optional[str]
    WEB_SEARCH_EXTERNAL_WEB_ACCESS: bool
    WEB_SEARCH_INCLUDE_SOURCES: bool
    ENABLE_CODE_INTERPRETER_TOOL: bool
    CODE_INTERPRETER_CONTAINER_JSON: Optional[str]
    REMOTE_MCP_SERVERS_JSON: Optional[str]
    TRUNCATION: Literal["auto", "disabled"]
    PROMPT_CACHE_KEY: Literal["id", "email"]
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
```

Merging is handled by `merge_valves`:

```python
def merge_valves(pipe_valves: PipeValves, user_valves: UserValves) -> RuntimeConfig:
    """
    - Start from pipe_valves.
    - Overlay any user_valves fields that are not "INHERIT".
    - Return a RuntimeConfig instance.
    """
```

> **Key invariant**
> During a request, the manifold **never** reads raw environment variables directly.
> It always uses the merged `RuntimeConfig` returned by `merge_valves`, accessed via `TurnContext.runtime_config`.

### 1.4 How valves flow through the system

1. Open WebUI instantiates `Pipe` and its `Pipe.Valves` once (process‑wide).

2. On each request:

   * The pipe reads `__user__["valves"]` into `Pipe.UserValves`.
   * Calls `merge_valves` → `RuntimeConfig`.
   * Builds a `TurnContext` with `ctx.runtime_config = RuntimeConfig`.

3. The rest of the system (`openwebui.bridge`, `domain.engine`, `domain.web_search`, etc.) reads **only** from `TurnContext.runtime_config`, never from env variables or `Pipe.Valves` directly.

> `MODEL_ID` in `RuntimeConfig` is used only for **pipe configuration & listing** (see §3). The *per‑turn* chosen model is taken from `__metadata__["model"]["id"]` and fed through the model catalog (`routing_and_model_catalog.md`).

---

## 2. Connection & auth

### 2.1 `BASE_URL`

**Type:** `str`
**Default:** Typically `https://api.openai.com/v1` (or a proxy/gateway value).

**What it does**

* Base URL for the OpenAI Responses API.
* The manifold calls `POST {BASE_URL}/responses` for all model requests.

**Typical values**

* Official OpenAI:

  * `https://api.openai.com/v1`
* Proxy / gateway:

  * `https://my-proxy.internal/openai/v1`

**Notes**

* Trailing slash is trimmed; you don’t need to worry about including it.
* Must be reachable from the Open WebUI server.

---

### 2.2 `API_KEY`

**Type:** `str`
**Default:** Typically wired from `OPENAI_API_KEY` or similar env var.

**What it does**

* API key used for `Authorization: Bearer <API_KEY>` on all `/responses` calls.

**Important**

* If invalid or left as a placeholder:

  * Requests will fail with 401/403.
  * The engine emits error events and the UI shows a failure message.

---

## 3. Models & routing

### 3.1 `MODEL_ID`

**Type:** `str` (comma‑separated list)
**Example:**

```text
"gpt-5.1-chat-latest, gpt-5.1-thinking, gpt-5.1-thinking-high, gpt-5.1-thinking-minimal"
```

**What it does**

* Controls **which logical models appear** in Open WebUI for this manifold.
* Each comma‑separated token becomes a separate model entry, e.g.:

  * `openai_responses.gpt-5.1-chat-latest`
  * `openai_responses.gpt-5.1-thinking`
  * etc.

The model that the user actually runs is chosen in the UI and passed back as `__metadata__["model"]["id"]`. The pipeline then normalizes that id via the model catalog (`routing_and_model_catalog.md`).

`MODEL_ID` is **configuration‑time** only: it determines the list `Pipe.pipes()` advertises. It does **not** override the user’s per‑turn selection.

**How it’s used**

* `Pipe.pipes()` splits `MODEL_ID` on commas and trims whitespace.
* Each value is passed through the model catalog:

  * Aliases like `gpt-5-thinking-high` map to a base model plus default params (e.g. `reasoning.effort = "high"`).

**Tips**

* You can expose both “fast” and “thinking” variants:

  ```text
  gpt-5-chat-latest, gpt-5, gpt-5-thinking, gpt-5-thinking-high
  ```

* You can also define routing pseudo‑models (e.g. `.gpt-5-auto-dev`) that the routing layer interprets specially (see `routing_and_model_catalog.md`).

---

## 4. Reasoning & summaries

### 4.1 `REASONING_SUMMARY`

**Type:** `"auto" | "concise" | "detailed" | "disabled"`
**Default:** `"disabled"`

**What it does**

Controls **visible reasoning summaries** from models that support them.

When enabled and supported, the manifold sets:

```python
request.reasoning = (request.reasoning or {})
request.reasoning["summary"] = REASONING_SUMMARY
```

The engine then listens for `response.reasoning_summary_text.done` events and emits multi‑line status messages (“Thinking…”, explanation) in the UI.

**Modes**

* `"disabled"`
  Do not request reasoning summaries, even if the model supports them.

* `"auto"`
  Let the model choose summary detail.

* `"concise"`
  Ask for shorter, tighter summaries.

* `"detailed"`
  Ask for more verbose, explanatory summaries.

**Notes**

* Only has effect when `model_catalog.supports("reasoning_summary", model_id)` is `True`.
* Reasoning summaries are **visible** status text, not hidden markers.

---

### 4.2 `PERSIST_REASONING_TOKENS`

**Type:** `"response" | "conversation" | "disabled"`
**Default:** `"disabled"`

**What it does**

Controls whether the manifold requests **encrypted reasoning tokens** and how they are persisted.

1. **`"disabled"`**

   * The manifold does **not** add `"reasoning.encrypted_content"` to `include`.
   * Encrypted reasoning is not requested or stored.

2. **`"response"`**

   * The manifold ensures:

     ```python
     request.include = list(request.include or [])
     request.include.append("reasoning.encrypted_content")
     ```

   * Models send encrypted reasoning for the **current** response.

   * The engine can use it within this turn (e.g., across multiple tool loops).

   * Reasoning items are **not** persisted across turns.

3. **`"conversation"`**

   * Same `include` behavior as `"response"`, plus:

     * Reasoning output items are **persisted** via the marker + DB layout (`markers_and_persistence.md`).
     * Markers are appended to the assistant message.
     * `HistoryManager` can rehydrate these items in future turns, enabling cross‑turn reasoning continuity.

**Tradeoffs**

* `"disabled"`: cheapest; no reasoning state persisted.
* `"response"`: slightly more expensive; best for single‑turn multi‑tool runs.
* `"conversation"`: most expensive; best for long, deep sessions where reasoning continuity matters.

---

## 5. Tools & execution behavior

### 5.1 `PERSIST_TOOL_RESULTS`

**Type:** `bool`
**Default:** `True`

**What it does**

Controls whether tool call outputs (and some other structured items) are **stored** in the chat DB and **reused** in future turns.

When `True`:

* The engine:

  * Persists each `function_call_output` (and selected other items) using the persistence layer (`markers_and_persistence.md`).
  * Injects invisible markers into assistant text.

* On regenerate / follow‑up:

  * `HistoryManager` rehydrates these items from markers.
  * Tool calls are **not** re‑run; this saves cost and latency.

When `False`:

* Tool outputs are **not** persisted.
* Future turns cannot reuse previous tool results automatically.
* Regenerate may trigger fresh tool calls.

**Recommended**

* Leave `True` unless you have strong persistence or privacy constraints.

---

### 5.2 `PARALLEL_TOOL_CALLS`

**Type:** `bool`
**Default:** `True`

**What it does**

Controls whether the model is allowed to call multiple tools **in parallel** within a single tool loop.

* Wired into `request.parallel_tool_calls` when supported.
* The engine may also use `asyncio.gather` to execute tool calls concurrently.

**Behavior**

* `True`:

  * Independent tools run concurrently; best for multiple network lookups, etc.

* `False`:

  * The model is instructed to use tools serially; and the engine may execute them sequentially for stricter ordering.

**Caveats**

* Some backends/proxies may limit concurrency regardless of this flag.
* Your tool implementations must be safe for parallel execution.

---

### 5.3 `ENABLE_STRICT_TOOL_CALLING`

**Type:** `bool`
**Default:** `True`

**What it does**

When `True`, Open WebUI registry tools (`__tools__`) are converted to **strict JSON Schema** before being sent to OpenAI:

* `additionalProperties = False` on objects.
* All properties become **required** by default.
* Fields that were previously optional are made **nullable** (type includes `"null"`).

When `False`, original schemas are passed through unchanged.

**Pros**

* Better validation and fewer hallucinated parameters.
* Clearer contracts between model and tools.

**Cons**

* Can surface sloppy or invalid schemas more aggressively.
* Some tools may need minor schema fixes to work under strict mode.

See `tools_and_extra_tools.md` for strictification details.

---

### 5.4 `MAX_TOOL_CALLS`

**Type:** `Optional[int]`
**Default:** `None` (no explicit cap)

**What it does**

Optional **hard cap** on the number of individual tool calls permitted **within a single turn**.

* If set:

  * The request may include a corresponding field (e.g. `max_tool_calls`) when supported.
  * The engine enforces that total tool calls across all loops do not exceed this number and will stop looping once the cap is reached.

**Use cases**

* Guardrails against runaway tool loops (e.g. bad prompts or tool failures).
* Cost control in high‑risk environments.

---

### 5.5 `MAX_FUNCTION_CALL_LOOPS`

**Type:** `int`
**Default:** `10`

**What it does**

Upper bound on how many **tool loops** the engine will perform for a single request.

Each loop:

1. Streams model output (which may include `function_call` items).
2. Executes requested tools.
3. Appends tool outputs to `input`.
4. Calls the model again.

When the loop count reaches `MAX_FUNCTION_CALL_LOOPS`:

* The engine stops requesting more completions.
* Emits a final status and completion.
* The response may be partial if the model wanted additional loops.

**Tip**

* `10` is usually safe; lower it for more conservative environments.
* This works together with `MAX_TOOL_CALLS` to bound total tool usage per turn.

---

## 6. Web search configuration

### 6.1 `ENABLE_WEB_SEARCH_TOOL`

**Type:** `bool`
**Default:** `False`

**What it does**

Enables the built‑in `web_search` tool when the model supports it.

It is only used when **all** of the following are true:

1. `model_catalog.supports("web_search_tool", model_id)` is `True`.

2. Either:

   * `ENABLE_WEB_SEARCH_TOOL` is `True`, **or**
   * A per‑model feature flag says web search is desired (e.g. via model metadata).

3. Reasoning effort is **not** `"minimal"` (for reasoning‑capable models); we don’t attach web search for minimal‑effort reasoning runs.

**Effects**

* The tool layer adds a `{"type": "web_search", ...}` tool to the request.
* The model can emit `web_search_call` items when it needs external information.
* Status events like “Searching” and “Reading through {{count}} sites” are shown in the UI.
* Source URLs can be rendered as a dedicated “Sources” panel (see `web_search_and_citations.md`).

---

### 6.2 `WEB_SEARCH_CONTEXT_SIZE`

**Type:** `"low" | "medium" | "high" | None`
**Default:** `"medium"`

**What it does**

Controls the `search_context_size` parameter on the `web_search` tool:

* `"low"`: Fastest, cheapest, shallowest context.
* `"medium"`: Balanced default.
* `"high"`: Deep context (slower and more expensive).
* `None`: Let the backend choose a default.

Only used when a `web_search` tool is actually present on the request.

---

### 6.3 `WEB_SEARCH_USER_LOCATION`

**Type:** `Optional[str]` (JSON‑encoded)
**Default:** `None`

**What it does**

If provided, parsed as JSON and attached to the `web_search` tool as `user_location`.

Example JSON value:

```json
{
  "type": "approximate",
  "country": "US",
  "city": "San Francisco",
  "region": "CA"
}
```

Behavior:

* On each request, the adapter tries:

  ```python
  web_search_tool["user_location"] = json.loads(WEB_SEARCH_USER_LOCATION)
  ```

* If parsing fails:

  * Logs a warning.
  * Proceeds without `user_location`.

**Notes**

* This can influence search results (localized context).
* Be mindful of privacy requirements when setting it.

---

## 7. Integrations

### 7.1 `REMOTE_MCP_SERVERS_JSON`

**Type:** `Optional[str]` (JSON‑encoded)
**Default:** `None`

**What it does**

Configures one or more **remote MCP servers** to expose as tools.

Supported formats:

* Single JSON object, or
* JSON array of objects.

Each object should include:

* `server_label` (string)
* `server_url` (string)

Optional keys:

* `require_approval`
* `allowed_tools`
* `headers`

Example:

```json
[
  {
    "server_label": "deepwiki",
    "server_url": "https://mcp.deepwiki.com/mcp",
    "require_approval": "never",
    "allowed_tools": ["ask_question"]
  }
]
```

Behavior:

* On each request, the tools layer parses the JSON and turns valid entries into `{"type": "mcp", ...}` tools.
* Invalid entries are skipped with a warning; the main request should not fail because of a bad MCP config.

**Note**

* MCP configuration is global for the pipe; slow or unreliable MCP servers affect all chats that use this manifold.

---

## 8. Truncation & context management

### 8.1 `TRUNCATION`

**Type:** `"auto" | "disabled"`
**Default:** `"auto"`

**What it does**

Controls how the Responses API handles conversations that exceed the model’s context window.

* `"auto"`:

  * Let OpenAI truncate older content (usually from the middle) to fit the context window.
  * Most forgiving and easiest operationally.

* `"disabled"`:

  * No automatic truncation.
  * Over‑long inputs will cause API errors (e.g. 400).
  * You must manage context yourself (e.g. summarization / manual truncation).

**Recommendation**

* Use `"auto"` unless you have a strong reason to fully control truncation.

---

## 9. Privacy & caching

### 9.1 `PROMPT_CACHE_KEY`

**Type:** `"id" | "email"`
**Default:** `"id"`

**What it does**

Controls which user identifier is sent to OpenAI in the `user` field of the request.

Options:

* `"id"`:

  * Use Open WebUI’s internal user ID (opaque / non‑PII).
  * Good balance between caching and privacy.

* `"email"`:

  * Use the user’s email address (`__user__["email"]`).
  * May be useful for certain auditing or provider‑side analytics, but has stronger privacy implications.

**Why it matters**

* The `user` field may be used for:

  * Abuse detection.
  * Request grouping and response caching.

* Do not send more identifying information than you’re comfortable with.

The choice is applied in `openwebui.bridge.build_turn_context` when setting `ResponsesRequest.user`.

---

## 10. Logging & diagnostics

### 10.1 `LOG_LEVEL` (pipe‑level)

**Type:** `"DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"`
**Default:** Often `"INFO"` (or wired from a global env var).

**What it does**

* Sets the default log level inside `RuntimeConfig.LOG_LEVEL` for all users who haven’t overridden it.
* Controls:

  * What gets printed to stdout/logs.
  * What gets buffered in `SessionLogger` for potential citation output.

Higher verbosity:

* `DEBUG`: very detailed (requests, events, routing decisions).
* `INFO`: operationally useful but not noisy.
* `WARNING` / `ERROR` / `CRITICAL`: mostly silent unless something goes wrong.

---

### 10.2 `UserValves.LOG_LEVEL` (per‑user)

**Type:** `"DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL" | "INHERIT"`
**Default:** `"INHERIT"`

**What it does**

* Allows a **per‑user override** of `RuntimeConfig.LOG_LEVEL`.

Behavior:

* If `LOG_LEVEL == "INHERIT"`:

  * The user inherits `PipeValves.LOG_LEVEL`.

* Otherwise:

  * `RuntimeConfig.LOG_LEVEL` is set to the user’s chosen level for that turn.

**How logs surface**

* During a run:

  * Logs are captured in memory in `SessionLogger.logs[session_id]` (see `core.logging`).

* At the end of a run (or on error):

  * The manifold may emit a `citation` event containing joined log lines (source `"Logs"` or `"Error Logs"`).
  * This is useful for debugging individual turns.

**Example**

* Global: `LOG_LEVEL = "WARNING"`.
* Power user: sets `UserValves.LOG_LEVEL = "DEBUG"` in their profile.

Result:

* Most users see minimal logs.
* The power user sees detailed logs (and potentially log citations) for their own sessions.

---

## 11. Summary & recommended defaults

A good starting configuration for most deployments:

**Connection & models**

* `BASE_URL = "https://api.openai.com/v1"`
* `API_KEY = "<your real key>"`
* `MODEL_ID = "gpt-5.1-chat-latest, gpt-5.1-thinking, gpt-5.1-thinking-high"`

**Reasoning**

* `REASONING_SUMMARY = "disabled"` (or `"auto"` if you like visible thinking)
* `PERSIST_REASONING_TOKENS = "response"`

**Tools**

* `PERSIST_TOOL_RESULTS = True`
* `PARALLEL_TOOL_CALLS = True`
* `ENABLE_STRICT_TOOL_CALLING = True`
* `MAX_TOOL_CALLS = None`
* `MAX_FUNCTION_CALL_LOOPS = 10`

**Web search**

* `ENABLE_WEB_SEARCH_TOOL = False` (turn on when you’re ready)
* `WEB_SEARCH_CONTEXT_SIZE = "medium"`
* `WEB_SEARCH_USER_LOCATION = None` (or a minimal approximate location if desired)

**Integrations**

* `REMOTE_MCP_SERVERS_JSON = None` (add later as needed)

**Context**

* `TRUNCATION = "auto"`

**Privacy & caching**

* `PROMPT_CACHE_KEY = "id"`

**Logging**

* `LOG_LEVEL = "INFO"`
* Users can override via `UserValves.LOG_LEVEL = "DEBUG"` if needed.

These defaults give you:

* Strong compatibility with the legacy manifold.
* Reasonable performance and cost.
* Room to selectively enable advanced features (web search, MCP, deep reasoning) as you need them.
