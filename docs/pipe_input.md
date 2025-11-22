# Pipe Input Reference

This document summarizes the data structures passed to a pipe's `pipe()` method. Each argument is described in its own section so automated tools can easily locate the information they need.

## Function Signature

```python
async def pipe(
    self,
    body: dict[str, Any],
    __user__: dict[str, Any],
    __request__: Request,
    __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
    __event_call__: Callable[[dict[str, Any]], Awaitable[Any]],
    __files__: list[dict[str, Any]],
    __metadata__: dict[str, Any],
    __tools__: dict[str, Any],
) -> AsyncIterator[str]:
    ...
```

The pipe receives a JSON-like payload describing the chat request (`body`) plus several helper objects such as user info and metadata. The pipe yields its response text as an asynchronous stream.

## 1. `body`

Holds the conversation request. Typical keys include:

* `stream` – `true` for partial streaming.
* `model` – the model identifier, e.g. `"openai_responses.gpt-4.1"`.
* `messages` – list of `{role, content}` chat messages.
* `stream_options` – options such as `include_obfuscation: false` (only when `stream: true`).
* `tools` – list of tool/function definitions. This field is **only** present
  when native function calling is enabled for the selected model. When filled in,
  each entry matches the OpenAI Completions API schema so it can be sent
  directly to OpenAI.

Example:

```jsonc
{
  "stream": true,
  "model": "openai_responses.gpt-4.1",
  "messages": [
    {"role": "system", "content": "System prompt text..."},
    {"role": "user", "content": "User question..."}
  ],
  "stream_options": {"include_obfuscation": false},
  "tools": [
    {
      "type": "function",
      "name": "calculator",
      "description": "Accurate math expressions, etc.",
      "parameters": {
        "type": "object",
        "properties": {
          "expression": {"type": "string", "description": "..."}
        },
        "required": ["expression"]
      }
    }
  ]
 }
```

When native function calling is **disabled**, the `tools` key will be absent and
Open WebUI runs tools internally. In that case use the `__tools__` argument
described later.

## 2. `__user__`

Information about the current user. Common keys:

* `id` – user UUID
* `email` – email address
* `name` – full or display name
* `role` – role such as `admin` or `user`
* `valves` – optional flag string enabling features or logging

Example:

```jsonc
{
  "id": "91216674-177d-4d5b-8a0b-a2d83783eb54",
  "email": "user@example.com",
  "name": "John Doe",
  "role": "admin",
  "valves": "CUSTOM_LOG_LEVEL='DEBUG' ..."
}
```

If omitted, `CUSTOM_LOG_LEVEL` defaults to the sentinel value `INHERIT`.  Any
field set to `INHERIT` is ignored, so the pipe's configured log level is used.
The selected level applies only to that request because the pipeline tracks the
active log level using a `ContextVar`.

## 3. `__request__`

The FastAPI `Request` object for the incoming HTTP call. A pipe can read headers or query parameters from here if needed.

## 4. `__event_emitter__` and `__event_call__`

Async callbacks to emit events or invoke additional workflow steps. Pipes that do not use events can safely ignore them.

## 5. `__files__`

List of uploaded file metadata. Each entry contains a `type` (usually `file`) and a nested `file` object with details such as `filename`, `hash`, and `data.content`.

Example:

```jsonc
[
  {
    "type": "file",
    "file": {
      "id": "c84fc997-c695-45f1-b031-258a26a95f3b",
      "user_id": "91216674-177d-4d5b-8a0b-a2d83783eb54",
      "hash": "...",
      "filename": "document.pdf",
      "data": {"content": "<base64 or text content>"},
      "meta": {
        "name": "document.pdf",
        "content_type": "application/pdf",
        "size": 123456,
        "data": {},
        "collection_name": "file-c84fc997-c695-..."
      },
      "created_at": 1747960134,
      "updated_at": 1747960134
    },
    "id": "c84fc997-c695-45f1-b031-258a26a95f3b",
    "url": "/api/v1/files/c84fc997-c695-45f1-b031-258a26a95f3b",
    "name": "document.pdf",
    "collection_name": "file-c84fc997-c695-45f1-b031-258a26a95f3b",
    "status": "uploaded",
    "size": 123456,
    "error": "",
    "itemId": "6d4fe4ad-e79f-4732-9564-c0031ca73dbe"
  }
]
```

## 6. `__metadata__`

Additional identifiers and settings for the conversation. Useful keys:

* `user_id`, `chat_id`, `message_id`, `session_id`
* `filter_ids`, `tool_ids`, `tool_servers`
* `features` – toggles such as `image_generation` or `web_search`
* `variables` – placeholders like `{{CURRENT_DATE}}`
* `model` – detailed model configuration
* `direct` – `true` when the pipe is invoked outside the chat UI
* `task` – name of the background task if applicable
* `task_body` – original request payload when `task` is set

Example:

```jsonc
{
  "user_id": "00000000-0000-0000-0000-000000000000",
  "chat_id": "11111111-1111-1111-1111-111111111111",
  "message_id": "22222222-2222-2222-2222-222222222222",
  "session_id": "ABC123456SESSIONID",
  "filter_ids": [],
  "tool_ids": null,
  "tool_servers": [],
  "features": {
    "image_generation": false,
    "code_interpreter": false,
    "web_search": false
  },
  "variables": {
    "{{USER_NAME}}": "Jane Doe [Example Corp]",
    "{{USER_LOCATION}}": "Unknown",
    "{{CURRENT_DATETIME}}": "2025-05-22 12:00:00",
    "{{CURRENT_DATE}}": "2025-05-22",
    "{{CURRENT_TIME}}": "12:00:00",
    "{{CURRENT_WEEKDAY}}": "Thursday",
    "{{CURRENT_TIMEZONE}}": "America/New_York",
    "{{USER_LANGUAGE}}": "en-US"
  },
  "model": {
    "id": "openai_responses.gpt-4.1",
    "name": "OpenAI: GPT-4.1 (Preview) ★★☆☆",
    "object": "model",
    "created": 1747769575,
    "owned_by": "openai",
    "pipe": {
      "type": "pipe"
    },
    "info": {
      "id": "openai_responses.gpt-4.1",
      "user_id": "00000000-0000-0000-0000-000000000000",
      "base_model_id": null,
      "name": "OpenAI: GPT-4.1 (Preview) ★★☆☆",
      "params": {
        "function_calling": "native",
        "system": "You are a helpful assistant. Current date: {{CURRENT_DATE}}"
      },
      "meta": {
        "profile_image_url": "data:image/png;base64,PLACEHOLDER_IMAGE_BASE64==",
        "description": "⚠️ Experimental Preview ⚠️ This is a next-gen instruction-following model.",
        "capabilities": {
          "vision": true,
          "file_upload": true,
          "web_search": false,
          "image_generation": false,
          "code_interpreter": false,
          "citations": true,
          "usage": true
        },
        "suggestion_prompts": null,
        "tags": [
          {
            "name": "⚡Base Model"
          }
        ],
        "filterIds": [
          "web_search_toggle"
        ]
      },
      "access_control": null,
      "is_active": true,
      "updated_at": 1747778445,
      "created_at": 1747778445
    },
    "actions": [],
    "filters": [
      {
        "id": "create_image_filter",
        "name": "Create an Image",
        "description": "Add the image_generation tool.",
        "icon": "data:image/svg+xml;base64,PLACEHOLDER_SVG_ICON=="
      },
      {
        "id": "web_search_toggle_filter",
        "name": "Web Search",
        "description": "Enable web search when toggle is active.",
        "icon": "data:image/svg+xml;base64,PLACEHOLDER_SVG_ICON=="
      }
    ],
    "tags": [
      {
        "name": "⚡Base Model"
      }
    ]
  },
  "direct": false,
  "task": "title_generation", // only present when spawned by a task
  "task_body": {"model": "gpt-4o", "...": "..."},
  "function_calling": "native"
}
```

## 7. `__tools__`

Dictionary of tool definitions keyed by tool name. This argument is populated
whenever one or more tools are selected and is available regardless of whether
native function calling is enabled. It is generally safer to rely on this
mapping than on `body['tools']` because the structure stays consistent and each
entry exposes a callable for direct invocation.

Each entry includes a `tool_id`, a `callable`, a `spec` describing parameters,
and optional metadata.

Example:

```jsonc
{
  "calculator": {
    "tool_id": "calculator",
    "callable": "<function Tools.calculator at 0x12345>",
    "spec": {
      "name": "calculator",
      "description": "Accurate math expressions...",
      "parameters": {
        "type": "object",
        "properties": {
          "expression": {
            "type": "string",
            "description": "A SymPy-compatible math expression."
          }
        },
        "required": ["expression"]
      }
    },
    "metadata": {"file_handler": false, "citation": false}
  }
}
```
