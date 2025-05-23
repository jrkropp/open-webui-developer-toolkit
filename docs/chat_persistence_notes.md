# Open WebUI Chat Persistence Notes

This document summarizes how chat messages are stored in the upstream Open WebUI project based on a review of the source code.

## Chat history structure
- Each row in the `chat` table has a JSON column named `chat`.
- Chat history lives under `chat["history"]` which contains:
  - `currentId` – the latest message id.
  - `messages` – a dictionary mapping message ids to message objects.
- Messages typically include `id`, `parentId`, `role` and `content`. The `content` field is either a string or a list of typed blocks (e.g. `{type: "text", text: "hi"}`).

## `upsert_message_to_chat_by_id_and_message_id`
Located in `backend/open_webui/models/chats.py`. The helper merges the given
dictionary into an existing message entry or inserts it if the id is new. The
core logic looks like:

```python
if message_id in history.get("messages", {}):
    history["messages"][message_id] = {
        **history["messages"][message_id],
        **message,
    }
else:
    history["messages"][message_id] = message
```

There is no schema validation – arbitrary keys are stored as provided. Custom
fields therefore persist in the database. They may be ignored by the default UI
unless additional code knows how to handle them.

Example of persisting a custom flag:

```python
Chats.upsert_message_to_chat_by_id_and_message_id(
    chat_id,
    "msg-123",
    {
        "role": "assistant",
        "content": "hello",
        "my_meta": {"notes": "stored as-is"},
    },
)
```

## Middleware serialization
- `backend/open_webui/utils/middleware.py` builds messages from `content_blocks`.
- Tool calls and code interpreter output are embedded inside the `content` string using `<details type="tool_calls">` or `<details type="code_interpreter">` tags.
- `convert_content_blocks_to_messages` converts a list of blocks to message objects. When a `tool_calls` block is encountered it emits:
  ```python
  {
      "role": "assistant",
      "content": serialize_content_blocks(temp_blocks),
      "tool_calls": block.get("content"),
  }
  ```
  followed by tool results as separate `{"role": "tool", ...}` entries.

At render time the `<details>` block is inserted directly into the content string
so progress and results can be displayed in the WebUI. Example output:

```html
<details type="tool_calls" done="true" id="123" name="my_tool" arguments="{}" result="\"ok\"">
<summary>Tool Executed</summary>
</details>
```

## Observations
- The database persists any extra keys but most helpers only read `role`, `content` and sometimes `files`.
- Embedding tool metadata directly inside `content` is how the UI displays call progress. Standalone fields like `tool_calls` are ignored by the renderer unless custom code processes them.
- Final message writes from the middleware overwrite `content` but keep previously stored fields due to the merge logic.

### Custom tool metadata
The `openai_responses` pipeline stores `function_call` and
`function_call_output` events using two arrays:

```json
{
  "tool_calls": [{"type": "function_call", "call_id": "c1", "name": "t"}],
  "tool_responses": [{"type": "function_call_output", "call_id": "c1", "output": "42"}]
}
```

`build_responses_payload()` reads these lists to reconstruct the conversation
history when the assistant is invoked again.
