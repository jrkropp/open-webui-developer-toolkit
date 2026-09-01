# OpenAI Responses Manifold — Agent Context Entry Point

> **Start here.** This file is the single entry point for AI agents and developers
> working on this pipe. Attach only this file for context; follow the links below
> when (and only when) you need deeper detail.

## What this is

`openai_responses_manifold.py` is a single-file Open WebUI **manifold pipe** (function id
`openai_responses`, hardcoded) that translates Open WebUI's Completions-style request
bodies into **OpenAI Responses API** calls. It adds native function calling, reasoning
summaries, encrypted-reasoning persistence, web search with citations, remote MCP tools,
usage/cost reporting, and pseudo-model aliases (e.g. `gpt-5.6-sol-high`).

Everything ships in one file because Open WebUI functions are imported as standalone
modules. Tests live in `tests/` and can import the module directly.

## Documentation map

| File | Read when you need… |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The full developer reference: code map, request flow, valve table, model registry, marker/persistence format, streaming event handling, tool building. **Read this before non-trivial changes.** |
| [DESIGN.md](DESIGN.md) | The *why* behind design decisions (currently: `extra_tools` filter-injection contract). |
| [README.md](README.md) | User-facing docs: setup, feature matrix, model tables, GPT-5.6 notes. |
| [CHANGELOG.md](CHANGELOG.md) | Version history. Add an entry for every user-visible change and bump `version:` in the module frontmatter. |
| `tests/` | Pytest coverage for `_route_gpt5_auto`, `transform_owui_tools`, web-search status events. |

## Hard invariants — do not break

1. **Marker format is a storage contract.** Hidden markers
   `\n[openai_responses:v2:<type>:<ULID16>]: #\n` (Crockford alphabet, 16 chars) are
   embedded in persisted assistant messages of *existing* chats. Changing the sentinel,
   regex, ULID length, or wrapper breaks reconstruction of historical conversations.
2. **Persistence schema.** Items live in the Chats table's `chat` JSON under
   `openai_responses_pipe` (`"__v": 3`, `items` keyed by ULID, `messages_index` per
   message). See ARCHITECTURE.md §Persistence.
3. **Model-id prefixing.** Open WebUI namespaces models as `openai_responses.<model_id>`;
   the manifold `id` and `ModelFamily._PREFIX` must stay in sync.
4. **`chat:completion` events must always include `content`** (even `""`) or the UI stalls.
5. **`body.input.extend(final_response["output"])`** after each streamed turn is what makes
   multi-loop tool calling and reasoning continuity work — never drop items from it.
6. **Keep `# fmt: off` / `# fmt: on`** guards: Open WebUI runs Black on upload; the aligned
   spec/alias/pricing tables rely on them.
7. `fetch_openai_response_items` filters persisted items by exact model id — by design
   (encrypted reasoning tokens are model-bound). Don't "fix" this without a migration plan.

## Current state / known quirks (as of 0.9.8-5.6)

- **Non-streaming is disabled** in `pipe()` (emits an error; `_run_nonstreaming_loop` is
  dormant but functional — it wraps the streaming loop with a suppressing emitter).
- `PARALLEL_TOOL_CALLS` valve is declared but never applied to the outbound body.
- `_route_gpt5_auto` ignores its `router_model` argument and hardcodes `gpt-5-mini`.
- Inline `[n]` citation markers in text are TODO; citations are emitted as `source` events only.
- `pipe()` has intentional side effects: it can flip the model record's
  `params.function_calling` to `"native"` in the DB, and injects CSS into the client tab
  to unclamp status lines.

## Workflow expectations

- Surgical, single-concern changes; match existing style (aligned tables, section banners).
- Update CHANGELOG.md + frontmatter `version` together.
- Run tests: `pytest functions/pipes/openai_responses_manifold/tests/` from repo root.
- `external/open-webui/` is a read-only upstream submodule — reference it, never edit it.
