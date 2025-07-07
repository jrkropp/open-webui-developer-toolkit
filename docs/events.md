# Events: Communicating with the Frontend

Events allow backend components (**Pipes**, **Filters**, and **Tools**) to directly interact with Open WebUI’s frontend in real-time.

Two main helpers are provided for this purpose:

* **`__event_emitter__`** – *(one-way communication)* Fire-and-forget events to send immediate updates to the frontend.
* **`__event_call__`** – *(two-way communication)* Prompt the frontend and wait for a user response (awaitable).

Each event is represented as a dictionary with a **type** and **data** payload:

```python
{
    "type": "<event_type>",
    "data": { ... }
}
```

---

## 📑 Supported Event Types

| Event Type                                       | Notes                                                                                     |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| **`status`**                                     | Show a progress/status update (e.g. loading states, intermediate steps).                  |
| **`chat:message:delta`** / **`message`**         | Stream partial text content (append incremental chunks of a response).                    |
| **`chat:message`** / **`replace`**               | Replace or set the entire message content (usually used to finalize a streamed response). |
| **`chat:completion`**                            | Explicitly denote the final completion of a chat response (advanced use).                 |
| **`chat:message:files`** / **`files`**           | Attach or update files associated with a message (for uploads or outputs).                |
| **`chat:title`**                                 | Dynamically set or update the conversation title.                                         |
| **`chat:tags`**                                  | Update tags associated with the conversation.                                             |
| **`source`** / **`citation`**                    | Add reference citations or other source data to a message.                                |
| **`notification`**                               | Display a toast notification (`success`, `error`, `info`, or `warning`) to the user.      |
| **`confirmation`** *(requires `__event_call__`)* | Prompt the user to confirm or cancel an action (yes/no dialog).                           |
| **`input`** *(requires `__event_call__`)*        | Prompt the user for text input (with a dialog) and await their response.                  |
| **`execute`** *(requires `__event_call__`)*      | Execute client-side JavaScript and return the result.                                     |

---

## Using Events from Tools / Filters / Pipes

To use these event helpers, declare them as parameters in your component’s function signature (Pipe, Filter, or Tool). Open WebUI will automatically inject the appropriate `__event_emitter__` and `__event_call__` when invoking your function.

For example:

```python
async def pipe(
    self,
    body: dict,
    __event_emitter__: Callable[[dict], Awaitable[None]] = None,
    __event_call__: Callable[[dict], Awaitable[Any]] = None,
):
    # Send a status update
    await __event_emitter__({
        "type": "status",
        "data": {"description": "Processing started...", "done": False}
    })
```

> **Note:** Only parameters that you explicitly declare in the function signature  will be injected. If you leave out `__event_emitter__` or `__event_call__`, those helpers will not be available in your function.

---

### Detailed Examples of Each Event Type

#### ✅ Status Updates (`status`)

Immediately inform the user about backend processing status or progress:

```python
await __event_emitter__({
    "type": "status",
    "data": {"description": "Loading results...", "done": False}
})
```

*(The `done` flag can be toggled to indicate whether the process is finished. For example, set `"done": True` on the final status update.)*

---

#### ✅ Incremental Text Updates (`chat:message:delta` or `message`)

Stream content to the user incrementally (e.g. token-by-token or chunk-by-chunk):

```python
await __event_emitter__({
    "type": "chat:message:delta",  # or simply "message"
    "data": {"content": "Partial response chunk "}
})

# ... Later in your code, send more chunks as they are generated:
await __event_emitter__({
    "type": "chat:message:delta",
    "data": {"content": "next part of the response..."}
})
```

Each `chat:message:delta` event appends text to the current message in the UI. Use this for real-time streaming of a response.

---

#### ✅ Full Message Replacement (`chat:message` or `replace`)

Replace the entire content of the current message (often used to signal completion of streaming):

```python
await __event_emitter__({
    "type": "chat:message",  # or "replace"
    "data": {"content": "Here is the final complete response."}
})
```

This sets the message content in the UI to the provided text, replacing any partially streamed content.

---

#### ✅ Chat Completion (`chat:completion`)

The `chat:completion` event explicitly marks the end of an assistant's response. The `middleware.py` automatically emits a completion event upon finishing, so in most cases you don't need to manually emit this event. However, it’s especially useful during streaming or when including additional metadata such as token usage, dynamically setting the chat title, or explicitly handling errors.

> **Important:** Always include the `content` field (even if empty `""`) to prevent UI issues, especially if users navigate away mid-stream.  Empty content field will not replace previously emited text.

**Supported fields within `data`:**

| Field         | Description                                                           |
| ------------- | --------------------------------------------------------------------- |
| **`content`** | *(required)* Text of the message (use `""` if no additional content). |
| **`done`**    | *(optional)* Boolean to explicitly indicate the end of streaming.     |
| **`title`**   | *(optional)* Set or update the conversation title dynamically.        |
| **`usage`**   | *(optional)* Provide token usage details (prompt, completion, total). |
| **`error`**   | *(optional)* Indicate an error occurred (with message details).       |

##### Basic Example

Emit a complete assistant response with content:

```python
await __event_emitter__({
    "type": "chat:completion",
    "data": {
        "content": "Here is your complete answer.",
        "done": True,
        "title": "Summary of Today's Meeting"
    }
})
```

This finalizes the response and updates the chat title.

##### Example with Usage Data

Finalize the response and include token usage statistics:

```python
await __event_emitter__({
    "type": "chat:completion",
    "data": {
        "content": "",
        "done": True,
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 30,
            "total_tokens": 45
        },
        "title": "API Usage Summary"
    }
})
```

Here, `content` is empty since we don't want to overwrite previously yield text. The UI finalizes the message, updates the title, and optionally records token usage stats.

##### Example Emitting Errors

Explicitly indicate an error or aborted generation to the user:

```python
await __event_emitter__({
    "type": "chat:completion",
    "data": {
        "content": "",
        "done": True,
        "error": {
            "message": "Model response timed out. Please try again."
        }
    }
})
```

The frontend marks the chat as complete and prominently displays the error, ensuring users aren’t left waiting indefinitely.

---

#### ✅ Attaching Files (`chat:message:files` or `files`)

Attach or update files in the current message. Files are stored under
`open_webui.config.UPLOAD_DIR` (by default `<repo>/backend/data/uploads`).
Since this code runs server side, you can save the files directly:

```python
from open_webui.config import UPLOAD_DIR
from pathlib import Path
import uuid

img_id = str(uuid.uuid4())
img_path = Path(UPLOAD_DIR) / f"{img_id}_plot.png"
img_path.write_bytes(generated_png_bytes)

txt_id = str(uuid.uuid4())
txt_path = Path(UPLOAD_DIR) / f"{txt_id}_report.txt"
txt_path.write_text(report_text)

await __event_emitter__({
    "type": "files",  # or "chat:message:files"
    "data": {
        "files": [
            {
                "id": img_id,
                "type": "image",
                "name": "plot.png",
                "url": f"/api/v1/files/{img_id}"
            },
            {
                "id": txt_id,
                "type": "file",
                "name": "report.txt",
                "url": f"/api/v1/files/{txt_id}"
            }
        ]
    }
})
```

Each item should include its `id`, human-readable `name`, and `type`
(for example `"image"`, `"file"`, `"doc"`).  The event only updates the UI; files
must already exist in `UPLOAD_DIR` as shown above.

---

#### ✅ Updating Conversation Title (`chat:title`)

Dynamically set or update the title of the current conversation:

```python
await __event_emitter__({
    "type": "chat:title",
    "data": {"title": "Discussion about Event Emitters"}
})
```

This changes the title displayed for the chat (useful if your tool or pipe determines a more context-appropriate title).

---

#### ✅ Updating Conversation Tags (`chat:tags`)

Update the tags associated with the current conversation (for organizational or filtering purposes):

```python
await __event_emitter__({
    "type": "chat:tags",
    "data": {"tags": ["python", "events", "examples"]}
})
```

This replaces the conversation’s tags with the provided list.

---

#### ✅ Citations and Sources (`source` or `citation`)

Emit citation data alongside numbered placeholders in your message text. The
frontend pairs each `[n]` marker with the corresponding entry from the emitted
`sources` list.

```python
if __event_emitter__:
    await __event_emitter__(
        {
            "type": "source",        # "source" (preferred) or "citation" for backwards compatibility
            "data": {
                "source": {"name": "NASA"},
                "document": [
                    "299 792 458 metres per second is the exact speed of light in vacuum."
                ],
                "metadata": [
                    {
                        "source": "https://science.nasa.gov/ems/03_movinglight/",
                        "date_accessed": "2025-06-24",
                    }
                ],
            },
        }
    )
```

You can stream citations incrementally (yield text such as `[1]` then emit a
matching `source` event) or send them all at once using
`{"type": "chat:completion", "data": {"content": "", "sources": [...]}}` at the
end of the response. See the
[Citations Example Pipe](../functions/pipes/citations_example) for a full
demonstration.

This event lets you attach source links or documents to a message. The UI will
render the markers as clickable references and display their details in a modal.

---

#### ✅ Notifications (`notification`)

Show a toast notification to the user (non-intrusive alert at the bottom/top of the app):

```python
await __event_emitter__({
    "type": "notification",
    "data": {
        "type": "success",  # "info", "warning" or "error" are also valid
        "content": "Your data was successfully saved!"
    }
})
```

This displays a small success toast. The `type` field controls the style of the notification and `content` is the text shown to the user.

---

#### ✅ User Confirmation (`confirmation`) *(requires `__event_call__`)*

Prompt the user with a confirmation dialog and wait for their response:

```python
confirmed = await __event_call__({
    "type": "confirmation",
    "data": {
        "title": "Confirm Action",
        "message": "Do you want to proceed?"
    }
})

if confirmed:
    # continue with the action
else:
    # action was cancelled by the user
```

The code pauses until the user clicks **Confirm** or **Cancel**. The `confirmed` variable will be truthy if the user confirmed.

---

#### ✅ User Input Prompt (`input`) *(requires `__event_call__`)*

Prompt the user with an input dialog and retrieve their text input:

```python
user_name = await __event_call__({
    "type": "input",
    "data": {
        "title": "Input Required",
        "message": "Enter your name:",
        "placeholder": "Name",
        "value": ""
    }
})
```

After the user enters text and submits, `user_name` will contain their input (e.g., `"Alice"`). You can then use `__event_emitter__` if you want to provide feedback or use that input in a follow-up event.

---

#### ✅ Executing JavaScript (`execute`) *(requires `__event_call__`)*

Run client-side JavaScript code on the user's browser and get the result:

```python
result = await __event_call__({
    "type": "execute",
    "data": {"code": "return window.location.href;"}
})
```

This executes the provided JavaScript in the user's browser and populates `result` with its return value. For example, the snippet above returns the current page URL. Use this for advanced integrations that need to query or manipulate the client environment.

---

## 🔧 Under the Hood:
### How __event_emitter__ and __event_call__ are passed to your pipe / filter / tool

When Open WebUI calls your component, it prepares the event helpers using metadata from the current request (like session and message IDs). It then inspects your function’s signature and injects only the parameters you have defined.

**Simplified internal mechanism (from Open WebUI’s loader):**

```python
extra_params = {
    "__event_emitter__": get_event_emitter(metadata),
    "__event_call__": get_event_call(metadata),
    "__chat_id__": metadata.get("chat_id"),
    "__session_id__": metadata.get("session_id"),
    "__message_id__": metadata.get("message_id"),
    # ... other context params ...
}

# Only pass parameters that the function actually accepts:
sig = inspect.signature(function_module.pipe)
params = {k: v for k, v in extra_params.items() if k in sig.parameters}

result = await function_module.pipe(**params)
```

In summary, Open WebUI automatically provides `__event_emitter__` and `__event_call__` (along with other context like IDs) to your function, but **only** if your function is defined to accept them.

### Creating Event Emitters Manually (Advanced)

In rare cases, you might want to create event emitter/caller outside of the automatic injection (for example, in a standalone script or for testing). You can manually construct these helpers by providing the required metadata:

```python
from open_webui.socket.main import get_event_emitter, get_event_call

metadata = {
    "session_id": "user-session-id",
    "chat_id": "chat-id",
    "message_id": "message-id"
}

event_emitter = get_event_emitter(metadata)       # create an emitter (update_db=True by default)
event_call = get_event_call(metadata)
```

Now you can use `event_emitter({...})` or `await event_call({...})` just like the injected versions. Make sure to supply real session/chat IDs from an active context.

### Detailed Event Behavior
#### Using `__event_emitter__` (Broadcast)

Events emitted via `__event_emitter__` are broadcast to **all** active sessions for the current user (including the session that triggered the event). Under the hood, these events use a WebSocket broadcast (Socket.IO) to update every open client interface for that user.

By default, certain event types are automatically persisted to the database as soon as they are emitted, to ensure no data is lost if the user disconnects mid-stream:

* **`status`** – status updates are added to the message’s status history.
* **`message`** – content appended via incremental message events is saved to the message.
* **`replace`** – the replaced full content is immediately saved/updated.

For example, sending a status update will persist that status to the chat history:

```python
await __event_emitter__({
    "type": "status",
    "data": {"description": "Loading...", "done": False}
})
```

If you wish to emit events without automatically updating the database (perhaps for purely transient UI updates), you can disable persistence when getting the emitter:

```python
custom_emitter = get_event_emitter(metadata, update_db=False)
```

*(Using a custom emitter like this is advanced usage; typically you can rely on the default behavior.)*

#### Using `__event_call__` (Await Response)

Events sent via `__event_call__` go to **only the requesting session** (the single user/browser that triggered the call) and pause execution until a response is received. Internally, this utilizes Socket.IO’s RPC-like call mechanism to ensure the response corresponds to the correct session and event.

For example, prompting for input will send an event to that user’s browser and wait for the answer:

```python
user_input = await __event_call__({
    "type": "input",
    "data": {
        "title": "Input Required",
        "message": "Enter your name:",
        "placeholder": "Name",
        "value": ""
    }
})
```

The code will resume only after the user provides input (or closes the dialog). Under the hood, Open WebUI uses a `sio.call(...)` to implement this behavior, tying the response to the specific session that initiated the event.

### Event Persistence in Database

Some event types **immediately persist** their data to the database to guard against interruptions (for example, if a user closes the browser mid-stream, the partial content is not lost). Other events only update the UI state and the in-memory chat, and are persisted only when the message is finalized.

**Events that persist automatically upon emission:**

* **`status`** – The status update is added to the message's status history log.
* **`message`** – Incremental content (appended text) is saved to the message content.
* **`replace`** – The message content is created or replaced fully in the database.

You can manually persist or update message content at any time by writing to the database. For example, to update a message's content directly:

```python
Chats.upsert_message_to_chat_by_id_and_message_id(
    chat_id,
    message_id,
    {"content": new_content}
)
```

> **Note:** If you manually persist data in the middle of streaming, be aware that when the message completes normally, the final write might override your manual update. Automatic persistence will typically ensure the final state is saved.

### How Frontend Processes Events

On the frontend side, the Open WebUI client listens for these events via WebSockets and updates the UI in real-time. For instance, the `Chat.svelte` component might handle incoming events as follows:

```svelte
$socket.on('chat-events', event => {
    const { type, data } = event;

    if (type === 'chat:message:delta' || type === 'message') {
        // Append incoming content to the current message
        message.content += data.content;
    } else if (type === 'chat:message' || type === 'replace') {
        // Replace the message content entirely
        message.content = data.content;
    } else if (type === 'status') {
        // Update message status (e.g., show or update a loading indicator)
        updateStatus(message, data);
    }
    // ... handle other event types similarly ...
});
```

The frontend logic ensures each event type updates the chat UI appropriately (streaming text, updating titles, showing notifications, etc.). As a developer, you don’t usually need to write any frontend code — just emitting or calling the events from the backend will trigger the intended UI updates automatically.
