# Pipes Guide

A **pipe** is a single Python file containing a `Pipe` class. When a user selects a pipe as their chat model, Open WebUI loads the module and calls `Pipe.pipe()` for each request. Any enabled filters run first and may modify the payload before it reaches the pipe.

```python
# minimal pipe structure
class Pipe:
    async def pipe(self, body: dict) -> str:
        return "response"
```

Pipes can call external APIs, emit events back to the browser and manage their own state. Place new files in this folder so the loader can discover them.

## Loading custom pipes

`utils.plugin.load_function_module_by_id` reads the file, rewrites imports such as `from utils.chat` to `from open_webui.utils.chat`, installs any dependencies and executes the code in a temporary module. A triple quoted **frontmatter** block at the top of the file declares metadata:

```python
"""
requirements: httpx, numpy
other_field: demo
"""
```

The `requirements` line is installed with `pip` before the pipe runs. Arbitrary key/value pairs are stored as metadata and can be inspected later.

### Valves

Pipes may expose adjustable settings via `Valves` and `UserValves` Pydantic models. Values are stored in the database and injected on every call:

```python
from pydantic import BaseModel

class Valves(BaseModel):
    prefix: str = ">>"

class UserValves(BaseModel):
    shout: bool = False

class Pipe:
    def pipe(self, body, __user__, valves):
        msg = body["messages"][-1]["content"]
        if __user__.valves.shout:
            msg = msg.upper()
        return f"{valves.prefix} {msg}"
```

The server exposes endpoints to update these values without re-uploading the code.

### Manifold pipes

A pipe can provide multiple sub‑models by defining a `pipes` attribute. This may be a list, a function or an async function returning items of the form `{"id": "sub", "name": "Sub Pipe"}`. `get_function_models` in the backend flattens these into separate models so the user can pick which one to run.

## Parameter injection

`functions.generate_function_chat_completion` inspects the `pipe` signature and only passes the arguments you declare. Useful names include:

- `__event_emitter__` / `__event_call__` – send events or display confirmation dialogs in the UI.
- `__chat_id__`, `__session_id__`, `__message_id__` – conversation identifiers.
- `__files__` – uploaded file metadata.
- `__user__` – dictionary with user details plus optional `UserValves`.
- `__tools__` – mapping of registered tools.
- `__messages__` – raw message history.

Extra context can be injected with the same names when calling the pipe.

### Streaming and return types

The `pipe` method may return a string, a dictionary, a generator/async generator that yields chunks or a `StreamingResponse`. When `stream=True` is set in the payload the middleware wraps the generator so each chunk is processed by outlet filters and forwarded to the client.

## Invoking tools from a pipe

Tools are provided through the `__tools__` dictionary. Each entry exposes the JSON spec and a callable function:

```python
class Pipe:
    async def pipe(self, body, __tools__):
        add = __tools__["add"]["callable"]
        result = await add(a=1, b=2)
        return str(result)
```

`utils.tools.get_tools` converts each tool into an async callable and attaches metadata such as whether it handles its own files.

## Pipe lifecycle

Loaded pipe modules are cached in `request.app.state.FUNCTIONS`. `Valves` and `UserValves` are hydrated before each execution and the pipe is invoked with the prepared parameters:

```python
pipe = function_module.pipe
params = get_function_params(function_module, form_data, user, extra_params)
res = await execute_pipe(pipe, params)
```

Reload the server or update the valves to pick up changes. See `external/MIDDLEWARE_GUIDE.md` for a deeper walk through of the request pipeline.
