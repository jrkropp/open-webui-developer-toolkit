# Agents Guide – OpenAI Responses Manifold

Keep this note open whenever you work in `functions/pipes/openai_responses_manifold/`.

## What this manifold is

- An **Open WebUI function/pipe** that speaks the **OpenAI Responses API** (streaming, tools, reasoning, web search, GPT‑5 routing, etc.).
- Open WebUI imports a **single file**: `openai_responses_manifold.py`.
- That file is **generated**; you should only edit code under `src/openai_responses_manifold/` and then rebuild.

At runtime there are a few clear layers:

- **Core** (`src/openai_responses_manifold/core/`)
  - Pure helpers: IDs, capabilities, Pydantic API models, markers, and message transforms.
- **Services** (`src/openai_responses_manifold/services/`)
  - History (builder + persistence), tools (build/execute), routing.
- **Infra** (`src/openai_responses_manifold/infra/`)
  - Talks to OpenAI (`OpenAIResponsesClient`) and OpenWebUI (`ItemStore`).
- **Utils** (`src/openai_responses_manifold/utils/`)
  - `SessionLogger` plus event helpers.
- **Engine** (`src/openai_responses_manifold/engine.py`)
  - `ResponsesEngine` orchestrates streaming, tool loops, persistence, and Open WebUI events.
- **Adapter** (`src/openai_responses_manifold/main.py`)
  - `Pipe` with nested `Valves` / `UserValves`; it builds `ResponsesBody`, routes auto models, and delegates to the engine.

Other important pieces:

- `tests/` – pytest suite that imports modules directly from `src/` (via `tests/conftest.py` stubs) so helpers run against the editable package.
- `scripts/build.py` – the bundler that flattens the package into the single file that Open WebUI imports.

## Folder map (current layout)

```
functions/pipes/openai_responses_manifold/
├─ AGENTS.md
├─ pyproject.toml          # packaging + pytest/ruff + Open WebUI manifest metadata
├─ Makefile                # dev shortcuts (install/test/lint/format/build/clean)
├─ scripts/
│  └─ build.py             # pytest + bundler entrypoint
├─ src/
│  └─ openai_responses_manifold/
│     ├─ __init__.py       # re-exports Pipe, ResponsesEngine, core helpers
│     ├─ model_catalog.py  # canonical place to add/modify supported models
│     ├─ core/             # ids, capabilities, API models, markers, message helpers
│     ├─ engine.py         # ResponsesEngine + EventEmitter
│     ├─ services/         # history, tools, routing
│     ├─ infra/            # OpenAIResponsesClient + ItemStore
│     ├─ utils/            # SessionLogger + event helpers
│     ├─ settings.py       # shared Pipe valve definitions/defaults
│     └─ main.py           # Pipe + nested Valves/UserValves (Open WebUI adapter)
├─ tests/                  # pytest suite (imports package modules via conftest)
└─ openai_responses_manifold.py   # generated artifact (never hand-edit)
```

## How the bundler works

- `scripts/build.py` is the **single source of truth** for bundling:
  - Runs `pytest` by default before bundling.
  - Reads `src/openai_responses_manifold/` in a fixed `MODULE_ORDER`:

  - For each module in that order:
    - Removes `from __future__ import ...`.
    - Strips **relative imports** (`from .something import ...`) and relies on earlier sections in the bundle defining the referenced names.
    - Optionally injects small alias lines for `from .module import name as alias` patterns.
  - Prepends a manifest docstring at the top, which is derived from `pyproject.toml` (see `_render_manifest_docstring`).

Key implications for agents:

- If you add a new module under `src/openai_responses_manifold/`, you **must**:
  - Add it to `MODULE_ORDER` in `scripts/build.py` at the correct place in the dependency order.
  - Use **relative imports** inside the package; the bundler will include the module and strip those imports, but the definitions will already be present in the bundle.
- Never edit `openai_responses_manifold.py` by hand; it will be overwritten by `make build`.

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
  - `Pipe.Valves` and `Pipe.UserValves` live in `main.py` and **must remain nested** inside `Pipe`.
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
  - Import core helpers from the package (`CompletionsBody`, `ResponsesBody`, markers, etc.).

When modifying engine behavior:

- Prefer changing `src/openai_responses_manifold/engine.py`, then run:

  ```bash
  cd functions/pipes/openai_responses_manifold
  make test
  make build
  ```

- The bundler will pick up `engine.py` (via `MODULE_ORDER`) and regenerate the monolith after tests pass so Open WebUI sees the same behavior.

## Key commands (recap)

- `make install` — editable install with runtime deps only.
- `make install-dev` — editable install including the `dev` extra (pytest, ruff, etc.).
- `make test` — run the pytest suite (against the package modules via `conftest.py`).
- `make lint` — run Ruff checks over `src/` and `tests/`.
- `make lint-fix` — Ruff with autofix over `src/` and `tests/`.
- `make format` — apply Ruff formatting fixes.
- `make build` — run pytest, then regenerate `openai_responses_manifold.py`.
- `python scripts/build.py --tests-only` — run pytest without rebuilding.
- `python scripts/build.py --skip-tests` — rebuild bundle without running tests (only use if tests already passed).

## Notes for agents

- Always treat `openai_responses_manifold.py` as generated; edit the package under `src/openai_responses_manifold/` instead.
- When adding new features:
  - Prefer to put pure logic in `core/`, shared orchestration in `services/`, infra-specific calls in `infra/`, and keep `main.Pipe` thin.
  - Update `scripts/build.py` if you introduce new top‑level modules in the package so the bundler stays in sync.
- Keep this guide in sync with structural changes so future agents don’t have to rediscover how the manifold and bundler work. 
