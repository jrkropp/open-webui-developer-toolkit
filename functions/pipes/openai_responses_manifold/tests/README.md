# Testing Strategy

The suite is split into two complementary layers:

1. **Scenario tests (`test_runner_scenarios.py`)** – drive `ResponsesEngine` with a fake Responses client and spy event emitter. These async tests assert the full Open WebUI event flow (streaming completions, tool execution loops, error/log handling).
2. **Module/unit tests** – validate deterministic helpers like marker persistence, Completions→Responses conversion, and tool builders.

Key helpers live in `tests/fakes.py`:

- `FakeResponsesClient`: yields scripted SSE events or request payloads.
- `SpyEventEmitter`: records events for assertions.
- `InMemoryChats`: lightweight stand-in for `open_webui.models.chats.Chats`.

Pytest fixtures in `tests/conftest.py` expose these fakes, factory helpers for metadata/request bodies, and scoped `SessionLogger` context. Use them instead of re-creating doubles in individual tests.
