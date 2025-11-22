# OpenAI Responses Manifold — Developer Overview

`functions/pipes/openai_responses_manifold/docs/developer_overview.md`

This short guide orients contributors to the **layered architecture** of the OpenAI Responses manifold and shows how a request flows from Open WebUI into the OpenAI Responses API and back.

## Why this manifold exists

Open WebUI imports a single Python file per pipe, but maintaining that monolith directly made it hard to add features like streaming tools, persistence, routing, and reasoning. The manifold keeps the single-file runtime artifact (`openai_responses_manifold.py`) while organizing the source into **clear layers** that are easy to test and extend.

## Layered architecture (source)

```
src/openai_responses_manifold/
  core/          # config + logging + model catalog + markers
  openai_api/    # request/response DTOs + OpenAIResponsesClient
  domain/        # engine orchestration, history, tools, routing
  openwebui/     # Open WebUI adapters (store, events, tools, bridge)
  pipe.py        # Pipe entrypoint loaded by Open WebUI
```

* Pure logic lives in **core** and **domain**, so it can be exercised without Open WebUI imports.
* **openai_api** keeps HTTP and event parsing isolated.
* **openwebui** holds the only Open WebUI–specific code paths.
* `pipe.py` wires the layers together and stays as thin as possible.

## Runtime flow (streaming turn)

1. **Open WebUI ➜ Pipe**
   * Open WebUI calls `Pipe.pipe()` with `body`, `messages`, tool registry data, and an event emitter/caller.
   * `Pipe` merges pipe + user valves, builds the Responses request, and injects Open WebUI–provided tools and filter `extra_tools`.

2. **Bridge ➜ Engine**
   * `openwebui.bridge` converts Completions-style `messages` into Responses `input` using `HistoryManager` to rehydrate hidden items from markers.
   * `ResponsesEngine` streams events from `OpenAIClient`, executes local tools (registry + web_search + MCP), and loops until completion.

3. **Events ➜ UI**
   * Status, `chat:message`, `source`/`citation`, and `chat:completion` events flow back through `OpenWebUIRuntimeEvents`.
   * Inline annotations become citations; session logs can be emitted as end-of-turn sources when enabled.

4. **Persistence**
   * Structured outputs (tool calls/results, reasoning) are persisted via `OpenWebUIHistoryStore` and referenced by **v2 markers** appended to assistant text so later turns can replay the exact history.

## Task path (non-streaming)

When Open WebUI uses the `__task__` model hint, `Pipe` bypasses streaming and calls `OpenAIClient.create()` directly. The engine is still used to normalize requests and aggregate the final text, but events and storage are suppressed.

## Monolith build (for Open WebUI)

* `scripts/build.py` flattens the layered source into `openai_responses_manifold.py` in the repository root.
* It reads modules in dependency order, strips relative imports, and prefixes a manifest docstring sourced from `pyproject.toml`.
* Run `make build` (or `python scripts/build.py`) after tests pass to keep the monolith in sync with the layered source.

## Testing & dev loop

* Run `make install-dev` once per checkout for editable installs with pytest/ruff/mypy.
* Use `make test` during development; `scripts/build.py` runs pytest before bundling by default.
* Scenario tests in `tests/` drive the engine with fake clients and stores, while module-focused tests cover helpers (markers, routing, tools, etc.).

## Legacy directories

* `src_old/` and `tests_old/` contain the legacy monolithic implementation and its tests. They are **reference-only**: do not modify them. All new work belongs under `src/` and `tests/`.
