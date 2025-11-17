> **Note:** Keep this workpackage current. Check off tasks as they’re completed and add subtasks when new work is discovered.

## Checklist
[] Reduce request/response schemas into a clear split: outbound request models vs inbound streaming event models.
[] Decide final file layout (e.g., `core/requests.py`, `core/events.py`) and update imports across engine/infra/tests.
[] Refactor `OpenAIResponsesClient.stream` to hand back typed events and enforce the documented SSE shapes.
[] Update `engine.py` to pattern match on typed events only (remove reliance on raw dicts/undocumented events).
[] Rewrite tests/fixtures to use validated schemas (fakes enqueue typed events or dicts that validate).
[] Add dev notes/docs describing the schema layout and how to parse/emit events.
