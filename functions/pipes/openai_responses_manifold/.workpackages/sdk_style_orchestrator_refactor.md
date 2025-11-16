> **Workpackage:** Introduce a `ResponsesEngine` abstraction, make `Pipe` a thin Open WebUI adapter, and keep the project feeling like a small OpenAI‑style SDK bundled into a single file.
>
> Goal: document how the manifold is structured, then refactor the “runner” into a clearer `ResponsesEngine` while preserving existing behavior and tests.

## 1. Manifold overview

The **OpenAI Responses Manifold** is an Open WebUI function/pipe that:

- Exposes a single Python file, `openai_responses_manifold.py`, that Open WebUI imports.
- Uses the **OpenAI Responses API** (not Completions) to power:
  - Streaming and non‑streaming chat responses.
  - Function/tool calling and tool result persistence.
  - Optional web search, GPT‑5 routing, and visible reasoning summaries.
- Persists extra “items” (reasoning, tool traces, citations) into Open WebUI’s chat model using hidden markers.

At a high level the runtime looks like:

- **Pipe adapter** (`Pipe` in `src/openai_responses_manifold/pipe.py`):
  - Implements the Open WebUI pipe contract (`type`, `id`, `Valves`, `UserValves`, `pipes()`, `pipe(...)`).
  - Knows about Open WebUI’s request shape (`body`, `__user__`, `__metadata__`, `__tools__`, etc.).
  - Translates these inputs into a `ResponsesBody` and chooses streaming vs non‑streaming vs task‑model calls.
- **Engine / runner** (currently `ResponseRunner` in `pipe.py`):
  - Talks to `OpenAIResponsesClient` (HTTP transport).
  - Drives the Responses loop: streams events, executes tools, retries with tool outputs, emits events back to WebUI.
  - Integrates with persistence helpers to stash extra items into the chat record.
- **Core + features + infra:**
  - `core/` – models (`ResponsesBody`, `CompletionsBody`), capabilities (model table), markers, logging, utilities.
  - `infra/` – `OpenAIResponsesClient` and persistence helpers.
  - `features/` – tool building, GPT‑5 router, and other feature toggles.

Everything under `src/openai_responses_manifold/` is the “real” code; `scripts/build.py` flattens this package back into the single `openai_responses_manifold.py` bundle that Open WebUI imports.

---

## 2. Intent of this work

Today the “engine” type is named `ResponseRunner` and lives alongside `Pipe` inside `pipe.py`. This works, but:

- The name “runner” is vague; “engine” better reflects that it *drives* the Responses workflow.
- `pipe.py` mixes:
  - Open WebUI integration (`Pipe`, valves, metadata glue).
  - Engine implementation (`ResponseRunner` and its methods).
- We want the public surface to **feel like an SDK**:
  - `OpenAIResponsesClient` – low‑level transport.
  - `ResponsesEngine` – high‑level behavior for Responses API calls.
  - `Pipe` – Open WebUI adapter that happens to use the engine.

This workpackage describes how to:

1. Introduce a `ResponsesEngine` abstraction (with a `ResponseRunner` alias for compatibility).
2. Make `Pipe` look and read like a thin adapter that delegates to the engine.
3. Keep bundling and tests working (`make build`, tests that still import `ResponseRunner`).

---

## 3. Target design

Layering inside `src/openai_responses_manifold/`:

- `infra/client.py`
  - Transport layer, analogous to `openai.OpenAI` or `client.responses.stream`.
  - Provides an async API used by the engine (`stream_events`, `request`, etc.).
- `core/`
  - Pydantic models (`CompletionsBody`, `ResponsesBody`), model capability tables, markers, utilities, logging.
  - No direct Open WebUI coupling.
- `features/`
  - Higher‑level helpers: tool building, GPT‑5 router, web search helpers, etc.
- **`ResponsesEngine`** (new name for the runner):
  - Encapsulates the Responses workflow:
    - `async def stream(...) -> str`
    - `async def nonstreaming(...) -> str` (optionally aliased to `create(...)` later).
    - `async def run_task_model(...) -> str`
    - `async def emit_notification(...)`, `emit_error(...)` helpers.
  - Lives in `pipe.py` initially (top of file), but is conceptually the “engine” layer.
- `Pipe`
  - Thin Open WebUI adapter:
    - Owns `Valves` / `UserValves` configuration models.
    - Translates Open WebUI `body`/`__user__`/`__metadata__`/`__tools__` into engine calls.
    - Uses a `ResponsesEngine` instance to actually talk to OpenAI.

We will keep a **backwards‑compatible alias**:

- `ResponseRunner = ResponsesEngine`

so that:

- Existing tests (`test_runner_scenarios.py`) can continue to construct `orm.ResponseRunner(...)` unchanged.
- Any external code using the monolith still works.

---

## 4. Valve contract constraints

Open WebUI has a **hard requirement** on how valves are exposed:

```python
class Pipe:
    class Valves(BaseModel):
        ...

    class UserValves(BaseModel):
        ...
```

It does **not** care where the logic lives, but it **does** expect:

- `Pipe.Valves` and `Pipe.UserValves` to be nested classes.
- Both to inherit from `BaseModel`.
- The field names to remain stable so existing GUI configs still map to attributes.

The current manifold also relies on the following merge pattern:

```python
valves = self._merge_valves(
    self.valves,
    self.UserValves.model_validate(__user__.get("valves", {})),
)
```

This means:

- Admin‑level defaults come from `self.valves` (an instance of `Pipe.Valves`).
- Per‑user overrides come from validating `__user__["valves"]` into `Pipe.UserValves`.
- The merged `valves` object is what the engine and helpers must read from (`valves.LOG_LEVEL`, `valves.TRUNCATION`, etc.).

If you introduce base classes, keep this pattern:

```python
class Pipe:
    class Valves(BasePipeValves):
        """Open WebUI-facing valves model."""
        pass

    class UserValves(BasePipeUserValves):
        """Open WebUI-facing user valves model."""
        pass
```

and always reference `self.Valves` / `self.UserValves` / `valves` in code, **never** the base types directly. That guarantees GUI changes still flow through correctly.

---

## 5. Refactor checkpoints

Work in small, mechanical steps; run `make test` after each block.

### 5.1: Rename the runner class to `ResponsesEngine`

**Goal:** Introduce the `ResponsesEngine` name without moving code across modules.

Steps:

- In `src/openai_responses_manifold/pipe.py`:
  - Rename `class ResponseRunner:` → `class ResponsesEngine:`.
  - At the bottom of the class definition, add:

    ```python
    # Backwards‑compatible alias for tests and callers that still use the old name.
    ResponseRunner = ResponsesEngine
    ```

- Update internal references in the same file from `ResponseRunner` to `ResponsesEngine`, except:
  - Keep the alias name `ResponseRunner` exported for compatibility.
- In `src/openai_responses_manifold/__init__.py`, re‑export both:

  ```python
  from .pipe import EventEmitter, Pipe, ResponsesEngine, ResponseRunner

  __all__ = [
      "EventEmitter",
      "Pipe",
      "ResponsesEngine",
      "ResponseRunner",
      # plus existing core exports…
  ]
  ```

- **Tests:** do not change tests yet; they should still import `orm.ResponseRunner`.

Checkpoint:

- `make test` remains green.
- IDEs and callers can now discover `ResponsesEngine` as the primary engine type.

### 5.2: Make `Pipe` a thin adapter over the engine

**Goal:** Make `pipe.py` read like a standard Open WebUI adapter: configuration + delegation to `ResponsesEngine`.

Steps:

- In `Pipe.__init__`:
  - Replace `self.runner = ResponseRunner(logger=self.logger)` with:

    ```python
    self.engine = ResponsesEngine(logger=self.logger)
    ```

  - Optionally keep a property alias for internal code:

    ```python
    @property
    def runner(self) -> ResponsesEngine:
        # Backwards‑compat shim for older code/tests.
        return self.engine
    ```

- In `Pipe.pipe(...)`:
  - Replace direct calls to `self.runner.stream` / `.nonstreaming` / `.run_task_model` / `.emit_*` with `self.engine.<method>` (or via the `runner` property if you keep it).
- Do **not** move the engine class to another module yet; just ensure the roles are visually separated:
  - Top of file: `ResponsesEngine` (engine).
  - Bottom of file: `Pipe` (adapter) that instantiates and delegates to the engine.

Checkpoint:

- `pipe.py` clearly shows:
  1. `ResponsesEngine` as the core engine.
  2. `Pipe` as a thin integration layer.
- `make test` still passes unchanged.

### 5.3: Optional SDK‑style method naming

**Goal:** Make engine methods feel closer to the OpenAI SDK surface.

Steps (optional, can be a follow‑up PR):

- Consider renaming:
  - `nonstreaming(...)` → `create(...)` (or `create_response(...)`).
  - `run_task_model(...)` → `create_task(...)` (or similar).
  - Keep `stream(...)` as is.
- Inside `Pipe.pipe(...)`, prefer the new names:

  - For streaming chat: `await self.engine.stream(...)`
  - For non‑streaming chat: `await self.engine.create(...)`
  - For task‑model calls: `await self.engine.create_task(...)`

- Keep old method names as thin wrappers for one release:

  ```python
  async def nonstreaming(...):
      return await self.create(...)
  ```

Checkpoint:

- `ResponsesEngine` feels like a small SDK surface, but external callers using the old names still work.

### 5.4: Optional test updates

Once you’re comfortable with the new naming, you can:

- Update `tests/test_runner_scenarios.py` to use `orm.ResponsesEngine` instead of `orm.ResponseRunner`.
- Adjust docstrings to say “engine” instead of “runner”.
- Keep the `ResponseRunner` alias for compatibility with existing deployments.

Checkpoint:

- All tests explicitly reference `ResponsesEngine`, and `ResponseRunner` is purely a backwards‑compatibility shim.

---

## 6. Bundling & verification

After each major checkpoint:

- Run:

  ```bash
  cd functions/pipes/openai_responses_manifold
  make test
  make build
  ```

- This ensures:
  - Tests still pass against the package and the bundled `openai_responses_manifold.py`.
  - The generated single‑file manifold exports both `ResponsesEngine` and `ResponseRunner`, and `Pipe` now clearly acts as a thin adapter over the engine. 
