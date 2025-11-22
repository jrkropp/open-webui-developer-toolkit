# History Manager

`functions/pipes/openai_responses_manifold/docs/history_manager.md`

> **Purpose:** Explain how the manifold’s **history layer** takes Open WebUI’s `messages[]` and turns them into OpenAI **Responses API** `input` items, and how this ties into marker‑based persistence and the DB.

This doc describes the **`domain.history`** layer:

* `HistoryStore` – abstract interface over persistence.
* `HistoryManager` – pure domain logic for:

  * reconstructing Responses `input[]` from `messages[]` + markers + stored items,
  * persisting new items and appending markers into assistant text.

In earlier iterations this logic lived inside `ResponsesBody.transform_messages_to_input(...)` in `types.py`. In the new architecture, any such function should be a thin wrapper around `HistoryManager` (or removed entirely).

---

## 1. Responsibilities & high‑level goals

The history layer must bridge three worlds:

1. **Open WebUI history**

   ```json
   [
     { "role": "user", "content": "Hi" },
     { "role": "assistant", "content": "Hello!" }
   ]
   ```

   * Filters, plugins, and the UI all assume `messages[]` is the single source of truth.

2. **OpenAI Responses API input**

   ```json
   {
     "input": [
       {
         "role": "user",
         "content": [
           { "type": "input_text", "text": "Hi" },
           { "type": "input_image", "image_url": "..." }
         ]
       },
       { "type": "function_call", ... },
       { "type": "function_call_output", ... },
       { "type": "reasoning", ... }
     ],
     "instructions": "You are a helpful assistant."
   }
   ```

3. **Marker‑based persistence**

   * Structured items live under `chat.chat["openai_responses_pipe"]`.
   * Assistant messages reference those items via **invisible markers**:

     ```text
     [openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #
     ```

The **History Manager** is where all of this comes together.

**It must:**

1. Keep **filters in control** of `messages[]`.
2. Reuse **persisted items** (tool calls, outputs, reasoning) on regenerate instead of re‑running them.
3. Keep assistant text **clean and readable** in the UI (markers stay invisible).
4. Preserve **chronological ordering** of user/assistant text and hidden items.
5. Work even when persistence is **disabled or unavailable**.

For marker format and DB layout, see `markers_and_persistence.md`.

---

## 2. Core types: `HistoryStore` & `HistoryManager`

### 2.1 `HistoryStore` (persistence interface)

`HistoryStore` is a small protocol that hides the actual DB implementation:

```python
class HistoryStore(Protocol):
    def save_items(
        self,
        chat_key: dict,
        message_id: str,
        items: list[dict],
        model_id: str,
    ) -> list[str]:
        """Persist items and return their ULIDs (as strings)."""

    def load_items(
        self,
        chat_key: dict,
        item_ids: list[str],
        model_id: str | None = None,
    ) -> dict[str, dict]:
        """Return {ulid: payload} for the requested items."""
```

* `chat_key` is an opaque key containing at least the chat identifier, e.g.:

  ```python
  chat_key = {"chat_id": __metadata__["chat_id"], "pipe_id": "openai_responses"}
  ```

* `model_id` (here) is the **Open WebUI model id** (e.g. `"openai_responses.gpt-4o"`), used to filter items that belong to other models.

On the Open WebUI side, `openwebui.store.OpenWebUIHistoryStore` implements this using `Chats` and the `openai_responses_pipe` layout documented in `markers_and_persistence.md`.

### 2.2 `HistoryManager`

`HistoryManager` is a **pure domain** class that only depends on:

* a `HistoryStore` instance,
* marker utilities (`core.markers`),
* standard Python types.

It exposes two key methods:

```python
class HistoryManager:
    def __init__(self, store: HistoryStore): ...

    def build_input_from_messages(
        self,
        messages: list[dict],
        chat_key: dict,
        model_id: str | None,
        openwebui_model_id: str | None,
    ) -> tuple[list[dict], str | None]:
        ...

    def persist_items_for_message(
        self,
        chat_key: dict,
        message_id: str,
        items: list[dict],
        model_id: str,
        openwebui_model_id: str,
        current_assistant_text: str,
    ) -> str:
        ...
```

Parameter meanings:

* `model_id` (both methods): canonical OpenAI model id (e.g. `"gpt-5.1"`). Mainly useful for logging / future behavior flags.
* `openwebui_model_id`: the full Open WebUI model id (e.g. `"openai_responses.gpt-5.1-chat-latest"`). This is what gets stored on items and used for filtering in the DB.

Usage:

* `build_input_from_messages(...)` is called from the OpenWebUI bridge:

  * Returns a fully formed `input[]` list for the Responses API.
  * Returns the last `system` message as `instructions` (or `None`).

* `persist_items_for_message(...)` is called from the engine at the **end** of a turn:

  * Persists structured items (tool outputs, reasoning, etc.).
  * Generates and appends marker strings to the assistant text.
  * Returns the updated assistant text (with markers included but still invisible in the UI).

---

## 3. Invariants to preserve

The history layer must uphold these invariants:

1. **Filters own `messages[]`**

   * We never maintain a separate “shadow history”.
   * We always start from the `messages[]` array passed into the pipe (after filters have run).

2. **No duplicate work on regenerate**

   * Previously executed tool calls, tool outputs, and persisted reasoning must **not** be re-run.
   * Instead, we reconstruct them from the persistence store and reinsert them into `input`.

3. **UI text stays clean**

   * Assistant `content` is user‑friendly text.
   * Markers are invisible Markdown reference links; users don’t see them.

4. **Ordering is correct**

   * The `input` array must reflect the true chronological order:

     * user → assistant text → tool calls → tool outputs → reasoning → … (as originally streamed).

5. **Safe degradation**

   * If `chat_key` or `openwebui_model_id` is missing, or persistence is disabled:

     * We skip DB lookups and treat markers as plain text.
     * The transform still works for one‑shot / ephemeral use.

6. **Model‑scoped items**

   * When loading items, we must **not** mix data across models:

     * Only items whose stored `model` matches `openwebui_model_id` are used.

7. **Marker & DB compatibility**

   * Marker format and `openai_responses_pipe` layout must remain compatible with legacy data (see `markers_and_persistence.md`).

---

## 4. `build_input_from_messages(...)` – Inputs & outputs

### 4.1 Inputs

Typical call from the OpenWebUI bridge:

```python
input_items, instructions = history_manager.build_input_from_messages(
    messages=body["messages"],
    chat_key={"chat_id": __metadata__["chat_id"], "pipe_id": "openai_responses"},
    model_id=ctx.model_id,                  # canonical OpenAI model id (e.g. "gpt-5.1")
    openwebui_model_id=ctx.metadata["owui_model_id"],  # e.g. "openai_responses.gpt-5.1-chat-latest"
)
```

* `messages`: raw Open WebUI messages array:

  ```python
  {
    "role": "user" | "assistant" | "system" | "developer",
    "content": str | list[dict],  # same shape filters see and manipulate
  }
  ```

* `chat_key`: at minimum `{ "chat_id": <str> }`. It can include other keys (e.g. `pipe_id`) but is opaque to `HistoryManager`.

* `model_id`: canonical OpenAI model id. Currently used mainly for logging / future feature hooks.

* `openwebui_model_id`: full Open WebUI model id; used to filter persisted items and encode into markers.

If `chat_key` or `openwebui_model_id` is `None`, item loading is skipped and we only transform visible text.

### 4.2 Outputs

* `input_items: list[dict]` – the Responses `input` array:

  ```jsonc
  [
    {
      "role": "user",
      "content": [
        { "type": "input_text", "text": "Hi there!" }
      ]
    },
    {
      "type": "function_call",
      "name": "...",
      "arguments": "...",
    },
    {
      "role": "assistant",
      "content": [
        { "type": "output_text", "text": "Hello! How can I help?" }
      ]
    }
  ]
  ```

* `instructions: str | None` – the last `system` message’s content, or `None` if there are no system messages.

  * The OpenWebUI bridge assigns this to `ResponsesRequest.instructions`.

---

## 5. Algorithm details – `build_input_from_messages`

### 5.1 Step 0 – Collect ULIDs from markers (if possible)

If both `chat_key` and `openwebui_model_id` are present:

1. Initialize:

   ```python
   required_item_ids: set[str] = set()
   ```

2. For each `msg` in `messages` where `msg["role"] == "assistant"` and `msg["content"]` is a string:

   * If `core.markers.contains_markers(msg["content"])` is true:

     * Call `core.markers.extract_markers(msg["content"], parsed=True)`.
     * For each parsed marker `mk`, add `mk.ulid` to `required_item_ids`.

We ignore markers in non‑assistant messages.

### 5.2 Step 1 – Load persisted items from the store

If `required_item_ids` is non‑empty:

```python
items_lookup = store.load_items(
    chat_key=chat_key,
    item_ids=list(required_item_ids),
    model_id=openwebui_model_id,  # filter by Open WebUI model id
)
```

* `items_lookup` maps ULID → stored payload:

  ```python
  {
    "01HX4Y2VW5VR2Z2H": { "type": "function_call", ... },
    ...
  }
  ```

If persistence is unavailable, or `required_item_ids` is empty, use `items_lookup = {}`.

### 5.3 Step 2 – Walk messages and build `input_items`

Initialize:

```python
input_items: list[dict] = []
instructions: str | None = None
```

Then iterate `messages` in order.

---

#### Case A – `role == "system"`

* Do **not** add any `input` items for system messages.
* Set `instructions` to the latest system content:

  ```python
  content = msg.get("content")

  if isinstance(content, str):
      instructions = content
  else:
      # For structured system messages, serialize to a string,
      # e.g. join all text content blocks.
      instructions = render_system_content(content)
  ```

The **last** system message wins.

---

#### Case B – `role == "user"`

Map user messages into **input blocks**.

1. Normalize content:

   ```python
   blocks = msg.get("content") or []
   if isinstance(blocks, str):
       blocks = [{"type": "text", "text": blocks}]
   ```

2. Transform each block:

   ```python
   def _to_input_block(block: dict) -> dict:
       kind = block.get("type")
       if kind == "text":
           return {"type": "input_text", "text": block.get("text", "")}
       if kind == "image_url":
           url = (block.get("image_url") or {}).get("url")
           return {"type": "input_image", "image_url": url}
       if kind == "input_file":
           return {"type": "input_file", "file_id": block.get("file_id")}
       # Fallback: pass block through as-is
       return block
   ```

3. Append to `input_items`:

   ```python
   content_blocks = [
       _to_input_block(b)
       for b in blocks
       if b is not None
   ]
   if content_blocks:
       input_items.append({"role": "user", "content": content_blocks})
   ```

---

#### Case C – `role == "developer"`

Developer messages are “hidden instructions” that still flow through the Responses API.

We handle them similarly to user messages, but with `role = "developer"`:

```python
blocks = msg.get("content") or []
if isinstance(blocks, str):
    blocks = [{"type": "text", "text": blocks}]

content_blocks = [
    _to_input_block(b)     # reuse the same helper as user
    for b in blocks
    if b is not None
]

if content_blocks:
    input_items.append({"role": "developer", "content": content_blocks})
```

> Note: System messages modify `instructions` instead of emitting `input` items. Developer messages stay in `input` so the model can “see” them distinct from user content.

---

#### Case D – `role == "assistant"`

Assistant messages can contain:

* Plain text.
* Plain text + markers.
* (Rarely) non‑string content; we degrade gracefully.

1. Get raw text:

   ```python
   raw = msg.get("content", "") or ""
   if not isinstance(raw, str):
       # For safety: convert structured content to a best-effort string.
       raw = str(raw)
   ```

2. If `core.markers.contains_markers(raw)` is **false**:

   * Treat the entire message as plain text:

     ```python
     text = raw.strip()
     if text:
         input_items.append({
             "role": "assistant",
             "content": [{"type": "output_text", "text": text}],
         })
     ```

3. If `core.markers.contains_markers(raw)` is **true**:

   * Split into segments using `core.markers.split_text_by_markers(raw)`:

     ```python
     segments = split_text_by_markers(raw)
     ```

   `segments` has the form:

   ```python
   [
     { "type": "text",   "text": "visible text..." },
     { "type": "marker", "payload": "openai_responses:v2:..." },
     ...
   ]
   ```

   * For each segment:

     * If `segment["type"] == "marker"`:

       1. Parse raw marker payload:

          ```python
          mk = parse_marker(segment["payload"])  # item_type, ulid, metadata
          ```

       2. Resolve payload from `items_lookup`:

          ```python
          item = items_lookup.get(mk.ulid)
          if item is not None:
              input_items.append(item)
          ```

          Unknown ULIDs or mismatched models are silently ignored.

     * If `segment["type"] == "text"`:

       ```python
       text = segment["text"].strip()
       if text:
           input_items.append({
               "role": "assistant",
               "content": [{"type": "output_text", "text": text}],
           })
       ```

Because we iterate segments **in order**, the final `input_items` list preserves the original interleaving of:

* structured items (tool calls, outputs, reasoning), and
* visible assistant text.

---

## 6. `persist_items_for_message(...)` – Persisting new items & markers

This method is called from the engine after a turn, whenever we have new structured items to store (e.g., tool outputs, reasoning):

```python
updated_text = history_manager.persist_items_for_message(
    chat_key=history_key,
    message_id=ctx.metadata["message_id"],
    items=items_to_persist,             # list[dict]
    model_id=ctx.model_id,              # canonical OpenAI model (for logging / invariants)
    openwebui_model_id=ctx.metadata["owui_model_id"],
    current_assistant_text=assistant_text,  # what the user sees so far
)
```

### 6.1 Behavior

1. If `items` is empty:

   * Return `current_assistant_text` unchanged.

2. Call the store:

   ```python
   ulids = store.save_items(
       chat_key=chat_key,
       message_id=message_id,
       items=items,
       model_id=openwebui_model_id,  # stored as "model" in the DB
   )
   ```

   * `HistoryStore.save_items` is responsible for:

     * Writing to `openai_responses_pipe.items[ulid]`.
     * Updating `messages_index[message_id]["item_ids"]`.
     * Returning the ULIDs in the same order as `items`.

3. For each `(ulid, payload)` pair:

   * Determine an `item_type`:

     ```python
     item_type = payload.get("type", "unknown")
     ```

   * Build raw marker payload via `core.markers.build_marker_payload(...)`:

     ```python
     marker_payload = build_marker_payload(
         item_type=item_type,
         ulid=ulid,
         metadata={"model": openwebui_model_id},
     )
     ```

   * Wrap into invisible Markdown:

     ```python
     marker_text = wrap_marker(marker_payload)  # "\n[openai_responses:v2:...]: #\n"
     ```

4. Append all marker strings to `current_assistant_text`:

   ```python
   updated_text = current_assistant_text + "".join(all_marker_texts)
   ```

5. Return `updated_text`.

### 6.2 Engine integration

In the streaming engine (`ResponsesEngine`):

* `assistant_visible_text` is what the user sees (no markers).
* `assistant_internal_text` is what we **persist** to the chat message (visible text + markers).

Typical pattern:

```python
# While streaming text:
assistant_visible_text += delta
assistant_internal_text += delta
await events.delta(assistant_visible_text)

# Later, when persisting items:
assistant_internal_text = history_manager.persist_items_for_message(
    chat_key=history_key,
    message_id=ctx.metadata["message_id"],
    items=items_to_persist,
    model_id=ctx.model_id,
    openwebui_model_id=ctx.metadata["owui_model_id"],
    current_assistant_text=assistant_internal_text,
)
```

The message stored in `Chats` uses `assistant_internal_text` so that **markers are included** but remain invisible in the rendered UI.

---

## 7. Examples

### 7.1 Simple case – no markers

**Messages:**

```json
[
  { "role": "system", "content": "You are a helpful assistant." },
  { "role": "user",   "content": "Hi there!" },
  { "role": "assistant", "content": "Hello! How can I help?" }
]
```

**HistoryManager output:**

```jsonc
input_items = [
  {
    "role": "user",
    "content": [
      { "type": "input_text", "text": "Hi there!" }
    ]
  },
  {
    "role": "assistant",
    "content": [
      { "type": "output_text", "text": "Hello! How can I help?" }
    ]
  }
]

instructions = "You are a helpful assistant."
```

---

### 7.2 Assistant with a function call marker

Assume a previous turn persisted a tool call:

```json
{ "type": "function_call", "name": "calculator", "arguments": "{\"expression\":\"34234*pi\"}" }
```

under ULID `01HX4Y2VW5VR2Z2H`, and the stored assistant message text is:

```text
[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #
The result of 34234 × π is approximately 107,549.28.
```

**`build_input_from_messages(...)` result:**

```jsonc
input_items = [
  {
    "role": "user",
    "content": [
      { "type": "input_text", "text": "Calculate 34234 multiplied by pi." }
    ]
  },
  {
    "type": "function_call",
    "name": "calculator",
    "arguments": "{\"expression\":\"34234*pi\"}"
  },
  {
    "role": "assistant",
    "content": [
      {
        "type": "output_text",
        "text": "The result of 34234 × π is approximately 107,549.28."
      }
    ]
  }
]
```

No new tool execution happens; the Responses API simply sees that the tool call already occurred.

---

### 7.3 Mixed text + multiple markers

Given assistant content:

```text
[openai_responses:v2:function_call:AAAA...]: #
Tool output:

[openai_responses:v2:function_call_output:BBBB...]: #
Now, here's my final answer.

[openai_responses:v2:reasoning:CCCC...]: #
```

The reconstructed `input` sequence will be:

1. `function_call` payload for `AAAA`.
2. Assistant `output_text` `"Tool output:"`.
3. `function_call_output` payload for `BBBB`.
4. Assistant `output_text` `"Now, here's my final answer."`.
5. `reasoning` payload for `CCCC`.

The **order of segments** is preserved exactly as in the assistant text.

---

## 8. Edge cases & fallback behaviors

### 8.1 Unknown or broken markers

If a marker:

* doesn’t match the regex,
* refers to a ULID not found in the store, or
* refers to an item whose stored `model` is different from `openwebui_model_id`,

then:

* we **ignore that marker** and do not append any structured item,
* surrounding text segments still become `output_text` blocks.

### 8.2 Missing persistence

When:

* `chat_key` is missing or does not correspond to a chat,
* `openwebui_model_id` is `None`,
* `PERSIST_TOOL_RESULTS` or related knobs disable persistence, or
* the store raises an error,

we fall back to:

* building `input` only from visible text and user content,
* skipping DB interactions.

The manifold remains usable even if persistence is not set up.

### 8.3 Multiple system messages

If there are multiple `system` messages:

* `instructions` is taken from the **last** one.
* All system messages are omitted from `input_items`.

This matches prior production behavior.

### 8.4 Structured assistant content

If an assistant message’s `content` is not a string (e.g. a structured array introduced by a filter):

* We fall back to `raw = str(content)` before scanning for markers.
* This is a **best‑effort** behavior; in normal operation, assistant messages created by the manifold are simple strings with optional markers.

---

## 9. Testing guidelines

When implementing or modifying `HistoryManager`, tests should cover at least:

1. **Basic mapping**

   * User string → `input_text`.
   * User blocks with `text`, `image_url`, `input_file`.
   * Assistant plain text → `output_text`.
   * Developer messages → `role="developer"` with `input_text` blocks.

2. **System → instructions**

   * System messages don’t appear in `input_items`.
   * `instructions` is set to the last system content.

3. **Markers round‑trip**

   * Given stored items and markers in assistant text:

     * `build_input_from_messages` must emit the exact payloads.
     * Mixed segments (text before/after markers) preserve ordering.

4. **Model filtering**

   * When `HistoryStore.load_items` returns items for multiple models, only items whose `model` matches `openwebui_model_id` are used.

5. **Graceful degradation**

   * With missing/invalid `chat_key` or `openwebui_model_id`:

     * No crashes.
     * Assistant markers treated as normal text.
     * No calls to the store, or store errors are swallowed.

6. **Performance sanity**

   * Marker scanning is linear in the size of message text.
   * The store is called at most once per history transform, not once per marker.

---

## 10. Implementation notes & evolution

* **Current home**

  * The logic described here lives in `src/openai_responses_manifold/domain/history.py` as `HistoryManager` + `HistoryStore`.
  * Open WebUI integration (`OpenWebUIHistoryStore`) is documented in `openwebui_integration.md` and `markers_and_persistence.md`.

* **If you refactor again**

  * Keep the public contract of:

    * `build_input_from_messages(...)`
    * `persist_items_for_message(...)`

    intact, or update this doc first.
  * Preserve:

    * marker format (`openai_responses:v2:...`),
    * DB layout (`openai_responses_pipe`),
    * role & block mapping semantics described above.

By following this spec, you ensure that **history reconstruction** stays:

* Compatible with Open WebUI’s simple `messages[]` model,
* Correctly integrated with marker‑based persistence,
* Safe, deterministic, and easy to reason about for both humans and AI agents.