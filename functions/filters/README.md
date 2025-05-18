# Filters Guide

Filters intercept chat requests and responses. A filter is a Python file that exposes one or more of the functions `inlet(body)`, `outlet(body)` and `stream(event)`. Open WebUI executes them in that order around the pipe:

1. **Inlet** – receives the request payload before the pipe runs and may mutate it.
2. **Outlet** – called with the final response; can rewrite messages before they are sent back to the client.
3. **Stream** – optional hook invoked for every streamed chunk when the pipe returns a generator.

Only the functions that exist are executed.

```python
# basic filter

def inlet(body):
    body["messages"][-1]["content"] += " [filtered]"
    return body
```

## Valves and user settings

Like pipes, filters may define `Valves` and `UserValves` models. Values are hydrated by the loader and passed to the handler via the `valves` argument or `__user__.valves` when the function signature requests them. Setting `file_handler = True` tells the middleware that the filter processed uploaded files so they should not be handled again.

## Parameter injection

`process_filter_functions` inspects the handler signature and injects the same optional parameters available to pipes (`__event_emitter__`, `__event_call__`, `__files__`, `__user__`, etc.). A filter can therefore emit events or access tools just like a pipe.

Place filter modules in this folder and enable them through the WebUI interface. Multiple filters can be chained; their order is controlled by the `priority` value stored in the filter's valves.
