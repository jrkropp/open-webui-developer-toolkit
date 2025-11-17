# OpenAI Responses Manifold — Developer Guide (v2 design)

> **TL;DR (for humans *and* AI agents)**
>
> * This repo is a **modular OpenWebUI manifold** that adapts OpenWebUI chat requests to the **OpenAI Responses API** with streaming, tools, routing, and persisted rich items.
> * The codebase is split into:
>   **Adapter** (`main.py`) → **Engine** (`engine.py`) → **Core** (pure logic, `core/`) → **Services** (history, tools, routing) → **Infra** (OpenAI HTTP, OpenWebUI store).
> * **Sacred concepts:** Conversation/Turn, Messages vs Context Items, Model Capabilities, Markers + Persistence, Single‑turn Engine Run, Valves (settings).
> * **Model IDs:** We never hard‑code the OpenWebUI Function ID. We **normalize** incoming model IDs (prefix/dot/date safe) before checking capabilities.
> * **Persistence pattern:** Store structured items (tool results, reasoning) in the chat DB, **embed invisible markers** in assistant text, and **resolve them later** to rebuild context.

---

## 1) Project structure (standard, predictable)

```
openai_responses_manifold/
├─ main.py                      # OpenWebUI Pipe (manifold) – entrypoint/adapter
├─ settings.py                  # Valves: pipe & per-user settings (OpenWebUI-facing)
├─ engine.py                    # ResponsesEngine – orchestrates one “turn”
├─ model_catalog.py             # Canonical model/capability table (edit this when adding models)
├─ core/                        # Pure domain logic (no I/O)
│  ├─ __init__.py
│  ├─ api_models.py             # Pydantic: CompletionsBody, ResponsesBody
│  ├─ messages.py               # Message block helpers (text/image/file → items)
│  ├─ capabilities.py           # MODEL_FEATURES, MODEL_ALIASES, supports()
│  ├─ ids.py                    # Model ID normalization (prefix/dot/date safe)
│  ├─ markers.py                # Hidden marker format & parsing (no DB)
│  └─ errors.py                 # Manifold exceptions (Tool, Routing, Stream)
├─ services/                    # Light business logic composed with infra
│  ├─ __init__.py
│  ├─ history.py                # HistoryPersistence (items→markers), HistoryBuilder (markers→items)
│  ├─ tools.py                  # Build OpenAI `tools` & execute tool calls
│  └─ routing.py                # “auto” model routing (e.g., gpt‑5‑auto)
├─ infra/                       # I/O implementations
│  ├─ __init__.py
│  ├─ openai_client.py          # aiohttp client for OpenAI Responses API
│  └─ openwebui_store.py        # ItemStore for OpenWebUI Chats (persist/fetch items)
└─ utils/
   ├─ __init__.py
   ├─ logging.py                # Context-aware logging + per-session buffer for citations
   └─ events.py                 # Event helpers (status/usage/completion/citation)
```

**Subtle naming tweaks to feel “standard”**

* **Engine** (not “runner”): matches common Python service language and reads well to OpenAI API devs (“Responses Engine”).
* **core/** (not “domain”): familiar pattern in many Python libs (pure logic).
* **openai_client.py** method names mirror OpenAI SDK vibes: `.create()` (non‑stream) and `.stream()` (SSE).
* **history.py** hosts **HistoryPersistence** (Flow A: items→markers) and **HistoryBuilder** (Flow B: markers→items) — the two halves of the persistence design.

---

## 2) Core concepts (mental model first)

1. **Conversation → Turn**

   * We process one **turn** at a time: user input → assistant streaming output (with optional tool loops).

2. **Messages vs Context Items**

   * **Messages** (OpenWebUI) are `{role, content}` + hidden **markers** in assistant text.
   * **Context Items** (OpenAI Responses) are structured blocks: `input_text`, `input_image`, `input_file`, `output_text`, `function_call`, `function_call_output`, `reasoning`, `web_search_call`, etc.
   * We consistently transform **messages → context items → messages**.

3. **Model & Capabilities**

   * Canonical model IDs (e.g., `gpt-5`, `gpt-4.1`, `o3`) and **aliases** (e.g., `gpt-5-thinking-high`).
   * Capabilities drive behavior (function calling, reasoning, web search, image tool).
   * The top-level `model_catalog.py` is the single source of truth for supported models — edit it whenever you add or change coverage.

4. **Markers + Persistence**

   * Persist structured items in the OpenWebUI chat store.
   * Embed **invisible markers** in assistant text (stable namespace) pointing to those items.
   * On the next turn, parse markers and **resolve** to reconstruct full context.

5. **Engine Run (single turn)**

   * Build `ResponsesBody` from the current conversation and valves.
   * Stream SSE from OpenAI, handle tool calls, persist items, emit OpenWebUI events, finish with usage + citations + logs.

6. **Valves (settings)**

   * Typed knobs (API endpoint/key, models, web search, reasoning summary, parallel tool calls, logging).

---

## 3) How the parts work together (flow overview)

### A. During streaming (response time)

1. Engine streams SSE events from OpenAI.
2. Emits:

   * `chat:message` on each text delta,
   * `usage` on usage deltas,
   * `status` for UX hints (“Thinking…”, “Running tool…”).
3. When rich **output items** arrive (tool results, reasoning), the engine:

   * calls `HistoryPersistence.persist_items_for_message(...)`,
   * appends the returned **markers** to assistant text (so UI shows a stable message, and we retain structured items).
4. On completion or error, engine emits `chat:completion` + optional citations/logs.

### B. When building the next request (context reconstruction)

1. Engine (or adapter) invokes `HistoryBuilder.build_input_from_messages(messages, resolve_items=...)`.
2. `HistoryBuilder`:

   * scans assistant messages for markers,
   * asks a resolver (wired to the store) to fetch those items by ULID,
   * builds the **full Responses input** list: user/dev blocks + assistant text segments + restored structured items.

---

## 4) Module responsibilities and APIs (with SDK‑like naming)

### `main.py` — OpenWebUI adapter (Pipe)

* **Purpose:** Speak OpenWebUI on one side, Engine on the other.
* **Reads**: `body`, `__user__`, `__metadata__`, `__tools__` (OpenWebUI tool registry).
* **Writes**: Emits OpenWebUI events (`utils.events`).

```python
class Pipe:
    class Valves(PipeValves):
        """Admin-level valve configuration."""

    class UserValves(PipeUserValves):
        """Per-user valve overrides."""

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = get_logger(__name__)
        self.engine = ResponsesEngine(logger=self.logger)

    async def pipes(self) -> list[dict[str, str]]:
        # Return [{"id": "gpt-4.1", "name": "OpenAI: gpt-4.1"}, ...]

    async def pipe(self, body, __user__, __request__, __event_emitter__,
                   __event_call__, __metadata__, __tools__, __task__=None,
                   __task_body__=None):
        # 1) Merge valves (pipe + user)
        # 2) Build CompletionsBody (core.api_models)
        # 3) Use HistoryBuilder to construct Responses input
        # 4) Build tool specs (services.tools)
        # 5) Optionally route auto models (services.routing)
        # 6) Invoke ResponsesEngine(streaming)
        # 7) Return final assistant text or task result
```

> **Note:** We never rely on `self.id` for logic. The effective **Function ID** is the **prefix of `body["model"]`** that OpenWebUI passes. For capabilities we **normalize** the full model id via `core.ids.normalize()` (prefix/dot/date safe).

---

### `settings.py` — Valves (OpenWebUI‑facing settings)

* **PipeValves** (pipe‑level) and **UserValves** (per user).
* Docstrings read cleanly in the Function UI.

```python
class PipeValves(BaseModel):
    BASE_URL: str = "https://api.openai.com/v1"
    API_KEY: str = "sk-xxxxx"
    MODEL_ID: str = "gpt-5, gpt-5-mini, gpt-4.1, o3, gpt-4o"
    ENABLE_WEB_SEARCH_TOOL: bool = False
    REASONING_SUMMARY: Literal["auto","concise","detailed","disabled"] = "disabled"
    PERSIST_REASONING_TOKENS: Literal["response","conversation","disabled"] = "disabled"
    PARALLEL_TOOL_CALLS: bool = True
    ENABLE_STRICT_TOOL_CALLING: bool = True
    TRUNCATION: Literal["auto","disabled"] = "auto"
    LOG_LEVEL: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"] = "INFO"
    # ... WEB_SEARCH_CONTEXT_SIZE, WEB_SEARCH_USER_LOCATION, MCP JSON, etc.

class UserValves(BaseModel):
    LOG_LEVEL: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL","INHERIT"] = "INHERIT"
```

---

### `engine.py` — **ResponsesEngine** (single‑turn orchestration)

* Think “**client.responses.stream**” with extras (tool loops, persistence, UI events).
* Keeps a narrow surface; composes services/infra via dependency injection.

```python
class ResponsesEngine:
    def __init__(self, client, history_persistence, history_builder_factory,
                 tool_service, router, logger):
        ...

    async def run_streaming_turn(
        self,
        completions: core.api_models.CompletionsBody,
        *,
        valves: PipeValves,
        user: dict[str, Any],
        metadata: dict[str, Any],
        event_emitter: Callable[[dict], Awaitable[None]],
        openwebui_tools: dict[str, Any] | None,
    ) -> str:
        """
        1) Build ResponsesBody (messages → items)
        2) Attach tools, route if needed
        3) Stream SSE; emit events; persist items and append markers
        4) Handle tool call loops
        5) Finalize with usage, citations, logs; return assistant text
        """
```

**Event phases (emitted)**

* status: Thinking… / Running tool…
* chat:message: partial assistant text
* usage: token deltas aggregated
* citation: logs or model-provided citations near the end
* chat:completion: final

---

### `core/api_models.py` — Pydantic models (API shapes)

* `CompletionsBody`: mirrors what OpenWebUI already sends today.
* `ResponsesBody`: the OpenAI Responses API payload.
* Optional `@model_validator` to apply defaults for **aliases** (`MODEL_ALIASES`).

### `core/ids.py` — model ID normalization

* Lowercase, strip **OpenAI date suffix** (`-YYYY-MM-DD`), and if the full string is `<prefix>.<suffix>`, only strip the prefix **if the suffix is known** (in `MODEL_FEATURES` or `MODEL_ALIASES`).
  Works with dotted models like `gpt-4.1-2025-11-03`.

### `core/capabilities.py` — model features and aliases

* `MODEL_FEATURES`: canonical model → frozenset of features.
* `MODEL_ALIASES`: alias → `{base_model, params}`.
* `supports(feature, model_id)` always uses `ids.normalize()` then maps to `base_model`.

### `core/messages.py` — message block helpers

* Converts OpenWebUI blocks (`text`, `image_url`, `input_file`) into Responses items.
* No I/O and no DB.

### `core/markers.py` — hidden marker format

* Stable namespace (e.g., `openai_responses:v2`), not tied to Function ID.
* Pure encode/decode/split/parse logic — no DB.

### `core/errors.py` — typed exceptions

* `ToolExecutionError`, `OpenAIStreamError`, `RoutingError`, etc.

---

### `services/history.py` — persistence & reconstruction services

**HistoryPersistence** (Flow A: items → markers)

```python
class HistoryPersistence:
    def __init__(self, store: ItemStore, marker_namespace: str = "openai_responses"):
        ...

    def persist_items_for_message(
        self,
        chat_id: str,
        message_id: str,
        items: list[dict],
        model_id: str,
    ) -> str:
        """
        Save items via store.save_items(...) → [ULIDs]
        Convert each to a marker (core.markers), wrap, and join.
        Return the concatenated marker string to append to assistant text.
        """
```

**HistoryBuilder** (Flow B: messages → full Responses input)

```python
class HistoryBuilder:
    def __init__(self, resolve_items: Callable[[list[str]], dict[str, dict[str, Any]]]):
        ...

    def build_input_from_messages(self, messages: list[dict[str, Any]]) -> list[dict]:
        """
        Scan markers in assistant messages; resolve ULIDs → payloads;
        return a complete list of Responses input items (user/dev/assistant).
        """
```

> The **resolver** is injected so `HistoryBuilder` stays pure and testable. In production it calls the OpenWebUI store; in tests it can just read from a dict.

---

### `services/tools.py` — tools declaration & execution

**Build OpenAI tools** (SDK‑like declarative surface):

```python
def build_tools(
    responses_body,
    valves,
    openwebui_tools: dict[str, Any] | None,
    *,
    features: dict[str, Any] | None = None,
    extra_tools: list[dict] | None = None,
) -> list[dict]:
    """
    - Transform OpenWebUI registry tools → OpenAI {type: "function"} tools
      (strict JSON Schema optional).
    - Attach {type: "web_search"} if supported/enabled (respect reasoning effort).
    - Attach MCP tools if configured.
    - Dedupe by (type, name).
    """
```

**Execute tool calls** (runtime):

```python
async def execute_tool_calls(
    calls: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> list[dict]:
    """
    Decode JSON args, run sync/async callables, map exceptions to strings,
    return list of {type: "function_call_output", call_id, output}.
    """
```

---

### `services/routing.py` — “auto” model routing

```python
async def route_auto_model(
    client,
    valves,
    base_body,
    tools,
    event_emitter=None,
) -> core.api_models.ResponsesBody:
    """
    Call a small helper model to choose final 'model' and 'reasoning.effort'
    for 'auto' variants; merge and annotate as model_router_result.
    """
```

---

### `infra/openai_client.py` — OpenAI Responses client (SDK‑like)

* SDK‑inspired naming: **create** (non‑stream), **stream** (SSE).

```python
class OpenAIResponsesClient:
    async def create(self, body: dict, *, api_key: str, base_url: str) -> dict:
        """POST /responses (non-stream)"""

    async def stream(self, body: dict, *, api_key: str, base_url: str) -> AsyncIterator[dict]:
        """SSE events from POST /responses with Accept: text/event-stream"""
```

> This keeps the call sites readable to OpenAI SDK users:
>
> * `client.create({...})`
> * `async for event in client.stream({...}): ...`

---

### `infra/openwebui_store.py` — ItemStore for chat persistence

```python
class ItemStore:
    def save_items(self, chat_id: str, message_id: str, items: list[dict], model_id: str) -> list[str]:
        """Persist items; return generated ULIDs."""

    def load_items(self, chat_id: str, item_ids: list[str], model_id: str | None = None) -> dict[str, dict]:
        """Return payloads keyed by ULID."""
```

* Uses `open_webui.models.chats.Chats` under a **stable** key (e.g., `"openai_responses_pipe"`).
* **Do not** derive storage names from the Function ID; admin renames won’t break old chats.

---

### `utils/logging.py` — logging helpers

* Standard Python logging configured once with ContextVars for `session_id`, `chat_id`, `message_id`, and `user_id`.
* Console handler writes to stdout; memory handler buffers per-session lines for the final **Logs** citation.
* Helpers: `get_logger()`, `push_logging_context()/pop_logging_context()`, `logging_context()`, and `truncate_for_log()` for safe payload snippets.

### `utils/events.py` — event helpers

* Utility functions that produce correctly shaped OpenWebUI events (`status`, `usage`, `chat:message`, `citation`, `chat:completion`) to keep `engine.py` clean.

---

## 5) Design choices aligned with OpenAI SDK intuition

* **Client naming:** `OpenAIResponsesClient.create()` / `.stream()` mirrors SDK verbs (`openai.responses.create`, streaming SSE).
* **Single‑turn orchestration:** `ResponsesEngine` encapsulates a **turn** similar to how SDK streaming helpers encapsulate response lifecycles — but we add tool loops, persistence, and UI event emission.
* **Tool interface:** declarative **tool specs** (like SDK’s function tools) and a separate **execution** path for tool calls.
* **Model ID handling:** treat the **whole model string** like the SDK does (allowing dots and version suffixes) and normalize **without** hardcoded prefixes.

---

## 6) Conventions & invariants (what keeps this robust)

* **Never** hard‑code the OpenWebUI Function ID in normalization or capabilities.
  Always use `core.ids.normalize(model_id)` (prefix/dot/date safe).
* **Markers**: keep the namespace **stable** (`openai_responses:v2`).
  Do not couple to Function ID, so old chats keep working after GUI renames.
* **Store key**: keep **stable** (e.g., `"openai_responses_pipe"`). If you ever change it, provide a legacy fallback.
* **Capabilities checks**: always go through `core.capabilities.supports(feature, model_id)`.
* **Attach tools** only if the target model supports function calling.
* **Valves** control policy (web search, reasoning summary, parallel tool calls); the engine enforces them consistently.

---

## 7) Extending the system

**Add a model**

1. `core/capabilities.py`: add to `MODEL_FEATURES`; optionally add alias in `MODEL_ALIASES`.
2. Done — engine behavior flows from capability checks.

**Add a tool**

1. Register it in OpenWebUI (so it appears in `__tools__`).
2. Ensure its JSON Schema is valid (strict mode optional).
3. `services.tools.build_tools(...)` picks it up; engine will execute calls via `execute_tool_calls(...)`.

**Persist a new output item**

1. Engine’s output‑item handler: mark it **persistable**.
2. `HistoryPersistence.persist_items_for_message(...)` returns markers.
3. `HistoryBuilder` will restore them on the next turn automatically.

**Route an “auto” variant**

1. Add a router scenario in `services.routing.route_auto_model(...)`.
2. Engine invokes router for `*.gpt-5-auto*` variants before first request.

---

## 8) Testing guidance (fast feedback)

* **core/** unit tests: pure, fast.

  * `ids.py`: normalization of raw/dates/prefixed dotted ids.
  * `markers.py`: encode/decode/split/parse.
  * `api_models.py`: alias defaults merging.
  * `messages.py`: block transforms.

* **services/** tests:

  * `history.HistoryBuilder`: messages with/without markers; resolver returns payloads; output items match expectations.
  * `tools`: function tool specs, web_search gating; execution (sync/async, errors).
  * `routing`: mock client response, merged into `ResponsesBody`.

* **engine** tests:

  * Simulate a small SSE stream; assert event emission sequence, persisted markers appended, and loop termination on no further tool calls.

---

## 9) Why this is intuitive for OpenWebUI users & OpenAI devs

* **OpenWebUI users** see `main.py` (Pipe), `settings.py` (valves), and familiar event names; the rest is conventional Python layering.
* **OpenAI API developers** recognize a **client with `create/stream`**, typed request/response models, function tools, and a lifecycle around a single turn.
* **Python developers** see clear separation of concerns, PEP 8 naming, typed boundaries, and dependency injection for testability.
