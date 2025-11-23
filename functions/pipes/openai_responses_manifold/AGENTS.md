# Agents Guide – OpenAI Responses Manifold

Keep this note open whenever you work in `functions/pipes/openai_responses_manifold/`.

## What this manifold is

- An **Open WebUI function/pipe** that speaks the **OpenAI Responses API** (streaming, tools, reasoning, web search, GPT‑5 routing, etc.).
- Open WebUI imports a **single file**: `openai_responses_manifold.py`.
- That file is **generated**; you should only edit code under `src/openai_responses_manifold/` and then rebuild.

At runtime there are a few clear layers:

- **Config** (`src/openai_responses_manifold/config/`)
  - Valve defaults (`settings.py`).
- **Core** (`src/openai_responses_manifold/core/`)
  - Model catalog/aliases + ID normalization, markers/messages/errors, context-aware logging.
- **Adapters** (`src/openai_responses_manifold/adapters/`)
  - `openai/`: Request/response DTOs, streaming event types + parser, `OpenAIResponsesClient`.
  - `openwebui/`: Event helpers, chat-backed `ItemStore`, request builder, runtime-event bridge, and `Pipe`.
- **Domain** (`src/openai_responses_manifold/domain/`)
  - Manifold orchestration: runtime events protocol, history helpers, tool execution, tasks/routing, and `ResponsesEngine`.

Other important pieces:

- `tests/` – pytest suite that imports modules directly from `src/` (via `tests/conftest.py` stubs) so helpers run against the editable package.
- `cli/openai_responses_manifold_cli/commands/build.py` – the bundler used by the developer CLI to flatten the package into the single file that Open WebUI imports.

## Folder map (current layout)

```
functions/pipes/openai_responses_manifold/
├─ AGENTS.md
├─ pyproject.toml          # packaging + pytest/ruff + Open WebUI manifest metadata
├─ cli/
│  └─ openai_responses_manifold_cli/
│     ├─ main.py                    # CLI entrypoint
│     ├─ utils.py                   # shared path helpers + subprocess runner
│     └─ commands/                  # build/test/lint commands
├─ src/
│  └─ openai_responses_manifold/
│     ├─ __init__.py       # re-exports Pipe, ResponsesEngine, helpers
│     ├─ config/settings.py          # shared Pipe valve definitions/defaults
│     ├─ core/                       # model catalog, markers/messages/errors, logging
│     ├─ adapters/
│     │  ├─ openai/                  # OpenAI DTOs, streaming event types, client
│     │  └─ openwebui/               # Open WebUI events/store, request builder, runtime events, Pipe
│     └─ domain/                     # runtime events protocol, history/tools/tasks/routing, engine
├─ tests/                  # pytest suite (imports package modules via conftest)
└─ openai_responses_manifold.py   # generated artifact (never hand-edit)
```

## How the bundler works

- `cli/openai_responses_manifold_cli/commands/build.py` is the **single source of truth** for bundling:
  - Runs `pytest` by default before bundling.
  - Reads `src/openai_responses_manifold/` in a fixed `MODULE_ORDER`.
  - For each module in that order:
    - Removes `from __future__ import ...`.
    - Strips **relative imports** (`from .something import ...`) and relies on earlier sections in the bundle defining the referenced names.
    - Optionally injects small alias lines for `from .module import name as alias` patterns.
  - Prepends a manifest docstring at the top, which is derived from `pyproject.toml` (see `_render_manifest_docstring`).

Key implications for agents:

- If you add a new module under `src/openai_responses_manifold/`, you **must**:
  - Add it to `MODULE_ORDER` in `cli/openai_responses_manifold_cli/commands/build.py` at the correct place in the dependency order.
  - Use **relative imports** inside the package; the bundler will include the module and strip those imports, but the definitions will already be present in the bundle.
- Never edit `openai_responses_manifold.py` by hand; it will be overwritten by `orm build`.

## Pipe & valves contract

- Open WebUI requires this shape:

  ```python
  class Pipe:
      class Valves(BaseModel): ...
      class UserValves(BaseModel): ...
      async def pipes(...): ...
      async def pipe(...): ...
  ```

- In this manifold:
  - `Pipe.Valves` and `Pipe.UserValves` live in `adapters/openwebui/pipe.py` and **must remain nested** inside `Pipe`.
  - Admin defaults come from `self.valves = self.Valves()`.
  - Per‑user overrides come from `__user__["valves"]`, validated into `Pipe.UserValves`.
  - The merge logic lives in `Pipe._merge_valves(...)`, which produces the effective `valves` object used by `ResponsesEngine` and helpers.
- Do **not** move `Valves` / `UserValves` out of `Pipe`; you can, however, refactor shared behavior into other helpers and keep the nested classes as thin wrappers if needed.

## How tests see the engine and pipe

- `tests/conftest.py`:
  - Installs lightweight stubs for `open_webui` imports (Chats, Models, misc helpers).
  - Prepends `src/` to `sys.path` and imports `openai_responses_manifold` from the package so tests exercise the editable modules.
- Tests then:
  - Use `orm.Pipe` as the Open WebUI adapter.
  - Use `orm.ResponsesEngine` directly for scenario tests (`tests/test_runner_scenarios.py`).
  - Import core helpers from the package (`CompletionCreateParams`, `ResponseCreateParams`, markers, etc.).

When modifying engine behavior:

- Prefer changing `src/openai_responses_manifold/domain/engine.py`, then run:

  ```bash
  cd functions/pipes/openai_responses_manifold
  orm test
  orm build
  ```

- The bundler will pick up `domain/engine.py` (via `MODULE_ORDER`) and regenerate the monolith after tests pass so Open WebUI sees the same behavior.

## Key commands (recap)

- `python -m pip install -e .[dev]` — editable install including the `dev` extra (pytest, ruff, etc.).
- `python -m pip install -e .` — editable install with runtime deps only.
- `orm test` — run the pytest suite (against the package modules via `conftest.py`).
- `orm lint` — run Ruff checks over `src/`, `tests/`, and `cli/`.
- `orm lint --fix` — Ruff with autofix over `src/`, `tests/`, and `cli/`.
- `orm build` — run pytest, then regenerate `openai_responses_manifold.py`.
- `orm build --tests-only` — run pytest without rebuilding.
- `orm build --skip-tests` — rebuild bundle without running tests (only use if tests already passed).

## Notes for agents

- Always treat `openai_responses_manifold.py` as generated; edit the package under `src/openai_responses_manifold/` instead.
- When adding new features:
  - Prefer to put pure logic in `core/`, orchestration in `domain/`, OpenAI/HTTP in `adapters/openai/`, Open WebUI glue in `adapters/openwebui/`, and keep the `Pipe` thin.
  - Update `cli/openai_responses_manifold_cli/commands/build.py` if you introduce new top‑level modules in the package so the bundler stays in sync.
- Keep this guide in sync with structural changes so future agents don’t have to rediscover how the manifold and bundler work. 
