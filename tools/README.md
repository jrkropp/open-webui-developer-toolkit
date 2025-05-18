# Tools Guide

Tools are standalone Python modules that expose one or more callable functions. Pipes look them up by name and invoke them to perform work such as calculations or web requests.

A simple tool defines a `spec` describing the function and an `invoke()` coroutine:

```python
spec = {
    "name": "hello_world",
    "description": "Return a friendly greeting",
    "parameters": {"type": "object", "properties": {}}
}

async def invoke(args: dict) -> str:
    return "hello"
```

Place new tool modules in this folder. `utils.plugin.load_tool_module_by_id` installs any dependencies declared in the optional frontmatter and returns a `Tools` object containing the functions.

## Registry and invocation

`utils.tools.get_tools` retrieves tool modules and converts each function into an async callable. Type hints and docstrings are parsed with `convert_function_to_pydantic_model` so the JSON `spec` matches the OpenAI tool format. The returned dictionary maps function names to `{"callable": func, "spec": spec, ...}`.

When a pipe needs a tool it selects it from this mapping and awaits the callable:

```python
add = tools["add"]["callable"]
result = await add(a=1, b=2)
```

Tools may also come from **tool servers** which serve an OpenAPI document. `get_tools` downloads the spec, wraps each endpoint and proxies the request when called.

## Events and callbacks

Tool functions can communicate with the browser. If the signature includes `__event_emitter__` or `__event_call__` the middleware injects helpers that send structured websocket events:

```python
async def example_tool(__event_emitter__, __event_call__):
    await __event_emitter__({"type": "status", "data": {"description": "Loading", "done": False}})
    ok = await __event_call__({"type": "confirmation", "data": {"title": "Continue?", "message": "Run step?"}})
    if ok:
        await __event_emitter__({"type": "replace", "data": {"content": "step complete"}})
```

`__event_call__` can also run JavaScript (`execute`) or prompt for input. The emitter recognises `message`, `replace`, `status`, `citation` and `notification` event types.
