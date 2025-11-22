# Tools & `extra_tools` Deep Dive

`functions/pipes/openai_responses_manifold/docs/tools_and_extra_tools.md`

This document explains how the OpenAI Responses manifold handles **tools** end‑to‑end:

* Where tools come from (`__tools__`, `body.tools`, `body.extra_tools`, built‑ins).
* How they are **merged** into the final `tools` list sent to the OpenAI Responses API.
* How **strict JSON schema**, **deduplication**, and **local execution** work.
* How **filter‑injected `extra_tools`** behave and how to use them safely.

It is the companion to:

* `manifold_refactor.md` (overall architecture and checklist)
* `config_and_valves.md` (tool‑related configuration)
* `web_search_and_citations.md` (web search tool behavior)
* `responses_engine.md` (how tool calls are executed at runtime)
* `openwebui_integration.md` (how `__tools__` and filters flow into the manifold)

---

## 0. Key invariants (read this first)

These are the promises the tools layer makes:

1. **Single source of “what tools exist” per turn**
   The final OpenAI `tools` array is built exactly once per turn by
   `ToolPolicy.build_responses_tools(...)`. Everything else feeds into it.

2. **Model capability gating**
   If a model does **not** support function calling, `type="function"` tools are **never** attached.

3. **Merge order with last‑write‑wins**
   When two tools have the same identity (same `type` and `name`), the later one in merge order overrides the earlier one.

4. **Strictness is opt‑in at the valve level**
   `ENABLE_STRICT_TOOL_CALLING=True` makes registry tools strict by default,
   but callers can still control `strict` on a per‑tool basis if needed.

5. **Local execution is separate from declaration**
   Having a tool in the OpenAI `tools` list does *not* automatically mean the manifold can execute it locally; that’s controlled by the `ToolExecutor` and `__tools__`.

6. **Filter‑injected `extra_tools` are first‑class**
   `body.extra_tools` are merged side‑by‑side with registry tools and built‑ins, and can override them by identity.

Keep these in mind when editing any of `domain.tools`, `openwebui.tools`, or the bridge.

---

## 1. Three views of a “tool”

There are three layers that talk about “tools”:

1. **Domain‑level view** (`domain.tools`)

   * `ToolDefinition` — internal description of a tool.
   * `ToolRegistry` — where tool definitions come from.
   * `ToolExecutor` — how tool calls are actually run.
   * `ToolPolicy` — how to build the final OpenAI `tools` list.

2. **Open WebUI view** (`openwebui.tools` / `__tools__`)

   ```python
   __tools__ = {
       "weather_lookup": {
           "spec": {...},          # JSON schema, description, name, etc.
           "callable": weather_fn, # Python function or coroutine
       },
       ...
   }
   ```

   * `OpenWebUIToolRegistry` wraps this into `ToolDefinition`s.
   * `OpenWebUIToolExecutor` wraps the callables into a `ToolExecutor`.

3. **OpenAI Responses API view** (request `tools` array)

   ```jsonc
   {
     "type": "function",
     "name": "weather_lookup",
     "description": "Get current weather by city.",
     "parameters": { ... },    // JSON Schema
     "strict": true
   }
   ```

   The model **only** sees this schema and decides when to emit `function_call` items.

The manifold’s job is to keep all three aligned and predictable.

---

## 2. Domain‑level types & responsibilities (`domain.tools`)

### 2.1 `ToolDefinition`

Internal representation of a tool:

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    strict: bool
    source: Literal["registry", "filter", "body", "mcp", "builtin"]
```

* `name`, `description`, `parameters` map directly to OpenAI function tools.
* `strict` indicates whether the tool should be treated as a strict JSON Schema.
* `source` is used for introspection/debugging (e.g. telling where a tool came from).

### 2.2 `ToolRegistry`

Abstract interface for “where tools are defined”:

```python
class ToolRegistry(Protocol):
    def get(self, name: str) -> ToolDefinition | None: ...
    def iter_definitions(self) -> Iterable[ToolDefinition]: ...
```

Domain code never assumes where definitions come from—just that the registry can enumerate them.

### 2.3 `ToolExecutor`

Abstract interface for “how tools are executed”:

```python
class ToolExecutor(Protocol):
    async def execute(self, calls: list[ToolCall]) -> list[ToolResult]: ...
```

The engine uses `ToolExecutor` to run `ToolCall`s (see `responses_engine.md`):

* It doesn’t know or care whether tools are local Python functions, HTTP calls, or something else.

### 2.4 `ToolPolicy`

Encapsulates **all** logic for building the final `tools` list:

```python
class ToolPolicy:
    @staticmethod
    def build_responses_tools(
        model_id: str,
        features: set[str],
        cfg: RuntimeConfig,
        registry: ToolRegistry,
        body_tools: list[dict] | None,
        extra_tools: list[dict] | None,
        mcp_tools: list[dict] | None,
        web_search_tools: list[dict] | None,
    ) -> list[dict]:
        ...
```

This is the **only** place that knows:

* How to merge tools from different sources.
* How strictness is applied.
* How deduplication works.
* Which models actually get which tools.

---

## 3. Open WebUI wrappers (`openwebui.tools`)

### 3.1 `OpenWebUIToolRegistry`

Constructed from `__tools__` supplied by Open WebUI:

* For each entry:

  ```python
  spec = tool_info["spec"]
  definition = ToolDefinition(
      name=spec["name"],
      description=spec.get("description", ""),
      parameters=spec.get("parameters", {"type": "object", "properties": {}}),
      strict=False,             # base value; may later be overridden by cfg
      source="registry",
  )
  ```

* Implements `ToolRegistry` by:

  * `get(name)` → `ToolDefinition` or `None`.
  * `iter_definitions()` → yields all `ToolDefinition`s.

### 3.2 `OpenWebUIToolExecutor`

Executes tool calls via `__tools__` callables:

```python
async def execute(self, calls: list[ToolCall]) -> list[ToolResult]:
    results = []
    for call in calls:
        fn = self._callables.get(call.name)
        if not fn:
            results.append(ToolResult(
                call_id=call.call_id,
                output="Tool not found",
                status="error",
                error_message="Tool not found",
            ))
            continue

        try:
            args = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError as e:
            results.append(ToolResult(
                call_id=call.call_id,
                output=f"Invalid JSON arguments: {e}",
                status="error",
                error_message=str(e),
            ))
            continue

        try:
            if inspect.iscoroutinefunction(fn):
                value = await fn(**args)
            else:
                value = await asyncio.to_thread(fn, **args)
            output = json.dumps(value, default=str)
            results.append(ToolResult(
                call_id=call.call_id,
                output=output,
                status="ok",
                error_message=None,
            ))
        except Exception as e:
            results.append(ToolResult(
                call_id=call.call_id,
                output=f"Tool error: {e}",
                status="error",
                error_message=str(e),
            ))
    return results
```

* Domain code just sees `ToolExecutor`; everything about Python callables lives here.

---

## 4. All the places tools can come from

For a single turn, tools can originate from five places:

1. **Open WebUI registry (`__tools__`) → `OpenWebUIToolRegistry`**

   * Tools defined and registered at the app level.
   * Use `OpenWebUIToolExecutor` for local execution.
   * Source: `"registry"`.

2. **Model‑configured tools (Completions `body.tools`)**

   * Provided by model config or advanced UI options.
   * Already in OpenAI tools format.
   * Extracted by `openwebui.bridge.map_completions_to_responses`.
   * Source: `"body"`.

3. **Filter‑injected tools (`body.extra_tools`)**

   * Added/edited by filters, per chat or per request:

     ```python
     body.setdefault("extra_tools", []).append({
         "type": "function",
         "name": "weather_lookup",
         "description": "Get current weather by city.",
         "parameters": {...},
     })
     ```

   * Already in OpenAI format.

   * Do *not* automatically get Python callables unless you also modify `__tools__`.

   * Source: `"filter"`.

4. **Built‑in web search tools (`domain.web_search`)**

   * Created from `RuntimeConfig` + model capabilities.
   * Source: `"builtin" / "web_search"` (type is `"web_search"`).

5. **Built‑in MCP tools**

   * Derived from `RuntimeConfig.REMOTE_MCP_SERVERS_JSON`.
   * Represent remote MCP servers that the model can call.
   * Source: `"mcp"` (type is usually `"mcp"`).

`ToolPolicy.build_responses_tools` merges all of these into one list.

---

## 5. Capability gating: which tools a model can see

Before merging anything, `ToolPolicy` respects **model capabilities** from `core.model_catalog`:

* If `supports("function_calling", model_id)` is **False**:

  * **Do not include** any `{"type": "function", ...}` tools.
  * You may still include non‑function tools (e.g. `web_search`, `mcp`) if supported.

* If a model doesn’t support `"web_search_tool"`:

  * `domain.web_search.build_web_search_tools` returns `[]`, so no `web_search` tools are attached.

This keeps tools aligned with what the model can actually do, and avoids confusing API errors.

---

## 6. Merge order & deduplication

### 6.1 Merge order

`ToolPolicy.build_responses_tools` collects tools in this order:

1. **Model‑configured tools** (`body_tools`, source `"body"`).
2. **Registry tools** (`ToolRegistry.iter_definitions()`, source `"registry"`).
3. **Filter‑injected tools** (`extra_tools`, source `"filter"`).
4. **MCP tools** (`mcp_tools`, source `"mcp"`).
5. **Web search tools** (`web_search_tools`, source `"builtin"` / `"web_search"`).

This order is **canonical**. If two tools collide by identity, the later one in this list wins.

### 6.2 Identity and dedup semantics

For deduplication, each tool gets a key:

* If `tool["type"] == "function"`:

  ```python
  key = ("function", tool.get("name"))
  ```

* Otherwise (e.g. `web_search`, `mcp`):

  ```python
  key = (tool.get("type"), None)
  ```

Tools are processed in merge order:

* First time we see a key → we keep that tool.
* Next time we see the same key → we **replace** the prior tool.

**Consequences:**

* A filter‑injected function tool with the same name as a registry tool will override it.
* Only one `{"type": "web_search", ...}` tool survives.
* Per‑model or per‑chat tweaks can be introduced by placing a tool later in the order.

---

## 7. Strict tool calling

Strict mode is controlled by:

* `RuntimeConfig.ENABLE_STRICT_TOOL_CALLING` (see `config_and_valves.md`).

When `ENABLE_STRICT_TOOL_CALLING == True`, `ToolPolicy`:

* Applies a **strict JSON Schema transform** to function tools, especially those from the registry:

  * Sets `additionalProperties = False` on object nodes.
  * Makes all existing `properties` required by default.
  * Makes formerly optional fields **nullable** (`"type": ["original_type", "null"]`).

* Ensures `tool["strict"] = True` for these tools (unless a caller explicitly overrides).

When `ENABLE_STRICT_TOOL_CALLING == False`:

* `parameters` are passed through as provided.
* `tool["strict"]` can still be set per tool, but no global strictification is applied.

**Pros:**

* Stronger contracts, fewer hallucinated arguments.
* Clearer tooling errors.

**Cons:**

* Broken/incomplete schemas are surfaced more aggressively (which is usually good, but can require some cleanup).

---

## 8. Local execution vs declaration

The **OpenAI `tools` list** is purely declarative; it does not guarantee the manifold knows how to execute a tool. Execution is governed by the `ToolExecutor`.

### 8.1 Tool calls & results

From `domain.types`:

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

The engine:

1. Collects `ToolCall`s from Responses items of type `function_call`.
2. Calls `tool_executor.execute(tool_calls)`.
3. Converts `ToolResult`s into `function_call_output` items and feeds them back into `request.input` (see `responses_engine.md`).

### 8.2 Local execution via `OpenWebUIToolExecutor`

`OpenWebUIToolExecutor` only knows how to execute tools that have callables in `__tools__`.

**Important:**

* A tool present in `body.extra_tools` **is visible to the model**, but **not executable** unless:

  * It also appears in `__tools__` with a callable, or
  * You provide a custom `ToolExecutor` implementation that knows how to run it.

If the model calls a tool that the executor doesn’t recognize:

* The executor returns `ToolResult(status="error", output="Tool not found")`.
* The engine surfaces this back to the model as `function_call_output`.

---

## 9. Filter‑injected `extra_tools`

Filters can add or modify `body.extra_tools` before the manifold runs.

### 9.1 Expectations for `extra_tools`

* Each `extra_tool` entry should be a **valid OpenAI tool spec**, e.g.:

  ```python
  {
      "type": "function",
      "name": "diagnostics_tool",
      "description": "Internal debug utility.",
      "parameters": {...},
  }
  ```

* The manifold does not rewrite these specs; they are fed to `ToolPolicy` as‑is.

### 9.2 How the manifold treats `extra_tools`

* `openwebui.bridge.map_completions_to_responses` extracts `body.extra_tools` and passes them into `ToolPolicy.build_responses_tools` as `extra_tools`.
* `ToolPolicy`:

  * Appends them after `body_tools` and registry tools.
  * Deduplicates by identity (last wins).

This makes filter‑injected tools **first‑class** citizens:

* They can override registry tools with the same `(type, name)`.
* They only gain local executability if you also register them in `__tools__` or provide a custom `ToolExecutor`.

### 9.3 Good patterns for filters

Use `extra_tools` when you want:

* **Per‑chat or per‑request tools** that shouldn’t be globally available.
* Experimental tools that you may later promote into the registry.
* The ability to **override** existing tools in a narrow context.

If you *also* need local execution:

* Mirror the tool into `__tools__` with a callable under the same `name`.

---

## 10. Config & valves that affect tools

Several valves in `config_and_valves.md` affect tool behavior:

* **`PERSIST_TOOL_RESULTS: bool`**

  * If `True`: tool outputs (and some other items) are persisted via markers (`markers_and_persistence.md`).
  * If `False`: tool outputs are not persisted; regenerate may re‑run tools.

* **`PARALLEL_TOOL_CALLS: bool`**

  * Hints to the model that it can call multiple tools in parallel.
  * The engine may also execute `ToolCall`s concurrently when this is enabled.

* **`MAX_TOOL_CALLS: Optional[int]`**

  * Hard cap on the number of `ToolCall`s per turn.
  * The engine stops looping and emits a status if this limit is exceeded.

* **`MAX_FUNCTION_CALL_LOOPS: int`**

  * Upper bound on how many tool loops the engine performs for a single user message.

* **`ENABLE_STRICT_TOOL_CALLING: bool`**

  * Enables strict JSON Schema enforcement for function tools, as described earlier.

* **`ENABLE_WEB_SEARCH_TOOL`, `WEB_SEARCH_CONTEXT_SIZE`, `WEB_SEARCH_USER_LOCATION`, `REMOTE_MCP_SERVERS_JSON`**

  * Determine whether `web_search` and `mcp` tools are added and how they’re configured.
  * See `web_search_and_citations.md` and `config_and_valves.md` for details.

All of these are read from `RuntimeConfig` at the start of each turn.

---

## 11. Edge cases & testing guidance

### 11.1 Models without function calling

When `supports("function_calling", model_id)` is `False`:

* `ToolPolicy.build_responses_tools` must **exclude** all `type="function"` tools.
* Only non‑function tools (e.g. `web_search`, `mcp`) may be included, if supported.

### 11.2 Malformed registry specs

`OpenWebUIToolRegistry` should:

* Skip entries without a `spec["name"]`.
* Treat missing or non‑dict `parameters` as an empty object schema:

  ```python
  {"type": "object", "properties": {}}
  ```

The presence of one bad registry entry should **not** crash the whole request.

### 11.3 Malformed MCP config

`REMOTE_MCP_SERVERS_JSON` parsing:

* On JSON errors or invalid entries:

  * Log a warning.
  * Skip that entry.
  * Do not fail the chat turn.

### 11.4 Overlapping tools

Test that:

* If a tool is present in both `body_tools` and `extra_tools`, the `extra_tools` version wins.
* If a registry tool and a filter tool share the same `(type, name)`, the filter version wins.
* Only one `web_search` tool exists after deduplication.

### 11.5 Executor behavior

Verify that `OpenWebUIToolExecutor`:

* Runs both sync and async callables.
* Handles JSON decode errors in `arguments_json`.
* Returns `status="error"` with meaningful `error_message` when:

  * Tool not found.
  * The callable raises an exception.

---

## 12. Mental model

You can think of tools flowing through **three stages**:

1. **Definition stage (what tools *could* exist)**
   Registry (`__tools__`), `body.tools`, `body.extra_tools`, MCP, web_search.

2. **Policy stage (what tools the model actually sees)**
   `ToolPolicy.build_responses_tools`:

   * Filters by capabilities.
   * Applies strictness.
   * Merges and deduplicates.

3. **Execution stage (what tool calls actually do)**
   `ResponsesEngine`:

   * Turns `function_call` items into `ToolCall`s.
   * Delegates to `ToolExecutor.execute`.
   * Feeds `ToolResult`s back into the model.
   * Optionally persists tool outputs via markers.

As long as you keep these three stages and their interfaces intact, you can:

* Add new tool sources (e.g. new MCP servers or built‑in tool types).
* Change how tools are merged or strictified.
* Swap the UI integration layer, without touching the core engine’s tool orchestration.