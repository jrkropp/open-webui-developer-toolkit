# OpenAI Responses Manifold

Enables advanced OpenAI features (function calling, web search, visible reasoning summaries, and more) directly in [Open WebUI](https://github.com/open-webui/open-webui).

**Now supports OpenAI’s GPT-6 Astra and the GPT-5.6 family (Sol / Terra / Luna) in the API — [Learn more](#gpt-6-astra-and-gpt-56-model-support).**

This project started as an internal tool (200+ hours of optimization and testing) and is now open-sourced as a way to give back to the Open WebUI community.

> ✨ Like the manifold? 
> Show your support by sharing it with others and providing feedback through [GitHub Discussions](https://github.com/jrkropp/open-webui-developer-toolkit/discussions).  
> 💡 Pull Requests are welcome!


## Contents

* [Setup](#setup)
* [Features](#features)
* [Advanced Features](#advanced-features)
* [Tested Models](#tested-models)
* [GPT‑6 Astra and GPT‑5.6 Model Support](#gpt-6-astra-and-gpt-56-model-support)
* [How It Works (Design Notes)](#how-it-works-design-notes)

> 🛠️ **Contributing or using an AI agent on this codebase?** Start with [AGENTS.md](AGENTS.md) (context entry point) and [ARCHITECTURE.md](ARCHITECTURE.md) (full developer reference).

## Setup
1. In **Open WebUI ▸ Admin Panel ▸ Functions**, click **Import from Link**.
   
   <img width="450" alt="image" src="https://github.com/user-attachments/assets/4a5a0355-e0af-4fb8-833e-7d3dfb7f10e3" />

2. Paste one of the following links, depending on which version you want:

   * **Main** (recommended) – Stable production build with regular, tested updates:

     ```
     https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
     ```

   * **Alpha Preview** – Pre-release build with early features, typically 2–4 weeks ahead of main:

     ```
     https://github.com/jrkropp/open-webui-developer-toolkit/blob/alpha-preview/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
     ```

3. **⚠️ Important: Set the Function ID to `openai_responses`.**
   
   This value is currently hardcoded in the pipe and must match exactly. It will become configurable in a future release.
   
   <img width="800" alt="image" src="https://github.com/user-attachments/assets/ffd3dd72-cf39-43fa-be36-56c6ac41477d" />

4. Done! 🎉

## Features

| Feature                            | Status          | Last updated | Notes                                                                                                                                                                                                                                                                                                        |
| ---------------------------------- | --------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Native function calling**        | ✅ GA            | 2025-06-04   | Sends full JSON tool specs directly to OpenAI models that support function calling. This API-enforced method ensures reliable, validated tool calls and allows **multiple tool calls in a single response**. Much more robust than Open WebUI’s default single-call router.                                  |
| **Visible reasoning summaries**    | ✅ GA            | 2025-08-07   | Enables OpenAI’s *reasoning summaries*, which explain how the model arrives at its answers. Displayed in collapsible `<details>` blocks for transparency, trust, and easier debugging.                                                                                                                       |
| **Encrypted reasoning tokens**     | ✅ GA            | 2025-08-07   | Saves reasoning tokens across tool-calling “turns” (and optionally whole conversations). Prevents the model from having to **re-reason from scratch** after each tool call, making responses faster, cheaper, and more cache-friendly.                                                                       |
| **Optimized token caching**        | ✅ GA            | 2025-06-03   | Ensures all tokens—including hidden ones like tool calls and reasoning—are re-sent in the same order. This unlocks OpenAI’s token caching, cutting **input costs by 50–75%** and lowering latency.                                                                                                           |
| **Web search tool**                | ✅ GA            | 2025-06-03   | Injects OpenAI’s `web_search` tool into supported models. With the valve enabled, the model can **self-decide when to search**. Alternatively, filters can toggle it on/off (mirroring ChatGPT’s behavior). Now emits search queries and sources via status updates for richer feedback.                                                                                                  |
| **Task model support**             | ✅ GA            | 2025-08-07   | Detects when a request is for an **External Task Model** and routes it separately. Makes manifold models usable for lightweight routing or background tasks (e.g., with `gpt-4.1-nano`).                                                                                                                     |
| **Streaming responses (SSE)**      | ✅ GA            | 2025-06-04   | Supports **real-time streaming**, so users can watch responses appear live as the model generates them.                                                                                                                                                                                                      |
| **Usage pass-through**             | ✅ GA            | 2025-06-04   | Forwards API usage stats (tokens, caching data, etc.) into Open WebUI, visible in the frontend (hover the ℹ️ icon). Gives users **transparent cost and performance insights**.                                                                                                                               |
| **Cost estimation**                | ✅ GA            | 2026-09-01   | Appends an **estimated USD cost** block (`input_cost`, `cached_input_cost`, `output_cost`, `total_cost`) to the usage stats, computed from token counts and a built-in per-model price table. Toggle with `SHOW_USAGE_COST`; override rates via `CUSTOM_MODEL_PRICING_JSON`. Estimates exclude tool surcharges (e.g., web search). |
| **Response item persistence**      | ✅ GA            | 2025-06-27   | Persists hidden items (reasoning, tool calls) by embedding unique IDs in Markdown. Stored separately in the DB and reattached in later turns, so the **conversation can be rebuilt exactly** without losing hidden events.                                                                                   |
| **Open WebUI Notes compatibility** | 🔄 In progress            | 2025-07-14   | Works seamlessly with Open WebUI’s new **Notes feature** (currently preview). Ensures manifold-based models work even when chats are ephemeral (no `chat_id`).                                                                                                                                               |
| **Native status updates**         | ✅ GA            | 2025-07-01   | Reports progress using Open WebUI's built-in status emitter with steps like "Thinking…", "Reading the question and building a plan.", "Gathering my thoughts…", "Exploring possible answers…", "Almost done…", and ends with "Thought for N seconds." |
| **Inline citation events**         | ✅ GA (basic)    | 2025-07-28   | Adds inline citations (e.g., `[1]`) for **web search results**. Basic implementation works but still being refined. Style is adjustable with the `CITATION_STYLE` valve.                                                                                                                                     |
| **Truncation control**             | ✅ GA            | 2025-06-10   | Defaults to `auto`, meaning if token limits are exceeded, older context is trimmed instead of failing. You can also set `max_tokens` via custom parameters. See OpenAI’s [Responses API docs on truncation](https://community.openai.com/t/introducing-the-responses-api/1140929/12?utm_source=chatgpt.com). |
| **Custom param pass-through**      | ✅ GA            | 2025-06-14   | Supports Open WebUI’s **Custom Parameters**. Any params set in the GUI are passed through to OpenAI (e.g., `max_tokens` → `max_output_tokens`). Lets users fine-tune behavior without editing code.                                                                                                          |
| **Regenerate → `text.verbosity`**  | ✅ GA            | 2025-08-11   | Open WebUI v0.6.19 added regenerate buttons for “More Concise” / “Add Details.” The manifold maps these to the `text.verbosity` parameter for GPT-5 models. Falls back to prompt injection if not supported.                                                                                                 |
| **Filter-injected tools**          | ✅ GA            | 2025-08-28   | Lets developers build **companion filters** that add tools under `body.extra_tools`. The manifold merges these into `body.tools` before sending to OpenAI, removing duplicates. Enables features like **web search toggles** without breaking native function calling.                                       |
| **Image input (vision)**           | 🔄 In progress  | 2025-06-03   | Supports basic image input (Open WebUI converts uploads to base64 and forwards them). Works but inefficient for large images. A future version will switch to OpenAI’s **file upload API** for better performance.                                                                                           |
| **Image generation tool**          | 🕒 Backlog      | 2025-06-03   | Planned support for **creating and editing images** with OpenAI. Will include **multi-turn editing**, but depends on efficient image handling via file uploads first.                                                                                                                                        |
| **File upload / file search**      | 🕒 Backlog      | 2025-06-03   | Planned support for uploading files and querying their contents (e.g., PDFs, spreadsheets) directly in chat.                                                                                                                                                                                                 |
| **Code interpreter**               | 🕒 Backlog      | 2025-06-03   | Planned support for OpenAI’s **Python/code interpreter** tool. Would allow running code, analyzing data, and generating charts inside Open WebUI.                                                                                                                                                            |
| **Computer use**                   | 🕒 Backlog      | 2025-06-03   | Placeholder for OpenAI’s **computer use** tool (models interacting with apps or browsers). Not yet supported in Open WebUI.                                                                                                                                                                                  |
| **Live voice (Talk)**              | 🕒 Backlog      | 2025-06-03   | Planned support for **real-time voice conversations** (like ChatGPT’s Talk mode). Requires backend audio streaming support.                                                                                                                                                                                  |
| **Dynamic chat titles**            | 🕒 Backlog      | 2025-06-03   | Planned support for **auto-updating chat titles** during long tasks. Not yet implemented.                                                                                                                                                                                                                    |
| **MCP tool support**               | 🔄 Experimental | 2025-06-23   | Allows attaching **remote MCP servers** via the `REMOTE_MCP_SERVERS_JSON` valve. Experimental: implementation works but is not optimized, so **not production-ready**. Behavior may change.                                                                                                                  |

## Advanced Features
### Pseudo-model aliases

The `MODEL_ID` valve accepts **pseudo IDs** that resolve to an official model plus a preset, so you can pick a reasoning level from the model picker instead of editing Custom Parameters. Examples:

* `gpt-6-astra-pro-max` → `gpt-6-astra` with `reasoning.mode="pro"` + `reasoning.effort="max"`
* `gpt-5.6` → `gpt-5.6-sol` (mirrors OpenAI's own routing alias)
* `gpt-5.6-sol-max` → `gpt-5.6-sol` with `reasoning.effort="max"`
* `gpt-5.6-sol-pro-high` → `gpt-5.6-sol` with `reasoning.mode="pro"` + `reasoning.effort="high"`
* `o4-mini-high` → `o4-mini` with `reasoning.effort="high"`

Aliases are resolved before the request leaves the manifold, so OpenAI only ever sees the real model ID. See [Pseudo-Model Aliases](#pseudo-model-aliases-convenience-ids) for the naming rules.

### Cost estimation

When `SHOW_USAGE_COST` is enabled (default), the manifold appends an estimated USD cost to the usage stats shown in Open WebUI (hover the ℹ️ icon on a message):

```
cost: {
  input_cost: 0.008665
  cached_input_cost: 0.0
  output_cost: 0.00011
  total_cost: 0.008775
  currency: USD
}
```

How it works:

* Rates come from a built-in per-model price table (USD per 1M tokens). Cached input tokens are billed at the cached rate; the remainder at the full input rate.
* Costs accumulate correctly across tool-call loops (recomputed from cumulative token counts each turn) and follow the **actual served model** reported by the API (e.g., after `gpt-5-auto` routing).
* Use the `CUSTOM_MODEL_PRICING_JSON` valve to override or extend the table without editing code, e.g.:

```json
{"gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0}}
```

`cached_input` is optional (defaults to the input rate). Models missing from the table simply omit the cost block.

⚠️ Costs are **estimates** based on published token rates — they exclude tool surcharges (e.g., web search) and may lag pricing changes. Always verify against your OpenAI invoice.

### Debug logging

Set `LOG_LEVEL=debug` (pipe-level or per-user valve) to embed inline debug logs in assistant messages.
This surfaces details like:

* API request/response structure
* Tool merging behavior
* Hidden response items

Helpful for troubleshooting and understanding exactly how the manifold processes requests.

### Remote MCP servers (experimental)

Attach external [Model Context Protocol (MCP)](https://platform.openai.com/docs/guides/tools-remote-mcp) servers using the `REMOTE_MCP_SERVERS_JSON` valve.

* Accepts JSON describing one or more servers
  ⚠️ Still experimental: works, but **not recommended for production** yet.

### Filter-injected tools

Lets developers build **companion filters** that add OpenAI-style tools dynamically.

* Filters inject tools into `body.extra_tools`
* The manifold merges them into `body.tools` before sending the request
* Duplicates are removed automatically

E.g.,

```python
body.setdefault("extra_tools", []).append({
    "type": "function",
    "name": "weather_lookup",
    "description": "Get current weather by city.",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
})
```

This makes features like **on-demand web search toggles** possible without breaking native function calling.

## Tested Models
The manifold works with any model that supports the **OpenAI Responses API**.  
Below are the IDs registered by default in the `MODEL_ID` valve. Trim that list to what your org actually uses — every entry becomes a model in the Open WebUI picker.

### Official Model IDs

| Family | Model IDs | Type / Modality | Status | Notes |
|---|---|---|:--:|---|
| **GPT-6** | `gpt-6-astra` | Reasoning (text + image in) | ✅ | Current flagship. Single slug, no tiers; efforts `low`→`max` (**no `none`**) plus pro mode. |
| **GPT-5.6** | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | Reasoning (text + image in) | ✅ | Previous flagship family. Named tiers replace the old unsuffixed/mini/nano split; efforts `none`→`max` plus pro mode. |
| **GPT-5.5** | `gpt-5.5`, `gpt-5.5-pro` | Reasoning | ✅ | Here `-pro` *is* a separate model slug, unlike GPT-5.6 / GPT-6. |
| **GPT-5.4** | `gpt-5.4`, `gpt-5.4-pro` | Reasoning | ✅ | |
| **GPT-5.2** | `gpt-5.2`, `gpt-5.2-pro` | Reasoning | ✅ | |
| | `gpt-5.2-chat-latest` | Chat-tuned (non-reasoning) | ✅ | Tool calling + web search, no reasoning. |
| **GPT-5.1** | `gpt-5.1` | Reasoning | ✅ | |
| | `gpt-5.1-chat-latest` | Chat-tuned (non-reasoning) | ✅ | Tool calling + web search, no reasoning. |
| **GPT-5** | `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5-pro` | Reasoning | ✅ | The only family that accepts `minimal` effort. |
| | `gpt-5-chat-latest` | Chat-tuned (non-reasoning) | ✅ | Tool calling + web search, no reasoning. |
| | `gpt-5-auto` | Router (pseudo-model) | 🔄 Experimental | Not a real OpenAI ID — see [`gpt-5-auto`](#gpt-5-auto-experimental-router). |
| **GPT-4.1** | `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | Non-reasoning | ✅ | Good task/utility models. `gpt-4.1-nano` has no web search. |
| **GPT-4o** | `gpt-4o`, `gpt-4o-mini` | Text + image → text | ✅ | |
| | `chatgpt-4o-latest` | Chat-tuned (non-reasoning) | ✅ | ⚠️ No tool calling, web search, or other advanced features. |
| **O-series** | `o3`, `o3-mini`, `o4-mini` | Reasoning | ✅ | Only `o4-mini` gets the web search tool. |
| | `o3-pro` | Reasoning (higher compute) | ✅ | No reasoning summaries. |
| **Deep research** | `o3-deep-research`, `o4-mini-deep-research` | Agentic deep research | ❌ | IDs are registered, but the deep-research flow isn't implemented yet. |

You can add IDs that aren't listed here. Be aware that an unrecognized ID gets **no capability flags**, which means tools, reasoning summaries, and verbosity mapping all stay off for it — add it to `ModelFamily._SPECS` to enable those.

---

### Pseudo-Model Aliases (Convenience IDs)

Aliases are registered in the `MODEL_ID` valve alongside real IDs and follow one rule: **`<base model>` + `-<preset>`**. The manifold strips the preset, sets the matching `reasoning` parameters, and sends the base model ID upstream.

An *unsuffixed* base ID sends no `reasoning.effort` at all, so OpenAI applies that model's own default (`medium` for GPT-6 and GPT-5.6).

| Family | Base IDs | Effort suffixes | Pro-mode suffixes |
|---|---|---|---|
| **GPT-6** | `gpt-6-astra` | `-low` `-high` `-xhigh` `-max` | `-pro` `-pro-high` `-pro-xhigh` `-pro-max` |
| **GPT-5.6** | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | `-none` `-low` `-high` `-xhigh` `-max` | `-pro` `-pro-high` `-pro-xhigh` `-pro-max` *(sol only)* |
| **GPT-5.5 / 5.4 / 5.2** | `gpt-5.5`, `gpt-5.4`, `gpt-5.2` | `-low` `-medium` `-high` `-xhigh` | on the separate `-pro` model: `-pro-high` `-pro-xhigh` |
| **GPT-5.1** | `gpt-5.1` | `-low` `-medium` `-high` | — |
| **GPT-5** | `gpt-5`, `gpt-5-mini`, `gpt-5-nano` | `-minimal` `-high` | — |
| **O-series** | `o3-mini`, `o4-mini` | `-high` | — |

Plus two standalone pseudo IDs:

| Alias | Resolves to | Notes |
|---|---|---|
| `gpt-5.6` | `gpt-5.6-sol` | Mirrors OpenAI's own routing alias. |
| `gpt-5-auto` | `gpt-5-chat-latest`, `gpt-5`, or `gpt-5-mini` | A classifier picks the model **and** the effort per request. 🔄 Experimental. |

The effort ladders differ per family because OpenAI's supported values differ: `minimal` exists only on GPT-5, `xhigh` only from GPT-5.2 onward, `max` only on GPT-5.6 and GPT-6, and GPT-6 Astra drops `none`. Sending an unsupported effort returns an API error.

---


## GPT-6 Astra and GPT-5.6 Model Support

### GPT-6 Astra

`gpt-6-astra` is OpenAI's current flagship — a single slug with no tiers and no `gpt-6` routing alias. It keeps the GPT-5.6 API surface (function calling, web search, image generation, `text.verbosity`, persisted reasoning, prompt caching, pro mode) with the same 1,050,000-token context window and 128,000 max output tokens, and an Apr 30, 2026 knowledge cutoff.

| Model | Input / Cached / Output per 1M | Notes |
|---|---|---|
| `gpt-6-astra` | $10.00 / $1.00 / $50.00 | Cache writes $12.50; prompts over 272K input tokens bill 2× input and 1.5× output for the whole request (the cost estimate doesn't model this). |

What's different from GPT-5.6 when you switch:

- **No `none` effort.** `reasoning.effort` accepts `low`, `medium` (default), `high`, `xhigh`, `max`. If you used `none`/`minimal` before, OpenAI's advice is to start at `low`. That's why there is no `gpt-6-astra-none` alias.
- **`temperature`, `top_p`, and `top_logprobs` are rejected.** The manifold forwards these untouched, so clear them from the model's Custom Parameters in Open WebUI.
- **Tool calling requires the Responses API** — which is what this manifold speaks, so nothing to do.
- **More willing to ask before acting.** Astra pauses for clarification more often than GPT-5.6 Sol when intent is ambiguous. If that's undesirable for your use case, add explicit "bias toward action" guidance to the system prompt — see OpenAI's [prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra).
- Newer capabilities the manifold does not configure (forwarded untouched if supplied via Custom Parameters or a filter): async tool calling (`async: true` on a tool), mid-turn steering over WebSocket, `configuration_update` input items for changing effort mid-conversation, and `prompt_cache_options.ttl` (replaces `prompt_cache_retention`).

### GPT-5.6

GPT-5.6 changed the naming scheme. Instead of one model plus `-mini`/`-nano`/`-pro`, it ships **three named tiers** — all sharing a 1,050,000-token context window, 128,000 max output tokens, and a Feb 16, 2026 knowledge cutoff:

| Model | Tier | Input / Output per 1M | Roughly replaces |
|---|---|---|---|
| `gpt-5.6-sol` | Frontier / flagship | $5.00 / $30.00 | the unsuffixed tier (`gpt-5.5`) |
| `gpt-5.6-terra` | Balanced intelligence vs. cost | $2.50 / $15.00 | the `mini` tier |
| `gpt-5.6-luna` | Cost-sensitive, high volume | $1.00 / $6.00 | the `nano` tier |

`gpt-5.6` is OpenAI's own alias for `gpt-5.6-sol`, and the manifold resolves it the same way.

### Reasoning effort: `none` → `max`

GPT-5.6 accepts `none`, `low`, `medium`, `high`, `xhigh`, and the new **`max`**, defaulting to `medium` when no effort is sent.

Because GPT-5.6 is more token-efficient than earlier generations, OpenAI's migration advice is to **keep your current effort as the baseline, then also test one level lower** — quality often holds at the cheaper setting. Reserve `max` for quality-first workloads, and measure it against `xhigh` before adopting it.

### Pro mode is a parameter now, not a model

There is no `gpt-5.6-pro` model slug. Pro is an execution mode — `reasoning.mode: "pro"` — that applies more model work before returning a single final answer. It works on any GPT-5.6 model and is **independent of `reasoning.effort`**.

The manifold exposes it through the `gpt-5.6-sol-pro*` and `gpt-6-astra-pro*` aliases. Pro-mode tokens bill at the model's standard rates, but there are more of them and latency is higher, so use it where a marginal quality gain actually changes the outcome.

### Not yet wired into the manifold

GPT-5.6 also introduced capabilities the manifold doesn't configure for you:

- `reasoning.context: "all_turns"` (persisted reasoning across turns)
- Programmatic Tool Calling (`programmatic_tool_calling`)
- Multi-agent (beta)
- Explicit prompt caching (`prompt_cache_options`)

Any parameter the manifold doesn't specifically handle is forwarded to OpenAI untouched, so you can supply these through **Custom Parameters** or a companion filter. Note that GPT-5.6 bills cache *writes* at 1.25× the uncached input rate — watch `cached_tokens` against `cache_write_tokens` before leaning on explicit caching.

### `gpt-5-auto` (experimental router)

In the ChatGPT app, picking a model doesn't pin one endpoint — OpenAI runs a router that decides whether to use a reasoning, minimal-reasoning, or non-reasoning variant. That router isn't exposed in the API, so the manifold ships an experimental **`gpt-5-auto`** pseudo-model:

- It isn't a real OpenAI model ID.
- The request first goes to a lightweight classifier (`gpt-5-mini` at `minimal` effort with a routing prompt).
- The classifier returns both a model (`gpt-5-chat-latest`, `gpt-5`, or `gpt-5-mini`) and a `reasoning_effort`, which the manifold applies before issuing the real request.

⚠️ Still an early proof of concept, and it currently routes within the **GPT-5** family only.

### What you need to know

1. **Reasoning vs. non-reasoning** — all three GPT-5.6 tiers are reasoning models. `reasoning.effort="none"` is the latency baseline; for a true non-reasoning chat model you still need a `*-chat-latest` ID, and GPT-5.6 doesn't have one.
2. **Tool calling** — every GPT-5.6 tier supports native function calling, web search, and image generation. At the other extreme, `chatgpt-4o-latest` supports none of them.
3. **Latency** — for ultra-low-latency task work (title generation, tagging), `gpt-4.1-nano` or `gpt-5.6-luna-none` beat a high-effort model.
4. **Output style** — GPT-5.6 is noticeably more concise by default than GPT-5.5, so blanket “be concise” instructions may now be redundant or even counterproductive. Prefer `text.verbosity` for the default level of detail and keep the prompt for task-specific requirements; Open WebUI's “More Concise” / “Add Details” regenerate buttons already map to it.
5. **Leaner prompts win** — OpenAI reports both lower token use and better eval scores after de-duplicating instructions and tightening tool descriptions. Example prompts live in the `system_prompts` folder.

**Further reading:** [Using GPT-6 Astra](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra) · [Using GPT-5.6](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6) · [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning) · [Model catalog](https://developers.openai.com/api/docs/models)


## How It Works (Design Notes)

### Persisting non-message items (function calls, tool outputs, reasoning tokens, …)

The **OpenAI Responses API** doesn’t just return text. A single response can include:
- reasoning steps,
- function/tool calls,
- tool results,
- assistant messages.

By default, **Open WebUI only saves** the `role` (`user` / `assistant`) and the assistant’s **visible text content**.  
That means all the “hidden work” (reasoning, tools used, results returned) would normally disappear.  
If we don’t capture it:
- tool calls may run again on regenerate,
- reasoning tokens are wasted (higher cost, slower),
- the model’s exact sequence of actions is lost.

The manifold solves this by persisting **all items** in sequence, not just the visible text.

---

### The persistence challenge

Open WebUI’s conversation history is built around a simple `messages[]` array where each entry looks like:

```json
{ "role": "user" | "assistant", "content": "..." }
````

* `role` identifies who sent the message.
* `content` is always rendered in the chat UI as visible text.

Here’s the problem:

* **Upstream filters** (which inject context, rewrite prompts, toggle tools, etc.) only modify the `messages[]` array.
* If the manifold built its own parallel storage, it would ignore those filter changes — breaking compatibility and leaving the manifold out of sync.

So we must keep using the **same `messages[]` array** that Open WebUI and its filters rely on.
But since `content` is always displayed in the UI, we need a way to tuck hidden data into assistant messages **without showing it to the user**.

---

### The solution: invisible markers

The manifold injects **empty Markdown reference links** into the assistant’s response text.
These links are ignored by the Open WebUI frontend (they don’t render), but they carry stable IDs that point to the hidden items stored in the DB.

Example marker:

```
[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H]: #
```

**Marker format:**

```
[openai_responses:v2:<item_type>:<id>[?model=<model_id>&k=v...]]: #
```

* `<item_type>` = event type (e.g., `function_call`, `reasoning`)
* `<id>` = unique 16-character ID
* optional query params (e.g., `model`)

> **Why not embed JSON directly?**
> Markers keep assistant messages lightweight and clipboard-safe, while the full payloads remain in the DB.

---

### Example: function call flow

1. **User asks a question**

```json
{ "role": "user", "content": "Calculate 34234 multiplied by pi." }
```

2. **Model emits a tool call**

```json
{
  "type": "function_call",
  "name": "calculator",
  "arguments": "{\"expression\":\"34234*pi\"}",
  "status": "completed"
}
```

* Stored under ID `01HX4Y2VW5VR2Z2H`
* Marker injected into assistant output:

```
[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H]: #
```

3. **Tool result is persisted the same way**

```
[openai_responses:v2:function_call_output:01HX4Y2VW6B091XE]: #
```

4. **Assistant shows visible text**

```
34234 multiplied by π ≈ 107,549.28.
```

5. **Final stream = hidden markers + visible text**

```
[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #
[openai_responses:v2:function_call_output:01HX4Y2VW6B091XE?model=openai_responses.gpt-4o]: #
The result of \(34234 \times \pi\) is approximately 107,549.28.
```

---

### Why this matters

By combining hidden markers with DB persistence:

* **No duplicate work** → tool calls and reasoning aren’t re-run on regenerate
* **Lower cost & latency** → caching saves \~50–75% input tokens
* **Filter compatibility** → upstream filters can still modify `messages[]` normally
* **Full fidelity history** → the exact reasoning + tool sequence is preserved and replayable

---

> **Tip for debugging:** Open browser **DevTools → Network**, inspect the chat POST payload, and you’ll see the hidden markers alongside the visible messages.
