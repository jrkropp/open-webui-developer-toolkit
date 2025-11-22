# Markers & Persistence

> **File:** `functions/pipes/openai_responses_manifold/docs/markers_and_persistence.md`
> **Scope:** How we **store** and **recover** hidden OpenAI Responses items in Open WebUI chats.

---

## 1. Why markers & persistence exist

Open WebUI stores chat messages in a simple shape:

```json
{ "role": "user" | "assistant", "content": "…" }
```

That’s great for the UI and filters, but the OpenAI **Responses API** deals in richer, structured items:

* `message` (visible assistant text)
* `function_call`
* `function_call_output`
* `web_search_call`
* `file_search_call`
* `code_interpreter_call`
* `reasoning`
* …and any new item types OpenAI adds.

We need to:

1. Keep a **faithful, machine‑readable history** of these items (so we can reuse tool results, reasoning, etc. on regenerate).
2. Stay 100% compatible with Open WebUI’s `messages[]` and its filters (which only see `role` + `content`).

The solution:

* Store **heavy structured payloads** in a dedicated block in the chat document.
* Inject tiny, **invisible markers** into assistant message text that point to those stored payloads.
* On later turns, **rebuild** the Responses API `input[]` by:

  * Scanning assistant text for markers,
  * Loading items by ULID from the DB,
  * Re‑interleaving them with visible assistant text.

This document covers:

* The **marker wire format** (`[openai_responses:v2:…]: #`).
* The **persistent layout** under `chat.chat["openai_responses_pipe"]`.
* How `core.markers`, `HistoryStore`, and `OpenWebUIHistoryStore` fit together.
* Invariants you must not break.

For the **full history reconstruction algorithm**, see:

> `functions/pipes/openai_responses_manifold/docs/history_manager.md`

---

## 2. Layers & responsibilities

Markers & persistence are split across three layers.

### 2.1 `core.markers` (pure string logic)

Located at:
`src/openai_responses_manifold/core/markers.py`

Responsibilities:

* Define the marker **format** and version.
* Generate ULIDs.
* Build raw marker payload strings.
* Wrap markers into invisible Markdown.
* Detect, extract, parse, and split markers in assistant text.

This module has **no DB or Open WebUI imports**. If you change the marker format, you change it **here**.

### 2.2 `domain.history` (`HistoryManager`)

Located at:
`src/openai_responses_manifold/domain/history.py`

Responsibilities:

* Pure “domain” logic, DB‑agnostic.
* Uses `core.markers` + a `HistoryStore` implementation to:

  * Build Responses `input[]` from `messages[]`, markers, and stored items:
    `build_input_from_messages(...)`.
  * Persist new items and append markers into assistant text:
    `persist_items_for_message(...)`.

This layer knows nothing about `Chats`; it only sees an abstract `HistoryStore`.

Details of the history algorithm live in:

> `history_manager.md` (this file just describes how markers & storage plug into that).

### 2.3 `openwebui.store.OpenWebUIHistoryStore`

Located at:
`src/openai_responses_manifold/openwebui/store.py`

Responsibilities:

* Implements `HistoryStore` **against Open WebUI’s `Chats` model**.
* Owns the `chat.chat["openai_responses_pipe"]` JSON layout.
* Bridges between:

  * `history_key` (`{"chat_id": ..., "pipe_id": ...}`),
  * ULIDs,
  * The actual stored payloads.

---

## 3. Marker format (v2)

### 3.1 Raw marker payload

The **raw marker payload** (before wrapping in Markdown) is:

```text
openai_responses:v2:<item_type>:<ULID>[?<k=v&...>]
```

Where:

* `openai_responses:v2:` — fixed prefix and version.

* `<item_type>` — 2–30 characters, `[a-z0-9_]`, e.g.:

  * `function_call`
  * `function_call_output`
  * `reasoning`
  * `web_search_call`

* `<ULID>` — 16‑char ID in Crockford Base32.

* Optional query string `?k=v&...` for metadata, e.g.:

  * `model=<openwebui_model_id>` to record which Open WebUI model produced the item.

**Example:**

```text
openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o
```

### 3.2 Wrapped form in assistant messages

Inside assistant `content`, markers are stored as **unused reference‑style Markdown links**:

```text
[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #
```

We normally surround each marker with newlines:

```text
\n[openai_responses:v2:function_call:01HX4Y2VW5VR2Z2H?model=openai_responses.gpt-4o]: #\n
```

Why this works:

* Reference links like `[id]: #` are typically **not rendered** as visible text if they are never referenced.
* The raw `content` string still contains the marker for parsing.
* Copy/paste from the UI tends to omit them, keeping user‑visible text clean.

### 3.3 `core.markers` API (conceptual)

Key pieces:

```python
MARKER_PREFIX     = "openai_responses:v2:"
ULID_LENGTH       = 16
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
```

#### `generate_ulid() -> str`

Generate a 16‑char Crockford Base32 ULID‑style ID:

```python
def generate_ulid() -> str:
    return "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(ULID_LENGTH))
```

#### `build_marker_payload(item_type: str, ulid: str, metadata: dict[str, str] | None = None) -> str`

Build the **raw** marker payload string:

```python
base = f"openai_responses:v2:{item_type}:{ulid}"
if metadata:
    return f"{base}?{urlencode(metadata)}"
return base
```

* `item_type` must match `[a-z0-9_]{2,30}` (raise if invalid).
* `metadata` is usually `{"model": <openwebui_model_id>}`.

#### `wrap_marker(payload: str) -> str`

Wrap the raw payload in an invisible Markdown reference:

```python
def wrap_marker(payload: str) -> str:
    # payload is "openai_responses:v2:..."
    return f"\n[{payload}]: #\n"
```

#### `contains_marker(text: str) -> bool`

Fast sentinel check:

```python
def contains_marker(text: str) -> bool:
    return MARKER_PREFIX in (text or "")
```

Used to short‑circuit regex work when no markers are present.

#### `extract_markers(text: str, *, parsed: bool = False) -> list[...]`

Scan `text` and return:

* Raw payload strings if `parsed=False`, e.g. `"openai_responses:v2:..."`.
* Parsed marker objects if `parsed=True`, e.g.:

  ```python
  {
    "item_type": "function_call",
    "ulid": "01HX4Y2VW5VR2Z2H",
    "metadata": {"model": "openai_responses.gpt-4o"},
  }
  ```

Internally uses a compiled regex that matches exactly the wrapped form `[...]: #`.

#### `parse_marker(payload: str) -> dict`

Parse a single raw marker payload (`"openai_responses:v2:..."`) into:

```python
{
  "item_type": str,
  "ulid": str,
  "metadata": dict[str, str],
}
```

This is what `HistoryManager` uses when iterating marker segments returned by `split_text_by_markers`.

#### `split_text_by_markers(text: str) -> list[Segment]`

Split `text` into segments in order:

```python
[
  { "type": "text",   "text": "visible text ..." },
  { "type": "marker", "marker": "openai_responses:v2:function_call:..." },
  ...
]
```

* `text` segments are the user‑visible text.
* `marker` segments carry the **raw payload** string (not the full `[...]: #` wrapper).

`HistoryManager` uses these segments to reconstruct `input[]` by:

* Emitting `output_text` for `text` segments.
* Looking up stored items by ULID for `marker` segments.

> If you change how markers are detected or parsed, change it **only here** and update the tests.

---

## 4. Persistent storage layout in `Chats`

Structured items (tool calls/results, reasoning, etc.) are stored under:

```python
chat.chat["openai_responses_pipe"]
```

This structure is owned by `OpenWebUIHistoryStore` and must stay backwards‑compatible.

### 4.1 Top‑level shape

```python
chat.chat["openai_responses_pipe"] = {
    "__v": 3,
    "items": {
        "<ULID>": {
            "model":      "<openwebui_model_id>",
            "created_at": <int_unix_timestamp>,
            "payload":    { ... },   # raw Responses item payload
            "message_id": "<message_id>",
        },
        ...
    },
    "messages_index": {
        "<message_id>": {
            "role": "assistant",
            "done": True,
            "item_ids": ["<ULID>", "<ULID2>", ...],
        },
        ...
    },
}
```

* `__v` — schema version for this subtree (currently `3`).
* `items` — global map of ULID → stored item metadata.
* `messages_index` — quick index of which item IDs belong to which assistant message.

Notes:

* Items are **not** embedded directly in messages; they live under `items[...]`.
* Assistant `content` only contains **markers** pointing to ULIDs.
* `messages_index` is a convenience index; **markers + items** are the canonical source of truth.

---

## 5. `HistoryStore`: saving & loading items

The domain layer uses a small abstraction for persistence:

```python
class HistoryStore(Protocol):
    def save_items(
        self,
        chat_key: dict,
        message_id: str,
        items: list[dict],
        model_id: str,  # OpenWebUI model id, e.g. "openai_responses.gpt-4o"
    ) -> list[str]:
        """Persist items and return their ULIDs."""

    def load_items(
        self,
        chat_key: dict,
        item_ids: list[str],
        model_id: str | None = None,
    ) -> dict[str, dict]:
        """Return {ulid: payload} for requested items (filtered by model if given)."""
```

* `chat_key` is opaque to the domain layer (usually at least `{"chat_id": ...}`).
* `model_id` is the **OpenWebUI model id** (not the bare OpenAI model id), used to avoid mixing items across models.

### 5.1 `OpenWebUIHistoryStore.save_items(...)`

Conceptual implementation:

1. **Locate chat**

   ```python
   chat_id = chat_key["chat_id"]
   chat = Chats.get_chat_by_id(chat_id)
   if not chat:
       return []
   ```

2. **Ensure `openai_responses_pipe` root**

   ```python
   pipe_root      = chat.chat.setdefault("openai_responses_pipe", {"__v": 3})
   items_store    = pipe_root.setdefault("items", {})
   messages_index = pipe_root.setdefault("messages_index", {})
   ```

3. **Ensure message index entry**

   ```python
   bucket = messages_index.setdefault(
       message_id,
       {"role": "assistant", "done": True, "item_ids": []},
   )
   ```

4. **Persist each item**

   ```python
   now = int(time.time())
   created_ids: list[str] = []

   for payload in items:
       ulid = generate_ulid()  # from core.markers

       items_store[ulid] = {
           "model":      model_id,      # full OpenWebUI model id
           "created_at": now,
           "payload":    payload,
           "message_id": message_id,
       }
       bucket["item_ids"].append(ulid)
       created_ids.append(ulid)
   ```

5. **Save chat**

   ```python
   Chats.update_chat_by_id(chat_id, chat.chat)
   ```

6. Return `created_ids`.

> **Important:** `save_items` **does not** create markers; it only writes items. Markers are created by `HistoryManager.persist_items_for_message` using these ULIDs.

### 5.2 `OpenWebUIHistoryStore.load_items(...)`

Conceptual implementation:

```python
chat_id = chat_key["chat_id"]
chat = Chats.get_chat_by_id(chat_id)
if not chat:
    return {}

items_store = chat.chat.get("openai_responses_pipe", {}).get("items", {})
result: dict[str, dict] = {}

for ulid in item_ids:
    item = items_store.get(ulid)
    if not item:
        continue
    if model_id is not None and item.get("model") != model_id:
        continue
    result[ulid] = item.get("payload") or {}

return result
```

* Filtering by `model_id` prevents cross‑contamination between different OpenWebUI models within the same chat.

---

## 6. How HistoryManager uses markers (high level)

The detailed algorithm is in `history_manager.md`; this section just shows how markers & persistence plug into it.

### 6.1 Rehydration (`build_input_from_messages(...)`)

`HistoryManager.build_input_from_messages(...)`:

1. Walks **assistant** messages in `messages[]`, looking for markers:

   ```python
   if isinstance(msg["content"], str) and contains_marker(msg["content"]):
       # collect ULIDs via extract_markers or split_text_by_markers
   ```

2. Collects ULIDs from all assistant messages and bulk‑loads them via:

   ```python
   payloads_by_ulid = store.load_items(chat_key, ulids, model_id=openwebui_model_id)
   ```

3. For each assistant message with markers:

   * Calls `split_text_by_markers(raw_content)` to get an ordered list of `{"type": "text"}` and `{"type": "marker"}` segments.
   * For each segment:

     * `text` → emit a `role="assistant"` `output_text` block (if non‑empty).
     * `marker` → use `parse_marker` → ULID → `payloads_by_ulid[ulid]` → append that payload item to `input[]`.

4. System, user, and developer messages are handled as described in `history_manager.md` (system → `instructions`, user → `input_text`/`input_image`/`input_file`, etc.).

The key point: markers + stored items are how we **re-insert structured history** (tool calls/outputs, reasoning, etc.) into `input[]` without re‑running tools.

### 6.2 Persistence (`persist_items_for_message(...)`)

When the engine wants to store new items (e.g. tool outputs, reasoning) for the current assistant message, it calls:

```python
new_text = history_manager.persist_items_for_message(
    chat_key=history_key,
    message_id=metadata["message_id"],
    items=items_to_persist,
    model_id=ctx.model_id,                   # OpenAI base model (unused by store)
    openwebui_model_id=ctx.metadata["owui_model_id"],
    current_assistant_text=assistant_text,   # visible text so far
)
```

Inside `persist_items_for_message`:

1. If `items` is empty → return `current_assistant_text` unchanged.

2. Call `HistoryStore.save_items(...)`:

   ```python
   ulids = store.save_items(
       chat_key=chat_key,
       message_id=message_id,
       items=items,
       model_id=openwebui_model_id,  # stored as "model" in the DB
   )
   ```

3. For each `(ulid, payload)` pair:

   * Determine `item_type`:

     ```python
     item_type = payload.get("type", "unknown")
     ```

   * Build raw payload string:

     ```python
     raw = build_marker_payload(
         item_type=item_type,
         ulid=ulid,
         metadata={"model": openwebui_model_id},
     )
     ```

   * Wrap it:

     ```python
     marker_text = wrap_marker(raw)  # "\n[openai_responses:v2:...]: #\n"
     ```

4. Append all `marker_text` segments to `current_assistant_text` and return the result.

The engine then:

* Stores this **full** assistant text (visible text + markers) in the chat DB.
* Continues to stream only the **visible** portion to the user.

---

## 7. Invariants & compatibility guarantees

When touching markers or the persistence layout, **do not break these**:

1. **Marker wire format**

   Must keep:

   ```text
   openai_responses:v2:<item_type>:<ULID>[?<k=v&...>]
   ```

   wrapped as:

   ```text
   [openai_responses:v2:...]: #
   ```

   You may add *new* query parameters (e.g. `kind=...`), but existing ones like `model` must keep working.

2. **DB layout**

   Under `chat.chat["openai_responses_pipe"]`:

   * Top‑level keys: `__v`, `items`, `messages_index`.
   * Per‑item keys: `model`, `created_at`, `payload`, `message_id`.

   You may add new keys, but must keep existing ones and their semantics.

3. **Model filtering**

   `HistoryStore.load_items(..., model_id=...)` must always filter by stored `item["model"]`, so we never reuse items across different OpenWebUI models.

4. **Marker invisibility**

   Markers must remain **invisible** in rendered messages:

   * Keep the reference‑style form `[...]: #`.
   * Do not change to a syntax that renders visible markdown.
   * Don’t prepend visible marker labels or numbering inside the reference line.

5. **Ordering**

   The reconstructed Responses `input[]` must preserve the **chronological** order of:

   * user messages,
   * assistant text segments,
   * tool calls,
   * tool outputs,
   * reasoning items,
   * etc.

   `split_text_by_markers` + `HistoryManager.build_input_from_messages` must uphold this ordering.

6. **Backwards compatibility with legacy manifold**

   Existing chats written by the **legacy** manifold must keep working:

   * The regex should still match old v2 markers.
   * The DB layout and keys must still parse correctly.

---

## 8. Edge cases & failure modes

* **Missing chat / missing `openai_responses_pipe`**

  * If `Chats.get_chat_by_id(chat_id)` returns `None`, or `openai_responses_pipe` is missing, `HistoryStore.load_items` returns `{}`.
  * Assistant markers that can’t be resolved are ignored.
  * History reconstruction falls back to visible text only.

* **Unknown or malformed markers**

  * If a marker doesn’t match the regex, or `parse_marker` fails:

    * Ignore that marker segment.
    * Treat it as if no structured item exists there.
    * Do **not** crash.

* **ULID not found / wrong model**

  * If a marker’s ULID isn’t in `items`, or the stored `model` doesn’t match the requested `model_id`:

    * `HistoryStore.load_items` simply omits it.
    * The corresponding marker segment produces no structured item.

* **Model changed mid‑thread**

  * If the user switches from, say, `openai_responses.gpt-4o` to `openai_responses.gpt-5`:

    * `load_items(..., model_id="openai_responses.gpt-5")` will not return items saved under `"openai_responses.gpt-4o"`.
    * Markers originating from the old model effectively become dead references for the new model.

* **Persistence disabled**

  * If higher layers decide not to persist certain items (e.g. `PERSIST_TOOL_RESULTS=False` or `PERSIST_REASONING_TOKENS="disabled"`):

    * They simply don’t call `persist_items_for_message` for those items.
    * Existing markers keep working; new runs just won’t add new ones.

---

## 9. Testing guidelines

When you change anything in `core.markers`, `OpenWebUIHistoryStore`, or the persistence layout, add tests in three areas:

### 9.1 `core.markers` unit tests

* **Round‑trip**:

  * `build_marker_payload` → `wrap_marker` → `extract_markers(parsed=True)` → `parse_marker` → original fields.

* **`split_text_by_markers`**:

  * Only text.
  * Text + one marker at end.
  * Text + multiple markers interleaved with text before, between, after.

* **`contains_marker`**:

  * Short strings with and without markers.
  * Non‑string inputs handled gracefully when converted to string upstream.

### 9.2 `OpenWebUIHistoryStore` tests

Using a stub or monkeypatched `Chats`:

* After `save_items`:

  * `openai_responses_pipe.items[ulid]` entries have `model`, `created_at`, `payload`, `message_id`.
  * `messages_index[message_id]["item_ids"]` lists the right ULIDs in order.

* `load_items`:

  * Returns only requested ULIDs.
  * Respects `model_id` filtering.

### 9.3 End‑to‑end marker + history tests

In tests for `HistoryManager` (see `history_manager.md`):

* Given assistant text containing markers and a fake `HistoryStore` with payloads:

  * `build_input_from_messages` should:

    * Emit items in the correct order (text segments + structured items).
    * Skip unknown ULIDs gracefully.

* Given some items and `current_assistant_text`:

  * `persist_items_for_message` should:

    * Call `save_items` with the right `model_id` (OpenWebUI model id).
    * Return text with wrapped markers appended.

---

## 10. Mental model

Keep this picture in your head:

* **Markers** are tiny, invisible **pointers** baked into assistant text.
* **`openai_responses_pipe`** is the **vault** where structured Responses items live.
* **HistoryManager** is the **bridge** that:

  1. Reads markers from assistant text,
  2. Fetches payloads from the vault via `HistoryStore`,
  3. Rebuilds a rich `input[]` for the Responses API, and
  4. Writes new markers when new items are persisted.

As long as you preserve this model:

* Old chats stay usable.
* Filters keep working on simple `messages[]`.
* You avoid re‑running tools or re‑fetching reasoning on regenerate.
* The manifold remains predictable and easy to reason about for both humans and AI agents.
