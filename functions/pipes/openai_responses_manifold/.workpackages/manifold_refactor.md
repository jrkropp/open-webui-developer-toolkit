> **Agent instruction:** Keep this work package plan current as you execute WP11. Update statuses on the checklist below and add new items whenever additional work emerges.
>
> ## Work Package Checklist
>
> * [x] WP11.1 – Confirm current source layout and bundling behavior
> * [x] WP11.2 – Create new package folders and `__init__.py` skeletons
> * [x] WP11.3 – Move & refactor *domain* modules (models, IDs, markers, messages, errors)
> * [x] WP11.4 – Move OpenAI protocol types (requests + streaming events + client)
> * [x] WP11.5 – Move infrastructure modules (logging, OpenWebUI events, store)
> * [x] WP11.6 – Move application modules (engine, history, request builder, tools, tasks, routing)
> * [x] WP11.7 – Move and adapt the OpenWebUI `Pipe` adapter
> * [x] WP11.8 – Update all imports and the bundling script (`scripts/build.py`)
> * [x] WP11.9 – Run tests / smoke tests and fix any regressions
> * [x] WP11.10 – Update README / internal docs to explain the new architecture
> * [x] WP11.11 – Add any newly discovered tasks to this checklist and keep statuses updated

---

# WP11 – Refactor OpenAI Responses Manifold Architecture

## 1. Objective

**Goal:** Refactor the OpenAI Responses API “manifold” plugin for Open WebUI into a clearer, more intuitive architecture with explicit layers and a consistent folder structure, *without changing runtime behavior*.

You will:

* Reorganize the existing modular source under `src/openai_responses_manifold/` into clearly named packages.
* Preserve the existing build flow where `scripts/build.py` bundles the modules into a single file for Open WebUI.
* Keep public behavior and the plugin’s external APIs compatible.

The result should make it obvious where to find:

* Domain concepts (model catalog, markers, messages, errors).
* OpenAI protocol definitions (Requests, streaming events, HTTP client).
* Application logic (engine, tools, routing, history, request building).
* Infrastructure (logging, OpenWebUI store and events).
* Adapters (OpenWebUI `Pipe` entry point).

---

## 2. Context (What you are starting from)

The monolithic file you see in Open WebUI is generated. The comment at the top describes the **source layout** (current situation):

* `model_catalog.py`
* `settings.py`
* `utils/logging.py`
* `utils/openwebui_events.py`
* `core/openai_response_events.py`
* `core/openai_requests.py`
* `core/ids.py`
* `core/messages.py`
* `core/markers.py`
* `core/errors.py`
* `main.py`
* `engine.py`
* `services/history.py`
* `services/request_builder.py`
* `services/tools.py`
* `services/tasks.py`
* `services/routing.py`
* `infra/openwebui_store.py`
* `infra/openai_client.py`

Conceptually, these already fall into natural groups:

* **Domain-ish:** model catalog, IDs, messages, markers, errors.
* **OpenAI protocol:** requests & streaming events.
* **Application:** engine, history, request_builder, tools, tasks, routing.
* **Infrastructure:** logging, OpenAI client, OpenWebUI events/store.
* **Adapter:** OpenWebUI `Pipe` (`main.py`).

This work package formalizes that into an explicit, layered architecture.

---

## 3. Target architecture (ideal folder structure)

You will refactor the source tree under `src/openai_responses_manifold/` to the following structure (names are important):

```text
openai_responses_manifold/
  __init__.py

  config/
    settings.py              # PipeValves, UserValves, DEFAULT_PIPE_LOG_LEVEL

  domain/
    model_catalog.py         # OpenAI model IDs, features, aliases AND ID normalization
    messages.py              # user/assistant blocks → Responses items helpers
    markers.py               # hidden marker encoding/decoding/splitting
    errors.py                # ManifoldError, ToolExecutionError, ...

    openai_requests.py       # ResponseCreateParams, CompletionCreateParams, ReasoningParams, ...
    openai_events.py         # Streaming EventType + StreamEvent union + parse_event

  infrastructure/
    logging.py               # session-aware logging, ContextVars, SESSION_LOGS buffer
    openwebui_events.py      # EventEmitter, EventCall, OpenWebUI event payload models
    openwebui_store.py       # ItemStore wrapping open_webui.models.chats.Chats
    openai_client.py         # OpenAIResponsesClient (aiohttp wrapper)

  application/
    engine.py                # ResponsesEngine (streaming orchestration + tool loop)
    history.py               # HistoryPersistence, HistoryBuilder, HistoryService
    request_builder.py       # build_responses_body(...)
    tools.py                 # build_tools(...), execute_tool_calls(...), resolve_tools(...)
    tasks.py                 # run_task_model(...)
    routing.py               # route_auto_model(...), router schema + prompt

  interface/
    openwebui_pipe.py        # Pipe class integrating everything into Open WebUI
```

### Layering rules

* `interface/` may depend on `application`, `config`, `domain`, `infrastructure`.
* `application/` may depend on `domain` and `infrastructure`.
* `infrastructure/` may depend on `domain` (for types) but not on `application` or `interface`.
* `domain/` depends on nothing else inside this package.

These rules are your guide when fixing imports.

---

## 4. High-level plan

You will execute the following steps (mirroring the checklist):

1. Confirm the current modular layout in `src/` and how `scripts/build.py` bundles it.
2. Create the new packages and move modules into their new homes.
3. Merge the model ID logic into a single domain module (`domain/model_catalog.py`) to remove the `model_catalog` ↔ `ids` circularity.
4. Move OpenAI protocol types into `domain/openai_requests.py` and `domain/openai_events.py`.
5. Move infrastructure helpers (logging, events, store, client).
6. Move application logic (engine, history, request builder, tools, tasks, routing).
7. Move the OpenWebUI `Pipe` into `interface/openwebui_pipe.py`.
8. Update all imports and update the bundling script to match the new layout.
9. Run tests / smoke tests and fix any breakage.
10. Update README / comments to reflect the new architecture.

---

## 5. Detailed tasks & guidance

### WP11.1 – Confirm current source layout and bundling behavior

**What to do**

* Locate the actual modular source tree (likely `src/openai_responses_manifold/` or similar).
* Verify that the modules listed in the header comments of the monolith match 1:1 with real files.
* Open and inspect `scripts/build.py` to understand:

  * how modules are discovered/imported,
  * how they are concatenated into the monolith,
  * whether it relies on specific paths or glob patterns.

**Acceptance criteria**

* You have a clear understanding of:

  * where each logical module lives now,
  * how `build.py` expects to find them.
* You add any deviations (if the local layout doesn’t perfectly match the header list) as notes to this work package if needed.

**Status notes**

* Current source layout matches the monolith header list: `model_catalog.py`, `settings.py`, `utils/logging.py`, `utils/openwebui_events.py`, `core/openai_response_events.py`, `core/openai_requests.py`, `core/ids.py`, `core/messages.py`, `core/markers.py`, `core/errors.py`, `main.py`, `engine.py`, `services/history.py`, `services/request_builder.py`, `services/tools.py`, `services/tasks.py`, `services/routing.py`, `infra/openwebui_store.py`, `infra/openai_client.py`.
* `scripts/build.py` drives bundling via `MODULE_ORDER` (list above) and `_validate_module_order` requires every source module to be listed, so the order must be updated when files move or rename.

---

### WP11.2 – Create new package folders and `__init__.py` skeletons

**What to do**

* Under `src/openai_responses_manifold/`, create the directories:

  ```text
  config/
  domain/
  infrastructure/
  application/
  interface/
  ```

* Add `__init__.py` to each (even empty) so they are valid Python packages.

* Ensure the top-level `openai_responses_manifold/__init__.py` continues to exist and exports whatever is currently expected (if anything).

**Acceptance criteria**

* All new directories exist and are importable as packages.
* No runtime behavior has changed yet; only new structure is present.

**Status notes**

* Created `config/`, `domain/`, `infrastructure/`, `application/`, `interface/` under `src/openai_responses_manifold/` with empty `__init__.py` files.

---

### WP11.3 – Move & refactor domain modules

**What to do**

1. **Model catalog + IDs (merge to remove cycles)**

   * Current:

     * `model_catalog.py`
     * `core/ids.py`
   * Target:

     * `domain/model_catalog.py`
   * Inside `domain/model_catalog.py`:

     * Keep:

       * `EMPTY_FEATURES`
       * `MODEL_FEATURES`
       * `MODEL_ALIASES`
       * `alias_defaults`
       * `features`
       * `supports`
     * Also move the ID logic from `core/ids.py`:

       * `_DATE_SUFFIX_RE`
       * `_KNOWN_IDS` (built from `MODEL_FEATURES.keys()` and `MODEL_ALIASES.keys()`)
       * `normalize(model_id: str) -> str`
       * `base_model(model_id: str, alias_lookup: Mapping[str, Mapping[str, str | dict]] | None = None) -> str`
     * Update `alias_defaults` and `features` to use the *local* `normalize` and `base_model` functions.
     * Delete or empty the old `core/ids.py` module once all imports are updated.

2. **Messages**

   * Move `core/messages.py` → `domain/messages.py` as-is.
   * Ensure it still exposes:

     * `normalize_user_blocks`
     * `user_blocks_to_responses_items`
     * `assistant_text_item`
     * `developer_message`.

3. **Markers**

   * Move `core/markers.py` → `domain/markers.py` as-is.

4. **Errors**

   * Move `core/errors.py` → `domain/errors.py` as-is.

5. **OpenAI requests & events**

   * Move `core/openai_requests.py` → `domain/openai_requests.py`.

     * Adjust imports so `ResponseCreateParams` and helpers import `base_model`, `MODEL_ALIASES`, `alias_defaults` from `domain/model_catalog.py`.
   * Move `core/openai_response_events.py` → `domain/openai_events.py`.

**Acceptance criteria**

* No remaining references to `core.ids`, `core.messages`, `core.markers`, `core.errors`, `core.openai_requests`, or `core.openai_response_events`.
* The imports are updated to:

  * `from openai_responses_manifold.domain.model_catalog import ...`
  * `from openai_responses_manifold.domain.messages import ...`
  * `from openai_responses_manifold.domain.markers import ...`
  * `from openai_responses_manifold.domain.errors import ...`
  * `from openai_responses_manifold.domain.openai_requests import ...`
  * `from openai_responses_manifold.domain.openai_events import ...`
* There are no circular imports between domain modules.

**Status notes**

* Domain modules moved under `domain/` and imports updated across package/tests to reference the new paths.
* `model_catalog` now contains normalization helpers from former `core/ids.py` and is the single source for alias/default logic; the old `core/` directory was removed.
* OpenAI request/event definitions now live in `domain/openai_requests.py` and `domain/openai_events.py`.

---

### WP11.4 – Move OpenAI client (protocol IO) into infrastructure

**What to do**

* Move `infra/openai_client.py` → `infrastructure/openai_client.py`.
* Update its imports:

  * Replace references to `..core.openai_response_events` and `..utils.logging` with:

    * `from openai_responses_manifold.domain.openai_events import StreamEvent, parse_event`
    * `from openai_responses_manifold.infrastructure.logging import get_logger, truncate_for_log`

**Acceptance criteria**

* The `OpenAIResponsesClient` class is in `infrastructure/openai_client.py`.
* All modules that previously imported it now use the new path.

**Status notes**

* `infra/openai_client.py` moved to `infrastructure/openai_client.py` with imports updated to use domain events and infrastructure logging.
* Call sites now import `OpenAIResponsesClient` from the `infrastructure` package.

---

### WP11.5 – Move infrastructure modules (logging, OpenWebUI events, store)

**What to do**

1. **Logging**

   * Move `utils/logging.py` → `infrastructure/logging.py`.
   * Ensure it still exposes:

     * `configure_logging`
     * `get_logger`
     * `logging_context`
     * ContextVars (`OWUI_SESSION_ID`, `OWUI_CHAT_ID`, `OWUI_MESSAGE_ID`, `OWUI_USER_ID`)
     * `SESSION_LOGS`, `get_session_logs`, `clear_session_logs`, `consume_session_logs`
     * `truncate_for_log`

2. **OpenWebUI events**

   * Move `utils/openwebui_events.py` → `infrastructure/openwebui_events.py`.

3. **OpenWebUI store**

   * Move `infra/openwebui_store.py` → `infrastructure/openwebui_store.py`.

4. Update all imports throughout the codebase:

   * `from utils.logging` → `from openai_responses_manifold.infrastructure.logging`
   * `from utils.openwebui_events` → `from openai_responses_manifold.infrastructure.openwebui_events`
   * `from infra.openwebui_store` → `from openai_responses_manifold.infrastructure.openwebui_store`

**Acceptance criteria**

* All infrastructure modules live under `infrastructure/`.
* No module imports from the old `utils.*` or `infra.*` paths.

**Status notes**

* Logging, OpenWebUI events, and store modules now live under `infrastructure/` with imports updated accordingly.
* Legacy `utils/` and `infra/` directories were removed after the moves.

---

### WP11.6 – Move application modules (engine, history, request builder, tools, tasks, routing)

**What to do**

1. **Engine**

   * Move `engine.py` → `application/engine.py`.
   * Ensure `ResponsesEngine` imports now use:

     * Domain: `openai_responses_manifold.domain.openai_requests`, `domain.openai_events`, `domain.errors`, `domain.model_catalog`.
     * Infra: `infrastructure.openai_client`, `infrastructure.openwebui_events`, `infrastructure.logging`, `infrastructure.openwebui_store`.

2. **History**

   * Move `services/history.py` → `application/history.py`.
   * Keep `HistoryPersistence`, `HistoryBuilder`, `HistoryService` in this single module (no need to split further unless you want to).

3. **Request builder**

   * Move `services/request_builder.py` → `application/request_builder.py`.
   * Update imports to:

     * `from openai_responses_manifold.domain.openai_requests import ResponseCreateParams`
     * `from openai_responses_manifold.application.history import HistoryService`
     * `from openai_responses_manifold.infrastructure.logging import get_logger`

4. **Tools**

   * Move `services/tools.py` → `application/tools.py`.
   * Ensure it still exports:

     * `resolve_tools`
     * `build_tools`
     * `execute_tool_calls`
   * Update imports to:

     * `from openai_responses_manifold.domain.openai_requests import ResponseCreateParams`
     * `from openai_responses_manifold.domain.errors import ToolExecutionError`
     * `from openai_responses_manifold.domain.model_catalog import supports`
     * `from openai_responses_manifold.infrastructure.logging import get_logger, truncate_for_log`

5. **Tasks**

   * Move `services/tasks.py` → `application/tasks.py`.
   * Ensure it imports `OpenAIResponsesClient` from `infrastructure.openai_client`.

6. **Routing**

   * Move `services/routing.py` → `application/routing.py`.
   * Update imports to:

     * `from openai_responses_manifold.domain.openai_requests import ResponseCreateParams`
     * `from openai_responses_manifold.infrastructure.openai_client import OpenAIResponsesClient`
     * `from openai_responses_manifold.infrastructure.openwebui_events import EventEmitter, EventEmitterFn`
     * `from openai_responses_manifold.infrastructure.logging import get_logger, truncate_for_log`

**Acceptance criteria**

* All `services/*.py` modules have been removed or turned into thin shims that import from `application.*`.
* Application code (engine, history, tools, tasks, routing, request_builder) lives entirely under `application/`.

**Status notes**

* Engine and service modules relocated under `application/` with imports updated to depend on `domain` and `infrastructure`.
* Old `services/` directory removed after moves; tests now import from `application.*`.

---

### WP11.7 – Move and adapt the OpenWebUI `Pipe` adapter

**What to do**

* Move `main.py` → `interface/openwebui_pipe.py`.
* Ensure the `Pipe` class:

  * Imports Valve types from `config/settings.py`:

    * `from openai_responses_manifold.config.settings import PipeValves, UserValves`
  * Imports application and infra components from their new locations:

    * `from openai_responses_manifold.application.engine import ResponsesEngine`
    * `from openai_responses_manifold.application.request_builder import build_responses_body`
    * `from openai_responses_manifold.application.routing import route_auto_model`
    * `from openai_responses_manifold.application.tools import build_tools`
    * `from openai_responses_manifold.domain.model_catalog import supports`
    * `from openai_responses_manifold.infrastructure.openai_client import OpenAIResponsesClient`
    * `from openai_responses_manifold.infrastructure.openwebui_store import ItemStore`
    * `from openai_responses_manifold.infrastructure.openwebui_events import EventCall`
    * `from openai_responses_manifold.infrastructure.logging import get_logger, logging_context`
* Ensure the public surface seen by Open WebUI (class name, attributes like `type`, `id`, `pipe`, `pipes`) remains the same.

**Acceptance criteria**

* There is a single OpenWebUI adapter module: `interface/openwebui_pipe.py`.
* The plugin still registers and behaves correctly in Open WebUI when built and loaded.

**Status notes**

* `main.py` renamed/moved to `interface/openwebui_pipe.py` with imports redirected to `config`, `application`, `domain`, and `infrastructure`.
* Top-level package exports now reference the interface module and new layer paths.

---

### WP11.8 – Update all imports and bundling script

**What to do**

1. **Update imports**

   * Search and replace import paths to match the new layout.
   * Ensure there are no references left to:

     * `core.*`, `utils.*`, `services.*`, `infra.*`, or top-level modules that have been moved.

2. **Update `scripts/build.py`**

   * Adjust any hard-coded module paths, glob patterns, or explicit import lists to:

     * match the new folder structure,
     * preserve the final order of content in the bundled monolith where necessary (if there were any ordering assumptions).
   * Ideally, the bundler should read from `openai_responses_manifold/` and respect its new package layout.

**Acceptance criteria**

* The build script runs successfully and produces a monolithic file equivalent (in behavior) to the current one.
* The monolith header comments can be updated to reflect the new layout (optional, but recommended).

**Status notes**

* Package imports now point to `config`, `domain`, `application`, `infrastructure`, and `interface`; legacy module paths were removed.
* `scripts/build.py` `MODULE_ORDER` updated to the new layout and the bundle regenerated via `python3 scripts/build.py --skip-tests`.

---

### WP11.9 – Run tests / smoke tests

**What to do**

* Run any existing automated tests (if the repository has them).
* If there are no tests, perform a basic smoke test:

  * Build the plugin.
  * Load it into Open WebUI.
  * Verify that:

    * you can select the pipe,
    * simple chat requests work,
    * tool calls still function as before,
    * streaming works,
    * history-based persistence (markers) still works.

**Acceptance criteria**

* No regressions in core functionality are observed.
* Any test failures are either resolved or documented with rationale (and ideally fixed).

**Status notes**

* `python3 -m pytest` passes for the refactored package; bundle rebuild succeeded after tests.

---

### WP11.10 – Update README / internal docs

**What to do**

* Update the plugin’s README (or add a new `ARCHITECTURE.md`) to describe:

  * The new folder structure.
  * The four main layers: `domain`, `application`, `infrastructure`, `interface`.
  * Where to look for:

    * Model catalog & capabilities,
    * OpenAI request/response/event models,
    * Engine & tool execution,
    * History persistence,
    * OpenWebUI integration (Pipe & events),
    * OpenAI HTTP client & logging.
* Update the monolith header comment if needed to point readers to the new source layout.

**Acceptance criteria**

* A new contributor can read the docs and immediately know:

  * “Where is the engine?” → `application/engine.py`
  * “Where do I change model features?” → `domain/model_catalog.py`
  * “Where do I adjust the OpenAI client?” → `infrastructure/openai_client.py`
  * “Where is the OpenWebUI Pipe?” → `interface/openwebui_pipe.py`

**Status notes**

* README, internal AGENTS guide, and Developer Guide updated to describe the new `config/domain/infrastructure/application/interface` layout and module locations.

---

### WP11.11 – Keep this work package / checklist current

As you execute this work package, you must:

* Update the checklist at the top:

  * Change `[ ]` → `[x]` when a task is completed.
  * Add new checklist items if you discover additional necessary work (e.g. WP11.12 for test refactors, WP11.13 for CI updates, etc.).

**Status notes**

* Checklist and notes refreshed through WP11 with no additional follow-up items identified so far.
* If you need to adjust the target architecture based on discoveries (e.g. additional modules or constraints from `build.py`), add a brief note explaining the change and keep the structure description in sync.

---

## 6. Rationale summary (for the agent)

* **Why introduce layers?**
  To make the code easier to navigate and reason about:

  * Domain concepts are centralized.
  * Application orchestration is separated from IO and adapters.
  * Infrastructure (logging, HTTP, storage) is isolated.
  * OpenWebUI-specific glue is confined to `interface/`.

* **Why merge `model_catalog` + `ids` into one domain file?**
  The current design couples them via mutual imports. Merging them into `domain/model_catalog.py` removes this circularity and makes the model ID / capability logic a single, obvious place.

* **Why keep the bundling?**
  Open WebUI expects a single-file pipe. The refactor makes the *source* cleaner while preserving the existing packaging convention.

* **What must not change?**

  * The way Open WebUI instantiates and calls the `Pipe`.
  * Behavior of streaming, tool calls, routes, and history persistence.
  * The logical behavior of the engine and services.

Use this work package as your living plan while performing WP11, and keep the checklist updated as you go.
