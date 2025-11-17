# WP-Logging – Standard, Session-Scoped Logging

## Context & Background

The OpenAI Responses Manifold is a single-file Open WebUI pipe generated from a modular package under:
- functions/pipes/openai_responses_manifold/src/openai_responses_manifold/

The current logging design uses a SessionLogger helper that:
- Stores a per-session session_id and log_level in ContextVars.
- Installs console + in-memory handlers on a named logger.
- Buffers log lines in memory (SessionLogger.logs[session_id]) so the engine can emit a single “Logs” citation at the end of a turn.

This mostly works, but configuration is not fully standard:
- SessionLogger.get_logger reconfigures the logger (handlers/filters) every time it’s called.
- Logging configuration is scattered instead of centralized.
- The pattern is conceptually close to “standard Python logging + ContextVars,” but not quite there.

We want to move to Option 2 from our design discussion:

A dedicated logging_config.py module that configures logging once, uses ContextVars for session_id + effective_log_level, and keeps the rest of the code using plain logging.getLogger(__name__).

The key idea: centralize logging wiring in one place, while preserving the current UX:
- Console logs (for operators).
- Per-session buffered logs as a single UI “Logs” citation.

### Goals
- Standardize logging so modules can just call logging.getLogger(__name__).
- Centralize logging configuration in a single logging_config.py (or similar) module.
- Preserve per-session isolation using ContextVars (no log bleeding across chats).
- Preserve the Logs citation behavior at the end of each turn.
- Keep changes focused to the manifold package (src/openai_responses_manifold/) without altering the external pipe interface.

### Non-Goals
- Do not change the Open WebUI pipe shape (Pipe, Valves, UserValves, pipe, pipes).
- Do not change semantic behavior of the engine / tool loops / history.
- Do not add or remove valves beyond what this WP requires (no big config redesign).
- Do not modify the bundler behavior in scripts/build.py beyond what’s strictly needed for imports to work.

---

## High-Level Design

We will introduce a dedicated logging configuration module, and then migrate existing code to use it.

### New module: logging_config.py

Create src/openai_responses_manifold/logging_config.py with the following responsibilities:
- Define ContextVars:
  - current_session_id: ContextVar[str | None]
  - current_log_level: ContextVar[int]
- Define a session-aware filter for log records:
  - Adds record.session_id from current_session_id (may be None).
  - Drops records with record.levelno < current_log_level.get().
- Define a console handler:
  - Writes to stdout.
  - Uses a simple, readable format, e.g. [LEVEL] [session_id] message.
- Define a memory handler per process** that writes to a per-session buffer**:
  - Use a module-level dict: SESSION_LOGS: dict[str, deque[str]].
  - Keys are session_id strings.
  - Values are deque[str] with a reasonable maxlen (e.g. 2000 lines).
  - emit():
    - If session_id is set, append a formatted line to the appropriate deque.
- Attach the filter + handlers once to a well-defined logger hierarchy:
  - Prefer a dedicated namespace, e.g. logger name prefix: "openai_responses_manifold".
  - Ensure all manifold modules use logger names under that prefix:
    - e.g. logging.getLogger(__name__) if __name__ starts with openai_responses_manifold.
  - Avoid changing root logger configuration outside this namespace.
- Provide public functions:

```
def set_session(session_id: str | None, level: int) -> tuple[token, token]:
    """Set the current session id and log level via ContextVars and return tokens for reset."""

def reset_session(tokens: tuple[token, token]) -> None:
    """Reset ContextVars to previous values using the provided tokens."""

def get_session_logs(session_id: str | None) -> list[str]:
    """Return a copy of buffered logs for the given session id (or empty list)."""

def clear_session_logs(session_id: str | None) -> None:
    """Clear buffered logs for the given session id, if any."""
```

You may adjust exact signatures if needed, but keep the semantics.

#### Session context helper (optional but preferred)
- Implement a small context manager in logging_config.py (or a tiny session_context.py) to simplify usage:

```
from contextlib import contextmanager

@contextmanager
def session_logging(session_id: str | None, level: int):
    tokens = set_session(session_id, level)
    try:
        yield
    finally:
        reset_session(tokens)
```

This makes it easy to scope current_session_id + current_log_level to a single pipe invocation.

#### Logs citation helper
- Implement a helper function in logging_config.py (or utils/logging.py if that’s where citation logic lives) that:
  - Takes:
    - session_id: str | None
    - event_emitter
    - source_name: str = "Logs"
  - Reads get_session_logs(session_id).
  - If non-empty:
    - Emits a single citation:

```
await emit_citation(event_emitter, "\n".join(lines), "Logs")
```

  - Calls clear_session_logs(session_id) to avoid leaks.

We will call this from the engine finally block.

---

## Step-by-Step Tasks

1. Introduce logging_config.py
   - Create src/openai_responses_manifold/logging_config.py.
   - Add ContextVars:
     - current_session_id
     - current_log_level
   - Add SESSION_LOGS: dict[str, deque[str]] (or defaultdict of deque, with maxlen).
   - Implement a logging.Filter subclass:
     - Adds session_id attribute.
     - Applies level filtering based on current_log_level.
   - Implement console handler:
     - StreamHandler(sys.stdout)
     - Formatter includes session_id in output.
   - Implement memory handler:
     - Custom logging.Handler subclass.
     - Emits to SESSION_LOGS[current_session_id].
   - Attach filter + handlers to the openai_responses_manifold logger hierarchy once:
     - Ensure idempotence (don’t reattach on repeated imports).
   - Implement the public helper functions:
     - set_session(session_id, level) -> tokens
     - reset_session(tokens)
     - get_session_logs(session_id) -> list[str]
     - clear_session_logs(session_id)
   - Optional: session_logging(session_id, level) context manager.

2. Migrate SessionLogger usage

Currently there is a SessionLogger class in utils/logging.py. We want to:
- Update src/openai_responses_manifold/utils/logging.py to become a thin facade or deprecation shim around logging_config.
- Option A (recommended):
  - Keep a SessionLogger class but have it delegate to logging_config:
    - SessionLogger.session_id → wrap logging_config.current_session_id.
    - SessionLogger.log_level → wrap logging_config.current_log_level.
    - SessionLogger.logs → wrap accessors that call get_session_logs / clear_session_logs.
    - SessionLogger.get_logger(name) → just logging.getLogger(name) (no handler reconfiguration).
    - Mark internal comments clearly: “Do not add new behavior here; see logging_config.py.”
  - Option B:
    - If safe, replace SessionLogger entirely with an import from logging_config and adjust call sites.
    - This is more invasive; prefer Option A unless you have time to clean up all references.
- Ensure no code path reconfigures handlers in get_logger anymore.
- Ensure all modules still obtain loggers via logging.getLogger(__name__) or SessionLogger.get_logger(__name__) (which now just forwards to standard logging).

3. Wire session context in Pipe.pipe

In src/openai_responses_manifold/main.py, inside Pipe.pipe:
- Import the session helpers from logging_config.py (or from the SessionLogger shim, whichever you decide):

```
from .logging_config import session_logging, set_session, reset_session
# or use SessionLogger’s wrapper if you keep that abstraction
```

- Determine the effective log level from valves:

```
import logging

effective_level = getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO)
```

- Grab session_id from __metadata__:

```
session_id = __metadata__.get("session_id")
```

- Wrap the core engine call in the session context:

```
async def pipe(...):
    ...
    session_id = __metadata__.get("session_id")
    effective_level = getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO)

    # Using context manager:
    async with session_logging(session_id, effective_level):
        result = await self.engine.run_streaming_turn(...)
        # (or non-streaming/task branches as needed)
        return result
```

If you prefer not to use a context manager, you can:

```
tokens = set_session(session_id, effective_level)
try:
    result = await self.engine.run_streaming_turn(...)
finally:
    reset_session(tokens)
```

- Remove direct manipulation of SessionLogger.session_id and SessionLogger.log_level from Pipe.pipe once logging_config is wired.

4. Move log flush into a single helper

In src/openai_responses_manifold/engine.py:
- Replace the existing _flush_logs implementation that touches SessionLogger.logs directly.
- Instead, import get_session_logs and clear_session_logs (or a higher-level helper) from logging_config.py.

Example shape:

```
from .logging_config import current_session_id, get_session_logs, clear_session_logs

async def _flush_logs(self, event_emitter: EventEmitter | None, valves: Any) -> None:
    # Optional: allow a valve to disable UI logs, but keep this behavior as close
    # as possible to the existing implementation.
    session_id = current_session_id.get()
    if not session_id:
        return

    lines = get_session_logs(session_id)
    if not lines:
        return

    await emit_citation(event_emitter, "\n".join(lines), "Logs")
    clear_session_logs(session_id)
```

- Ensure run_streaming_turn.finally no longer manipulates SessionLogger.logs state directly (pop calls) – that should be encapsulated in logging_config.

5. Ensure build/bundle compatibility

Because scripts/build.py bundles modules into a single file:
- Confirm that logging_config.py is included in the bundler’s MODULE_ORDER in scripts/build.py (if necessary).
- Ensure all imports are relative inside src/openai_responses_manifold/ (the bundler strips them appropriately).
- Run make build and confirm the generated openai_responses_manifold.py still imports and wires logging correctly.

---

## Testing

Add or update tests under functions/pipes/openai_responses_manifold/tests/ to validate the new behavior.

1. Unit-ish tests for logging_config
   - New tests file: tests/test_logging_config.py.
   - Test set_session / reset_session:
     - Set a session and log level.
     - Emit some logs via logging.getLogger("openai_responses_manifold.tests").
     - Assert that SESSION_LOGS (accessed via public helper) contains the expected lines.
   - Test filtering by level:
     - Set current_log_level to logging.INFO.
     - Emit DEBUG and INFO logs.
     - Only INFO and above should be captured.
   - Test session isolation:
     - Simulate two different session IDs in sequence.
     - Ensure logs are stored under the correct session id and don’t bleed across.

2. Engine integration
   - In an existing engine scenario test (e.g., tests/test_runner_scenarios.py or similar), add assertions that:
     - Logs emitted during a run appear in the Logs citation.
     - After the run completes, the buffer for that session is empty (no memory leak).

3. Regression checks
   - Run make test.
   - Run make lint and make format to ensure style/formatting are clean.
   - Run make build and sanity check the generated openai_responses_manifold.py:
     - No import errors.
     - Logging configuration code is present once.
     - Pipe still works with Open WebUI (manual smoke test if possible).

---

## Acceptance Criteria
- All tests pass: make test.
- Linting and formatting pass: make lint, make format.
- make build successfully regenerates openai_responses_manifold.py with the new logging wiring.
- Standard usage pattern everywhere:
  - Modules call logging.getLogger(__name__) (or SessionLogger.get_logger(__name__) if it’s now a thin shim).
  - No code manually attaches/detaches handlers or filters per logger name.
- Per-session logging works:
  - Logs from one chat do not appear in another.
  - The Logs citation still appears at the end of a turn when logs were emitted, and contains the expected content.
- There is a single, centralized place (logging_config.py) that explains and wires the logging design for future agents.
