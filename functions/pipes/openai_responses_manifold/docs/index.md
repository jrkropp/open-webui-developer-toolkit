# OpenAI Responses Manifold — Documentation Index

**File:** `functions/pipes/openai_responses_manifold/docs/index.md`
**Scope:** Map of all docs for the OpenAI Responses manifold.

This folder documents the **OpenAI Responses API manifold** for Open WebUI.

The manifold replaces the legacy Completions-only flow with a modern, layered design that:

* Uses the **OpenAI Responses API** for all model calls.
* Stays compatible with Open WebUI’s **pipe interface**, **filters**, and **tool registry**.
* Adds robust **persistence**, **history reconstruction**, **tools**, **web search**, **reasoning**, **routing**, and **logging**.

Use this index as the **navigation map** to the rest of the docs.

---

## 1. Canonical design spec

**Single source of truth for architecture and scope**

* `functions/pipes/openai_responses_manifold/.workpackages/manifold_refactor.md`

This workpackage is authoritative for:

* Target architecture and file tree (`core` → `openai_api` → `domain` → `openwebui` → `Pipe`).
* Responsibilities of each layer (engine, history, tools, adapters, etc.).
* Implementation checklist and sequencing.
* High‑level design decisions and non‑negotiable constraints.

If you’re new to this manifold:

> **Read `manifold_refactor.md` first**, then come back here and jump to the deep‑dive doc that matches what you’re editing.

---

## 2. Deep‑dive documents

Each supporting document focuses on one critical part of the manifold. They are meant to be **AI‑ and human‑friendly** references you can rely on while modifying code.

Paths below are relative to
`functions/pipes/openai_responses_manifold/docs/`.

---

### 2.1 Markers & persistence

**File:** `markers_and_persistence.md`

**Focus:**

* Why markers exist and how they keep the UI clean.
* The **marker format** (`[openai_responses:v2:…]: #`) and regex.
* The `openai_responses_pipe` block in `Chats`:

  * `items` map (ULID → payload + metadata).
  * `messages_index` (message → list of item IDs).
* How persistence helpers:

  * Generate ULIDs.
  * Write to `Chats`.
  * Return marker strings to append to assistant text.

**Read this when:**

* You touch anything related to markers or stored items.
* You need to understand **where hidden data lives** and how it’s looked up.
* You’re debugging missing tool / reasoning history on regenerate.

---

### 2.2 History reconstruction

**File:** `history_manager.md`

**Focus:**

* How Open WebUI’s `messages[]` become Responses `input[]`.
* Role / content mapping:

  * `system` → `instructions`.
  * `user` → `role: "user"` + `input_text` / `input_image` / `input_file`.
  * `assistant` → `output_text` **plus decoded markers** (persisted items).
  * `developer` → `role: "developer"`.
* How markers are detected, resolved via the DB, and reinserted into `input`.
* Ordering rules when mixing plain assistant text + interleaved persisted items.

**Read this when:**

* You change how `messages[]` are transformed for Responses.
* You’re implementing or refactoring `HistoryManager` / `transform_messages_to_input`.
* You add new content block types in the UI.

---

### 2.3 Tools & `extra_tools`

**File:** `tools_and_extra_tools.md`

**Focus:**

* All tool sources:

  * Open WebUI registry (`__tools__`).
  * Model‑configured tools.
  * Filter‑injected `body.extra_tools`.
  * Built‑ins (`web_search`, MCP).
* How registry tools are converted into Responses `{"type": "function", ...}` tools.
* **Strict tool calling** and schema strictification (`strict: true`).
* Merge + dedupe behavior so the final `tools` list is predictable.

**Read this when:**

* You modify tool building or merging logic.
* You add new tool types (file search, code interpreter, MCP, etc.).
* You work on filters that inject `extra_tools`.

---

### 2.4 Responses engine & streaming loop

**File:** `responses_engine.md`

**Focus:**

* The core streaming engine (`ResponsesEngine`):

  * Talks to `/responses` via SSE.
  * Parses Responses events.
  * Emits `chat:message`, `status`, `citation` / `source`, and `chat:completion`.
* Multi‑step tool calling:

  * Detect `function_call` items.
  * Execute local tools.
  * Persist outputs + inject markers.
  * Append outputs to `input` and loop.
* Usage accounting & error handling:

  * Merging nested `usage` objects.
  * Handling network/tool errors without leaving the UI in a “stuck streaming” state.

**Read this when:**

* You touch `ResponsesEngine` or streaming logic.
* You’re debugging strange streaming behavior in the UI.
* You’re adding support for new Responses event types.

---

### 2.5 Web search & citations

**File:** `web_search_and_citations.md`

**Focus:**

* How the `web_search` tool is built, enabled, and configured.
* Handling `web_search_call` output items:

  * Status for “Searching…” / “Reading through {{count}} sites”.
  * Using returned sources (URLs) for UX panels.
* Inline citations via `response.output_text.annotation.added` (`url_citation`).
* How citations are normalized, emitted as `source` / `citation` events, and persisted on messages as `sources`.

**Read this when:**

* You tweak web search behavior or related valves.
* You work on citation rendering or source panels.
* You debug missing or incorrect citations on messages.

---

### 2.6 Routing & model catalog

**File:** `routing_and_model_catalog.md`

**Focus:**

* The model catalog (`core.model_catalog`):

  * Base model IDs and feature flags (function calling, reasoning, web_search, etc.).
  * Aliases like `gpt-5-thinking-high` → base models + default params.
* GPT‑5 auto routing:

  * `.gpt-5-auto-dev` router prompt + JSON schema.
  * How the router chooses between `gpt-5.1-chat-latest`, `gpt-5`, `gpt-5-mini`, etc.
  * How model + reasoning effort decisions are surfaced as statuses.

**Read this when:**

* You add or change model aliases / capabilities.
* You modify `.gpt-5-auto*` routing behavior.
* You’re debugging “Why did it choose this model?” behavior.

---

### 2.7 Open WebUI integration

**File:** `openwebui_integration.md`

**Focus:**

* How the manifold’s `Pipe` integrates with Open WebUI:

  * `Pipe.pipes()` and `Pipe.pipe()` behavior.
  * How `__user__`, `__metadata__`, `__tools__`, `__event_emitter__`, and `__event_call__` are used.
* Interactions with:

  * `Chats` (history, metadata, `openai_responses_pipe`, `sources`).
  * `Models` (auto‑enabling native function calling).
* Event semantics:

  * `chat:message`, `chat:completion`, `status`, `citation`, `source`, `notification`.
  * One‑time CSS injection for multi‑line status descriptions.

**Read this when:**

* You debug frontend integration.
* You adjust which events are emitted and when.
* You change how the Pipe reads/writes via `Chats` or `Models`.

---

### 2.8 Config & valves reference

**File:** `config_and_valves.md`

**Focus:**

* All configuration knobs exposed via `Pipe.Valves` / `Pipe.UserValves`:

  * Connection & auth (`BASE_URL`, `API_KEY`).
  * Model selection (`MODEL_ID`).
  * Reasoning & reasoning summary.
  * Tool execution and persistence.
  * Web search.
  * MCP.
  * Truncation and prompt caching.
  * Logging and per‑user overrides.
* Semantics and trade‑offs for each valve:

  * Cost / latency / privacy / UX impact.
  * Recommended defaults.

**Read this when:**

* You operate or tune the manifold in different environments.
* You change defaults or add new valves.
* You need to understand why the manifold is behaving a certain way at runtime.

---

## 3. Suggested reading order

If you’re implementing or refactoring the manifold, this sequence works well:

1. **`manifold_refactor.md`**
   Big picture: architecture, layers, file tree, checklist.

2. **`markers_and_persistence.md`**
   Core mechanism: how hidden items are stored and referenced.

3. **`history_manager.md`**
   Bridge: how `messages[]` become Responses `input`.

4. **`tools_and_extra_tools.md`**
   Tool plumbing: registry, filters, built‑ins, strict mode.

5. **`responses_engine.md`**
   Execution: SSE loop, tool calls, statuses, usage.

6. **`web_search_and_citations.md`**
   Search & citations: web search UX and URL annotations.

7. **`routing_and_model_catalog.md`**
   Model behavior: capabilities, aliases, auto‑routing.

8. **`openwebui_integration.md`**
   Glue: how everything fits inside Open WebUI.

9. **`config_and_valves.md`**
   Operations: valves, tuning, and runtime behavior.

---

## 4. How to use this index (AI agents & humans)

* Treat **`manifold_refactor.md`** as the **authoritative plan** for architecture and sequencing.
* Use **this `index.md`** to quickly choose **which deep‑dive doc** to open for the subsystem you’re touching.
* When you make significant changes:

  1. Update `manifold_refactor.md` if the architecture or invariants change.
  2. Update the relevant deep‑dive doc(s) to match the new behavior.
  3. Then update the code.

This keeps the manifold **composable, understandable, and evolvable** for both humans and AI agents.