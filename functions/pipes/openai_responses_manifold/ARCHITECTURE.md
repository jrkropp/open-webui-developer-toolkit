# Architecture Reference — OpenAI Responses Manifold

Developer/agent reference for `openai_responses_manifold.py` (v0.9.8-5.6, ~2,520 lines).
For the entry-point summary and hard invariants, see [AGENTS.md](AGENTS.md).
Line numbers are approximate and drift as the file evolves — use the symbol names.

## Code map

| Section | Symbols | Purpose |
|---|---|---|
| Model registry | `ModelFamily` | Static specs, aliases, pricing for all supported models |
| Request models | `CompletionsBody`, `ResponsesBody` | Pydantic models; Completions → Responses transformation |
| Pipe | `Pipe` (`Valves`, `UserValves`, `pipes`, `pipe`, loops) | Open WebUI entry points and orchestration |
| Logging | `SessionLogger` | Per-session in-memory log buffer, surfaced as citations |
| Persistence | `persist_openai_response_items`, `fetch_openai_response_items` | Hidden-item storage in the chat record |
| Markers | `generate_item_id`, `create_marker`, `wrap_marker`, `parse_marker`, `extract_markers`, `split_text_by_markers` | Invisible markdown markers linking messages to persisted items |
| Tools | `build_tools`, `_strictify_schema`, `_dedupe_tools` | Final tool-list assembly |
| Misc | `merge_usage_stats`, `resolve_model_pricing`, `estimate_usage_cost`, `wrap_code_block`, `_wrap_event_emitter` | Helpers |

## 1. Model registry (`ModelFamily`)

All-classmethod static registry. Normalization (`_norm`) strips the
`openai_responses.` prefix and `-YYYY-MM-DD` date suffixes, lowercases.

- **`_SPECS`** — base model → feature set. Registered families: GPT-6 (`gpt-6-astra`,
  single slug, no tiers), GPT-5.6 (`gpt-5.6-sol|terra|luna`), GPT-5.5/5.4/5.2 (+`-pro`), `gpt-5.1`, GPT-5
  (`gpt-5`, `-pro`, `-auto`, `-mini`, `-nano`), GPT-4.1 (`gpt-4.1`, `-mini`, `-nano`),
  `gpt-4o`/`-mini`, o-series (`o3`, `o3-mini`, `o3-pro`, `o4-mini`), deep research
  (`o3-deep-research`, `o4-mini-deep-research`), chat-latest snapshots
  (`gpt-5.2-chat-latest`, `gpt-5.1-chat-latest`, `gpt-5-chat-latest`, `chatgpt-4o-latest`).
- **Feature flags**: `function_calling`, `reasoning`, `reasoning_summary`,
  `web_search_tool`, `image_gen_tool`, `verbosity`, `deep_research`.
- **`_ALIASES`** — pseudo-model → `{base_model, params}`. Effort suffixes
  (`-none/-low/-high/-xhigh/-max` per family; GPT-6 Astra has no `-none` because the API
  rejects that effort), pro-mode aliases (`gpt-5.6-sol-pro*`, `gpt-6-astra-pro*` →
  `reasoning.mode="pro"`), plain remaps (`gpt-5.6` → `gpt-5.6-sol`; there is no `gpt-6`
  alias), back-compat (`o3-mini-high`, `o4-mini-high`). GPT-5.6 and GPT-6 have **no**
  `-pro` model slug — pro is a `reasoning.mode` param independent of `reasoning.effort`.
- **`_PRICING`** — base model → `(input, cached_input, output)` USD per 1M tokens;
  `cached_input=None` means cached tokens bill at the full input rate. Overridable at
  runtime via the `CUSTOM_MODEL_PRICING_JSON` valve.
- Helpers: `base_model()`, `params()` (alias-implied defaults), `features()`,
  `supports(feature, id)`, `pricing()`, `display_name()` (id → human-friendly picker
  name, e.g. `gpt-5.6-luna-pro` → "GPT 5.6 Luna Pro"; overrides in
  `_NAME_TOKEN_OVERRIDES`, o-series ids stay lowercase). Workspace records still
  named with the pre-0.9.11 `OpenAI: <id>` auto-name override the pipe-provided
  name, so `pipes()` runs `_rename_legacy_model_records` once per process to
  migrate them (admin-customized names are left alone).
- **`_PSEUDO_MODELS`** — pipe-side router ids (`gpt-5-auto`) never served by
  `/models`; always kept when `pipes()` filters against the fetched model list.

## 2. Request transformation

**`CompletionsBody`**: `model`, `messages`, `stream`; `extra="allow"` so arbitrary
params (including `extra_tools`) pass through.

**`ResponsesBody.from_completions()`** pipeline:
1. Drop unsupported Completions params with a warning (`frequency_penalty`, `seed`,
   `response_format`, `functions`, etc.).
2. `max_tokens` → `max_output_tokens`; `reasoning_effort` → `reasoning.effort`
   (via `setdefault`, never overwrites an explicit value).
3. Last **system** message → `instructions` (system messages are excluded from `input`).
4. `messages` → `input` via `transform_messages_to_input`.
5. Construct `ResponsesBody(**sanitized, **extra_params)` — caller overrides win.

**`_apply_alias_defaults`** (model_validator): resolves aliases to base models and
deep-overlays alias params onto the body (`_deep_overlay`: dicts merge recursively,
lists concat with dedupe, alias scalars win). E.g. `gpt-5-high` → `gpt-5` +
`reasoning.effort="high"`. OpenAI never sees pseudo ids.

**`transform_messages_to_input`** rebuilds Responses `input` from chat history:
1. Scan assistant messages for hidden markers; collect referenced ULIDs.
2. `fetch_openai_response_items(chat_id, ulids, model_id)` — items stored under a
   *different* model id are silently dropped (encrypted reasoning is model-bound).
3. Map messages: user `text`→`input_text`, `image_url`→`input_image`,
   `input_file`→`input_file`; `developer` passes through; assistant text containing
   markers is split by `split_text_by_markers` and persisted items are re-injected
   verbatim at their original positions between `output_text` blocks.

This exact-order reconstruction is what unlocks OpenAI prompt caching across turns.

## 3. Valves

| Valve | Default | Purpose |
|---|---|---|
| `BASE_URL` | env or `https://api.openai.com/v1` | API base (LiteLLM-compatible) |
| `API_KEY` | env `OPENAI_API_KEY` | API key |
| `MODEL_ID` | all specs + aliases | Comma-separated ids exposed in the model picker |
| `FETCH_MODELS` | `True` | Fetch `{BASE_URL}/models` and hide unavailable `MODEL_ID` entries (pseudo-models kept; falls back to full list on failure/empty match) |
| `MODEL_FETCH_TTL_SECONDS` | `600` | Cache TTL for the fetched model list (min 60; failures cached too) |
| `MODEL_ICON_URL` | `None` | Icon for this manifold's models; `pipes()` writes it to each record's `meta.profile_image_url`, only if no icon is set (creates a minimal record when none exists) |
| `REASONING_SUMMARY` | `disabled` | `auto\|concise\|detailed\|disabled` (needs verified org) |
| `PERSIST_REASONING_TOKENS` | `disabled` | `disabled` / `response` (in-turn) / `conversation` (across turns) |
| `AUTO_ENABLE_NATIVE_FUNCTION_CALLING` | `True` | Persist `function_calling: "native"` on the model record when tools are attached and the setting is unset (never overrides an explicit value) |
| `PERSIST_TOOL_RESULTS` | `True` | Persist tool outputs across turns |
| `PARALLEL_TOOL_CALLS` | `True` | **Declared but currently unused** (body default applies) |
| `ENABLE_STRICT_TOOL_CALLING` | `True` | Strictify registry tool schemas, `strict: true` |
| `MAX_TOOL_CALLS` | `None` | Cap on built-in tool calls (`max_tool_calls`) |
| `MAX_FUNCTION_CALL_LOOPS` | `10` | Max model→tools→model cycles |
| `ENABLE_WEB_SEARCH_TOOL` | `False` | Attach built-in `web_search` where supported |
| `WEB_SEARCH_CONTEXT_SIZE` | `medium` | `low\|medium\|high` |
| `WEB_SEARCH_USER_LOCATION` | `None` | JSON user-location object |
| `REMOTE_MCP_SERVERS_JSON` | `None` | Experimental remote MCP servers (list or object) |
| `TRUNCATION` | `auto` | Responses truncation strategy |
| `SHOW_USAGE_COST` | `True` | Append estimated USD cost to usage |
| `CUSTOM_MODEL_PRICING_JSON` | `None` | Override/extend the price table |
| `PROMPT_CACHE_KEY` | `id` | User identifier (`id`/`email`) sent as `user` for cache affinity |
| `LOG_LEVEL` | env or `INFO` | Pipe log level |

`UserValves`: `LOG_LEVEL` (default `INHERIT`). `_merge_valves` overlays non-None,
non-`inherit` user values onto globals.

## 4. `pipe()` request flow

1. Merge valves; resolve `openwebui_model_id` from `__metadata__["model"]["id"]`;
   read per-request features from `__metadata__["features"]["openai_responses"]`;
   bind `SessionLogger` contextvars.
2. One-time CSS injection (`execute` event) to unclamp status descriptions in the UI.
3. Build `ResponsesBody.from_completions(...)` with `truncation`, `user`,
   `max_tool_calls` overrides.
4. `__task__` set (title/tags/etc.) → `_run_task_model_request` (minimal
   non-streaming call, returns concatenated `output_text`) and return.
5. `build_tools(...)` (awaits `__tools__` if coroutine — OWUI ≥0.6.23).
6. If tools exist, `AUTO_ENABLE_NATIVE_FUNCTION_CALLING` is on, and the model record's
   `function_calling` param is **unset**, persist `"native"` to the DB
   (`Models.update_model_by_id`) and notify the user to re-run. Explicit values
   (including `"default"`) are never overridden.

7. gpt-5-auto routing: id ending `.gpt-5-auto-dev` → `_route_gpt5_auto` (LLM router:
   hardcoded `gpt-5-mini` @ minimal effort, strict JSON schema choosing between
   `gpt-5-chat-latest`/`gpt-5`/`gpt-5-mini` + effort; attaches `model_router_result`);
   `.gpt-5-auto` → hardcoded `gpt-5-chat-latest` + "coming soon" toast.
8. Attach `tools`; set `reasoning.summary`; add `include=["reasoning.encrypted_content"]`
   (when reasoning + persistence enabled + `store=False`); add
   `web_search_call.action.sources` to `include` when web search is attached.
9. Map OWUI regenerate stubs (`add details`/`more concise`) → `text.verbosity`
   for verbosity-capable models, popping the stub from `input`.
10. Streaming → `_run_streaming_loop`. Non-streaming → **error** (path disabled;
    `_run_nonstreaming_loop` wraps the streaming loop with a `chat:message`-suppressing
    emitter and is kept dormant).

## 5. Streaming loop (`_run_streaming_loop`)

Outer `for loop_idx in range(MAX_FUNCTION_CALL_LOOPS)`; each iteration is one SSE call
via `send_openai_responses_streaming_request` (hand-rolled `data:` line parser,
`[DONE]` terminates).

- **Fake thinking statuses**: for reasoning models, delayed jittered status messages
  ("Thinking…", "Building a plan…", …) until the first real event cancels them.
- Key events:
  - `response.output_text.delta` → append + `chat:message`.
  - `response.reasoning_summary_text.done` → parse `**bold**` heading into a
    two-line status (title + content).
  - `response.output_text.annotation.added` (`url_citation`) → dedupe by URL, strip
    `utm_source=openai`, emit `source` event with ordinal. Inline `[n]` markers: TODO.
  - `response.output_item.done` → persistence policy (below) + per-tool status titles
    (function call code block, `web_search_queries_generated` / `sources_retrieved` /
    `web_search` statuses, image gen, MCP, file search, local shell).
  - `response.completed` → capture `final_response`, **extend `body.input` with the full
    `output` array** so the next loop carries reasoning/tool context.
- **Persistence policy** per output item: `reasoning` persists only when
  `PERSIST_REASONING_TOKENS == "conversation"`; `message`/`web_search_call` never;
  everything else when `PERSIST_TOOL_RESULTS`. Persisted items append their hidden
  marker to `assistant_message` (re-emitted via `chat:message`).
- **Function calls**: `_execute_function_calls` runs OWUI registry tools concurrently
  (async awaited, sync via `asyncio.to_thread`; missing tool → "Tool not found"),
  produces `function_call_output` items → optionally persisted → extended onto
  `body.input` → next loop. No calls → break.
- **Usage/cost**: per-turn usage merged via `merge_usage_stats` (`turn_count`,
  `function_call_count` added); cost recomputed each turn from *cumulative* counts via
  `resolve_model_pricing` using the **actual served model** (matters post-routing).
- **`finally`**: cancel thinking tasks, emit "Thought for N seconds", emit session logs
  as a "Logs" citation, emit final `chat:completion` (`content=""`, `done=True`), write
  `{"sources": emitted_citations}` to the message row. Returns `assistant_message`
  (markers included) for Open WebUI to persist.

Errors route through `_emit_error` (chat-completion error frame + optional
"Error Logs" citation from the session buffer).

## 6. Persistence & markers

**Storage** (in the `Chats` table's `chat` JSON column — not `meta`):

```
chat.chat["openai_responses_pipe"] = {
  "__v": 3,
  "items": { "<ULID16>": { "model": "<openwebui_model_id>", "created_at": <ts>,
                            "payload": <raw Responses item>, "message_id": "<id>" } },
  "messages_index": { "<message_id>": { "role": "assistant", "done": true,
                                         "item_ids": ["<ULID16>", ...] } }
}
```

**Marker format** (`v2`; note store `__v: 3` is independent):

- Bare: `openai_responses:v2:<item_type>:<ULID16>[?k=v&…]`
  (`item_type` must match `[a-z0-9_]{2,30}`; query metadata via `_qs`/`_parse_qs`,
  no URL-encoding).
- ULID: 16 chars, Crockford alphabet, `secrets.choice`.
- Wrapped (`wrap_marker`) as an empty markdown link-reference definition:
  `\n[<marker>]: #\n` — invisible when rendered, survives as text in the stored message.
- Detection: `_SENTINEL = "[openai_responses:v2:"` fast check, `_RE` for full parse;
  `split_text_by_markers` yields ordered text/marker segments for input rebuilding.

## 7. Tool building (`build_tools`)

Merge order (later wins after `_dedupe_tools`):
1. Bail with `[]` if the model lacks `function_calling`.
2. OWUI registry tools (`transform_owui_tools`, strictified per valve).
3. Built-in `web_search` — when supported AND (valve OR per-request feature flag) AND
   `reasoning.effort != "minimal"`; carries `search_context_size` + optional `user_location`.
4. Remote MCP tools (`_build_mcp_tools`: requires `server_label` + `server_url`;
   whitelisted keys only; invalid entries warned and dropped).
5. `extra_tools` from upstream filters (see [DESIGN.md](DESIGN.md)) — already
   OpenAI-format, passed through with minimal validation.

Dedup identity: `("function", name)` for function tools, `(type, None)` otherwise;
last occurrence wins.

`_strictify_schema`: deep-copies; wraps non-object roots as
`{"type":"object","properties":{"value":…}}`; per object node sets
`additionalProperties: false`, `required` = all keys, and adds `"null"` to types of
previously-optional properties; recurses into `properties`/`items`/`anyOf`/`oneOf`.

## 8. HTTP & logging

- Shared `aiohttp.ClientSession` cached on the pipe instance
  (`TCPConnector(limit=50, limit_per_host=10, keepalive_timeout=75)`,
  `ClientTimeout(connect=30, sock_read=3600)`).
- `SessionLogger`: ContextVar-scoped session id + log level; class-level
  `deque(maxlen=2000)` buffer per session, emitted as a "Logs"/"Error Logs" citation
  and cleared per request. Per-user `LOG_LEVEL=debug` enables inline debug logs.

## 9. Testing

```sh
pytest functions/pipes/openai_responses_manifold/tests/
```

Current coverage: `test_route_gpt5_auto.py`, `test_transform_owui_tools.py`,
`test_web_search_status.py`. Prefer adding tests against pure helpers (transformers,
markers, tool building) — they import the module directly without an Open WebUI runtime.
