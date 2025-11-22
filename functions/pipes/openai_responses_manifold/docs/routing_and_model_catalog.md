# Routing & Model Catalog

`functions/pipes/openai_responses_manifold/docs/routing_and_model_catalog.md`

This document explains how **model IDs, aliases, features, and routing** work in the OpenAI Responses manifold.

It is the single source of truth for:

- How the manifold interprets model IDs coming from Open WebUI.
- How we map **pseudo IDs** (like `gpt-5-thinking-high` or `.gpt-5-auto-dev`) to real OpenAI models.
- How we decide which models support **tools**, **reasoning**, **web_search**, **verbosity**, etc.
- How the **GPT‑5 auto router** chooses a concrete model at runtime.

If you change anything about models or routing, update:

1. This doc,
2. `src/openai_responses_manifold/core/model_catalog.py`, and
3. `src/openai_responses_manifold/domain/routing.py`.

You may also need to touch:

- `config_and_valves.md` (for `MODEL_ID` examples),
- `openwebui_integration.md` (for how Open WebUI model IDs flow into the manifold).

---

## 1. Responsibilities & mental model

The **model catalog + routing** layer should:

1. Provide a **central place** to understand model capabilities and aliases.
2. Hide naming quirks (prefixes, date suffixes, pseudo IDs) behind a small, stable API.
3. Let other parts of the system ask simple questions:

   - “Does this model support tools?”
   - “Does this alias imply `reasoning.effort = high`?”
   - “Should I attach a `web_search` tool?”
   - “Should I run the GPT‑5 router, and if so what did it decide?”

4. Keep GPT‑5 auto routing **explicit and debuggable** (user can see which model was chosen and why).

Think of the flow like this:

```text
Open WebUI model id (e.g. "openai_responses.gpt-5.1-thinking-high")
  ↓
core.model_catalog.normalize / base_model / alias_defaults
  ↓
ResponsesRequest.model (base model) + overlays (reasoning.effort, etc.)
  ↓
domain.routing.route_auto_model (for .gpt-5-auto* pseudo models)
  ↓
Final model & reasoning config used by ResponsesEngine + tools layer
````

---

## 2. Model catalog (`core.model_catalog`)

The catalog lives in:

```text
src/openai_responses_manifold/core/model_catalog.py
```

Internally it maintains:

* A map of **base models** → capability flags (`_SPECS`).
* A map of **aliases / pseudo IDs** → base model + default params (`_ALIASES`).
* Simple helpers so the rest of the system doesn’t care about how IDs are spelled.

You can implement this as a class (`ModelCatalog`) or as module-level functions; the **public interface** below must remain stable.

### 2.1 Public API

The module exports these helpers:

```python
def normalize(model_id: str) -> str: ...
def base_model(model_id: str) -> str: ...
def alias_defaults(model_id: str) -> dict: ...
def features(model_id: str) -> set[str]: ...
def supports(feature: str, model_id: str) -> bool: ...
```

**Semantics:**

* `normalize(model_id) -> str`

  * Strip the manifold prefix (`"openai_responses."`),
  * Strip trailing date suffixes (`-YYYY-MM-DD`),
  * Lowercase the result.

  Examples:

  ```python
  normalize("openai_responses.gpt-5.1-chat-latest") == "gpt-5.1-chat-latest"
  normalize("openai_responses.gpt-5.1-2025-05-20") == "gpt-5.1"
  normalize("gpt-5-ThInKiNg-High") == "gpt-5-thinking-high"
  ```

* `base_model(model_id) -> str`

  * Use `normalize(model_id)` to look up:

    * If it appears in `_ALIASES`, return that alias’s `base_model`.
    * Else, return the normalized ID itself.

  Example:

  ```python
  base_model("gpt-5-thinking-high") == "gpt-5"
  base_model("openai_responses.gpt-5.1-chat-latest") == "gpt-5.1-chat-latest"
  ```

* `alias_defaults(model_id) -> dict`

  * If the normalized ID is present in `_ALIASES`, return its `params` dict (or `{}`).
  * Otherwise return `{}`.
  * This dict is meant to be **deep-merged on top of** a `ResponsesRequest` (see §4).

* `features(model_id) -> set[str]`

  * Resolve to a base model via `base_model(model_id)`, then read that base model’s features from `_SPECS`.
  * If unknown, return `set()`.

* `supports(feature, model_id) -> bool`

  * Convenience helper: `feature in features(model_id)`.

All other components (tools, routing, engine, web_search) rely on this API rather than hard-coding model names.

---

### 2.2 Normalization rules (details)

Implementation sketch:

```python
_PREFIX = "openai_responses."
_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")

def normalize(model_id: str) -> str:
    m = (model_id or "").strip()
    if m.startswith(_PREFIX):
        m = m[len(_PREFIX):]
    m = _DATE_RE.sub("", m)
    return m.lower()
```

**Invariants:**

* Different spellings / prefixes of the same logical model should normalize to one string.
* `_SPECS` and `_ALIASES` are keyed by the **normalized** string.

---

### 2.3 Base model specs (`_SPECS`)

`_SPECS` maps **canonical base model IDs** → capability flags.

Example sketch (**not authoritative**; update to match what you actually expose):

```python
_SPECS = {
    "gpt-5.1-chat-latest": {
        "features": {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "verbosity",
        },
    },
    "gpt-5": {
        "features": {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "verbosity",
        },
    },
    "gpt-5-mini": {
        "features": {
            "function_calling",
            "reasoning",
            "reasoning_summary",
            "web_search_tool",
            "verbosity",
        },
    },
    "gpt-4o": {
        "features": {
            "function_calling",
            "web_search_tool",
        },
    },
    "chatgpt-4o-latest": {
        "features": set(),  # chat-optimized; this manifold doesn’t expose tools for it by default
    },
    # ... add more base models here ...
}
```

> **Rule of thumb:**
> Add every base model you expose via `MODEL_ID` to `_SPECS` with its *true* capabilities. Everything else (tools, reasoning summaries, web_search, routing) should use `supports(feature, model_id)`.

---

### 2.4 Alias specs (`_ALIASES`)

Aliases provide human-friendly or behaviorful IDs (often used in `MODEL_ID`) that expand to:

* A **base model** in `_SPECS`, and
* Optional default parameters (`params`) to overlay on a `ResponsesRequest`.

Example:

```python
_ALIASES = {
    # Reasoning-flavored GPT‑5:
    "gpt-5-thinking": {
        "base_model": "gpt-5",
    },
    "gpt-5-thinking-high": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "high"}},
    },
    "gpt-5-thinking-minimal": {
        "base_model": "gpt-5",
        "params": {"reasoning": {"effort": "minimal"}},
    },

    # Reasoning-flavored GPT‑5 Mini:
    "gpt-5-thinking-mini": {
        "base_model": "gpt-5-mini",
    },
    "gpt-5-thinking-mini-high": {
        "base_model": "gpt-5-mini",
        "params": {"reasoning": {"effort": "high"}},
    },

    # Back-compat alias example:
    "o4-mini-high": {
        "base_model": "o4-mini",
        "params": {"reasoning": {"effort": "high"}},
    },

    # You can also add 5.1-style aliases if you want:
    # "gpt-5.1-thinking-high": { "base_model": "gpt-5.1-chat-latest", "params": {...} },
}
```

`alias_defaults(model_id)` simply returns `params` for the normalized alias (or `{}`).

---

## 3. Capability flags

We standardize on a small set of **feature flags**. `features(model_id)` returns a set containing some of:

| Feature                 | Meaning in this manifold                                                                |
| ----------------------- | --------------------------------------------------------------------------------------- |
| `function_calling`      | Model supports OpenAI tool/function calling (we only send `tools` when this is `True`). |
| `reasoning`             | Model can emit reasoning traces / encrypted reasoning tokens.                           |
| `reasoning_summary`     | Model can emit a short visible summary of its reasoning.                                |
| `web_search_tool`       | Model supports OpenAI’s `web_search` tool.                                              |
| `code_interpreter_tool` | Model supports a code‑interpreter tool type (placeholder; implement when needed).       |
| `deep_research`         | Model is a deep‑research style model (if you wire those in).                            |
| `verbosity`             | Model supports `text.verbosity` (“add details”, “more concise” regenerate shortcuts).   |

Everywhere else in the code, prefer:

```python
if model_catalog.supports("function_calling", request.model):
    request.tools = tools

if model_catalog.supports("reasoning_summary", request.model) and cfg.REASONING_SUMMARY != "disabled":
    (request.reasoning or {}).update(summary=cfg.REASONING_SUMMARY)
```

instead of matching on explicit model names.

---

## 4. `MODEL_ID`, Open WebUI model IDs, and the catalog

### 4.1 `MODEL_ID` valve → models exposed to the UI

`Pipe.Valves.MODEL_ID` (see `config_and_valves.md`) is a comma‑separated list of **logical model IDs**:

```text
"gpt-5.1-chat-latest, gpt-5.1-thinking, gpt-5.1-thinking-high"
```

`Pipe.pipes()` splits these and exposes them to Open WebUI. The frontend will then refer to them as:

```text
openai_responses.gpt-5.1-chat-latest
openai_responses.gpt-5.1-thinking
...
```

That full ID comes back as `__metadata__["model"]["id"]` and is also stored on chats.

### 4.2 How the catalog sees them

Whenever the manifold wants to reason about a model, it passes the full ID through `core.model_catalog`:

```python
owui_model_id = __metadata__["model"]["id"]          # e.g. "openai_responses.gpt-5.1-thinking"
base = model_catalog.base_model(owui_model_id)       # e.g. "gpt-5.1-chat-latest" or "gpt-5"
feats = model_catalog.features(owui_model_id)        # features(base)
```

So other layers can simply call:

* `features(ctx.model_id)` and
* `supports("function_calling", ctx.model_id)`,

without caring whether `MODEL_ID` used aliases, dated names, or bare base models.

---

## 5. How `ResponsesRequest` uses the model catalog

The OpenAI request model lives in:

```text
src/openai_responses_manifold/openai_api/types.py
```

and is called `ResponsesRequest`.

It includes a post‑validation hook that:

1. Applies alias resolution (`base_model`),
2. Overlays alias-implied defaults (`alias_defaults`) onto the request.

Conceptually:

```python
@model_validator(mode="after")
def _apply_model_alias_defaults(self) -> "ResponsesRequest":
    original = self.model or ""
    base = model_catalog.base_model(original)
    defaults = model_catalog.alias_defaults(original) or {}

    # No alias mapping? nothing to do.
    if base == original and not defaults:
        return self

    data = self.model_dump(exclude_none=False)
    data["model"] = base

    # Deep merge alias params over the current data
    data = deep_overlay(data, defaults)  # alias_defaults → data

    for k, v in data.items():
        setattr(self, k, v)
    return self
```

**Result:**

* The caller (or Open WebUI) can set `model="gpt-5-thinking-high"` or `model="openai_responses.gpt-5-thinking-high"`.
* `ResponsesRequest` sends `model="gpt-5"` to the API.
* If the alias implies `{"reasoning": {"effort": "high"}}`, that gets merged in, unless the caller already explicitly set `reasoning.effort`.

This validator is the **only place** alias defaults are applied; everything else sees a request whose `model` is already a base model plus any derived reasoning params.

---

## 6. GPT‑5 auto routing (`domain.routing`)

Some Open WebUI models are **router** pseudo-models rather than concrete ones:

* `openai_responses.gpt-5-auto-dev`
* `openai_responses.gpt-5-auto`

These are handled by the routing layer in:

```text
src/openai_responses_manifold/domain/routing.py
```

### 6.1 Public helper

From the workpackage:

```python
async def route_auto_model(
    client: OpenAIClient,
    request: ResponsesRequest,
    ctx: TurnContext,
    tools: list[dict],
    events: RuntimeEvents,
) -> ResponsesRequest:
    ...
```

**Responsibilities:**

* Detect when routing is needed based on `ctx.metadata["owui_model_id"]`.
* Call a small **router model** via the Responses API (for `*.gpt-5-auto-dev`).
* Update `request.model` and `request.reasoning` based on the router output.
* Attach a `model_router_result` field to `request` that the engine can later turn into a status.
* Emit a status explaining the routing decision.

### 6.2 When routing runs

Recommended behavior:

* If `owui_model_id.endswith(".gpt-5-auto-dev")`:

  * Run the full router (see §6.3).
* If `owui_model_id.endswith(".gpt-5-auto")`:

  * For now, treat it as a simple alias to a concrete chat model:

    ```python
    request.model = "gpt-5.1-chat-latest"  # or "gpt-5-chat-latest"
    await events.notification(
        "Model router coming soon — using gpt‑5.1‑chat‑latest for now.",
        level="info",
    )
    ```

  * This gives you a stable default while allowing you to later upgrade `.gpt-5-auto` to use the router logic.

Router behavior is **optional**; if it fails, routing should degrade gracefully to the original chosen model.

### 6.3 Router request for `.gpt-5-auto-dev`

The router itself is a separate Responses call, typically using a **fast model** like `gpt-5-mini`:

```python
router_request = ResponsesRequest(
    model="gpt-5-mini",
    input=request.input,   # reuse the same input the main model will see
    instructions="You are a routing assistant ...",  # see below
    reasoning={"effort": "minimal"},
    text={
        "format": {
            "type": "json_schema",
            "name": "gpt5_router",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "enum": ["gpt-5.1-chat-latest", "gpt-5", "gpt-5-mini"],
                    },
                    "reasoning_effort": {
                        "type": "string",
                        "enum": ["minimal", "low", "medium", "high"],
                    },
                    "explanation": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 500,
                    },
                },
                "required": ["model", "reasoning_effort", "explanation"],
                "additionalProperties": False,
            },
            "verbosity": "medium",
        },
    },
)
```

**Router instructions** (high‑level intent; exact wording is up to you):

* Describe available target models:

  * `gpt-5.1-chat-latest` — fast / normal reasoning.
  * `gpt-5` — full reasoning, more expensive.
  * `gpt-5-mini` — cheaper, good for simple tool tasks and short answers.

* Give routing guidelines, e.g.:

  * Prefer `gpt-5.1-chat-latest` for normal chat, Q&A, editing.
  * Use `gpt-5` for complex, multi-step reasoning or heavy tool use.
  * Use `gpt-5-mini` for simple tool-heavy tasks or quick responses.

* Require output **only** in the JSON format specified by `text.format.schema`.

The router call is **non‑streaming**:

```python
router_response = await client.create_response(
    router_request,
    base_url=ctx.runtime_config.BASE_URL,
    api_key=ctx.runtime_config.API_KEY,
)
```

### 6.4 Applying the router decision

Once you have `router_response`:

1. Extract the JSON string from the last message item:

   ```python
   text = ""
   for item in reversed(router_response.get("output", [])):
       if item.get("type") != "message":
           continue
       for block in item.get("content", []):
           if block.get("type") == "output_text":
               text = block.get("text", "")
               break
       if text:
           break
   ```

2. Parse JSON robustly:

   ```python
   decision = {}
   try:
       decision = json.loads(text)
   except json.JSONDecodeError:
       start, end = text.find("{"), text.rfind("}")
       if start != -1 and end != -1 and end > start:
           try:
               decision = json.loads(text[start:end+1])
           except json.JSONDecodeError:
               decision = {}
   ```

3. If `decision` looks valid:

   ```python
   model = decision.get("model")
   effort = decision.get("reasoning_effort")
   explanation = decision.get("explanation")

   if model and effort and explanation:
       request.model = model

       # Only apply reasoning.effort if the target supports reasoning
       if model_catalog.supports("reasoning", model):
           reasoning = dict(request.reasoning or {})
           reasoning["effort"] = effort
           request.reasoning = reasoning

       # Attach router result for UX
       request.model_router_result = {
           "model": model,
           "reasoning_effort": effort,
           "explanation": explanation,
       }
   ```

4. Emit a **status** so the user can see what happened:

   ```python
   if getattr(request, "model_router_result", None):
       r = request.model_router_result
       await events.status(
           f"Routing to {r['model']} (effort: {r['reasoning_effort']})\n"
           f"Explanation: {r['explanation']}"
       )
   ```

5. If anything fails (router error, bad JSON, missing fields):

   * Log a warning.
   * Leave `request.model` and `request.reasoning` unchanged.
   * Do **not** crash the turn.

### 6.5 Engine integration

`ResponsesEngine.run_streaming_turn` can look at `request.model_router_result` (if present) and emit a status near the beginning of the turn. The routing helper can either:

* Emit the status itself (as shown above), or
* Attach `model_router_result` and let the engine decide exactly when/how to present it.

In either case, routing should only ever touch:

* `request.model`,
* `request.reasoning.effort`,
* `request.model_router_result` (for UX).

It must **not** modify `request.input` or `request.tools`.

---

## 7. Date-suffixed model IDs

OpenAI sometimes versions models as `gpt-5.1-2025-06-01` or similar.

We treat dated IDs as aliases of a base model:

* `normalize("gpt-5.1-2025-06-01") == "gpt-5.1"`
* `_SPECS` and `_ALIASES` are keyed by the undated ID (`"gpt-5.1"` or `"gpt-5.1-chat-latest"`, depending on how you define them).

If you ever need version-specific behavior:

* You may inspect the **raw** `ResponsesRequest.model` *before* normalization,
* But keep that logic localized and documented.
* The default behavior should treat all dated variants of the same base as functionally equivalent from the standpoint of features and routing.

---

## 8. Adding or changing models / aliases

When you add or change models:

1. **Update `_SPECS`** with the base model and its capabilities.

   ```python
   _SPECS["gpt-6"] = {
       "features": {
           "function_calling",
           "reasoning",
           "reasoning_summary",
           "web_search_tool",
           "verbosity",
       },
   }
   ```

2. **Update `_ALIASES`** with any friendly IDs or “flavors” you want to expose via `MODEL_ID`.

   ```python
   _ALIASES["gpt-6-thinking-high"] = {
       "base_model": "gpt-6",
       "params": {"reasoning": {"effort": "high"}},
   }
   ```

3. **Expose aliases via `MODEL_ID`** in `Pipe.Valves` (see `config_and_valves.md`):

   ```text
   MODEL_ID = "gpt-5.1-chat-latest, gpt-5.1-thinking, gpt-5.1-thinking-high, gpt-6-thinking-high"
   ```

4. **Re-run tests** that depend on:

   * `normalize`, `base_model`, `features`, `supports`,
   * Routing (if the new model participates in auto routing),
   * Tool behavior (if capabilities changed, e.g., added `web_search_tool`).

5. **Document anything unusual**:

   * If a model should always use web search or deep research,
   * If it doesn’t support tools even though it looks like a tool-capable family member.

---

## 9. Edge cases & testing checklist

When you modify `core.model_catalog` or `domain.routing`, tests should cover:

### 9.1 Normalization

* Prefix + date handling:

  ```python
  assert normalize("openai_responses.gpt-5.1-2025-05-20") == "gpt-5.1"
  assert normalize("gpt-5-ThInKiNg-High") == "gpt-5-thinking-high"
  ```

* Ensure new naming schemes don’t break existing normalization.

### 9.2 Alias resolution

* `base_model("gpt-5-thinking-high") == "gpt-5"`.
* `alias_defaults("gpt-5-thinking-high")` returns `{"reasoning": {"effort": "high"}}`.
* Explicit user overrides win over alias defaults:

  * If user sets `reasoning.effort="minimal"`, alias defaults should not overwrite it.

### 9.3 Feature checks

* Models that don’t support `function_calling` cause tools to be omitted in `ToolPolicy.build_responses_tools`.
* Models without `reasoning_summary` never get `request.reasoning.summary` set, even if the valve asks for it.
* Models without `web_search_tool` never get a `web_search` tool added.

### 9.4 Router happy path

For `.gpt-5-auto-dev`:

* Simulate a router response like:

  ```json
  {"model": "gpt-5-mini", "reasoning_effort": "low", "explanation": "Simple tool task"}
  ```

* Assert:

  * `request.model == "gpt-5-mini"`,
  * `request.reasoning.effort == "low"` if `supports("reasoning", "gpt-5-mini")`,
  * `request.model_router_result` is set,
  * A status mentioning the chosen model and explanation is emitted.

### 9.5 Router error paths

* Router returns malformed JSON:

  * We keep the original `request.model`,
  * Do not set `model_router_result`,
  * Do not crash.

* Network / HTTP error:

  * Same behavior: log and proceed with original model.

### 9.6 Backwards compatibility

* Old chats with dated IDs (`gpt-5.1-2025-xx-yy`) keep working because:

  * Normalization strips the date,
  * `_SPECS` has entries for the undated base.

---

By keeping **all model & routing semantics in this layer**, the rest of the manifold can treat `request.model` as a black box and just ask:

* “What capabilities does this model have?”
* “Does this alias imply any defaults?”
* “Do I need to route this pseudo model to a concrete one first?”

If you change how models behave, **update this doc first**, then adjust `core.model_catalog` and `domain.routing` to match.