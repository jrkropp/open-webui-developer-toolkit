# 🔧 Work Package — Code Interpreter Enablement

> Keep this work package up to date. Add or adjust items as you learn new facts, and tick them off as you complete them.

## Checklist

- [x] **Native function guard**: In `adapters/openwebui/pipe.py::_ensure_native_function_calling_if_needed`, only enforce the OpenWebUI “native function calling” toggle when any tool has `type == "function"`; do not block built-in tools (`code_interpreter`, `web_search`, etc.).
- [ ] **Strict schema safety**: In `domain/tools.py::_strictify_schema`, preserve the original `required` list and avoid forcing optional properties to be `required`+`nullable` so defaults are not overwritten by `null`.
- [x] **Request pass-throughs**: `adapters/openwebui/request_builder.py::build_responses_body` now forwards Responses fields (`tool_choice`, `include`, `store`, `background`, `metadata`, `text`, `service_tier`, `prompt_cache_key`, `prompt_cache_retention`, etc.).
- [x] **Valves for code interpreter**: `config/settings.py` exposes `ENABLE_CODE_INTERPRETER_TOOL` and optional `CODE_INTERPRETER_CONTAINER_JSON` (auto container by default). No extra include/choice valve required.
- [x] **Tool wiring**: `domain/tools.py::build_tools` adds the built-in `{"type": "code_interpreter", ...}` when supported and enabled; honors feature-level container overrides and valve JSON, defaults to `{"type": "auto"}`.
- [x] **Include wiring**: `Pipe._apply_parallel_tool_policy` auto-includes `"code_interpreter_call.outputs"` whenever a code interpreter tool is present (no valve needed) and keeps existing `web_search` handling.
- [x] **Streaming UX**: `_StreamSession.handle_event` (`domain/engine.py`) emits statuses for code interpreter start/interpret/complete and surfaces executed code as a hidden status on `code_done`.
- [x] **Output surfacing**: `domain/code_interpreter.py::handle_code_interpreter_item` consolidates logs + outputs + code into a citation; fallback stores pending state and now emits a follow-up citation with the assistant’s result text when no structured outputs are returned.
- [ ] **Model features sanity**: Confirm `core/model_catalog.py::MODEL_FEATURES` entries for code-interpreter-capable models remain accurate as OpenAI releases updates.
- [ ] **Strict schema tests**: Add/extend tests once `_strictify_schema` is relaxed so optional defaults stop being nulled.
- [x] **Build & bundle**: `make test` + `make build` run; monolith regenerated.
