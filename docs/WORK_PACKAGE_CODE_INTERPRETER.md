# 🔧 Work Package — Code Interpreter Enablement

> Keep this work package up to date. Add or adjust items as you learn new facts, and tick them off as you complete them.

## Checklist

- [ ] **Native function guard**: In `adapters/openwebui/pipe.py::_ensure_native_function_calling_if_needed`, only enforce the OpenWebUI “native function calling” toggle when any tool has `type == "function"`; do not block built-in tools (`code_interpreter`, `web_search`, etc.).
- [ ] **Strict schema safety**: In `domain/tools.py::_strictify_schema`, preserve the original `required` list and avoid forcing optional properties to be `required`+`nullable` so defaults are not overwritten by `null`.
- [ ] **Request pass-throughs**: Extend `adapters/openwebui/request_builder.py::build_responses_body` to forward valid Responses fields when present (at least `tool_choice`, `include`, `store`, `background`, `metadata`, `text`, `service_tier`, `prompt_cache_key`, `prompt_cache_retention`).
- [ ] **Valves for code interpreter**: Add to `config/settings.py`:
  - `ENABLE_CODE_INTERPRETER_TOOL` (bool, default False)
  - `CODE_INTERPRETER_CONTAINER_JSON` (optional JSON for `container`, default auto)
  - `CODE_INTERPRETER_INCLUDE_OUTPUTS` (bool, default True)
- [ ] **Tool wiring**: In `domain/tools.py::build_tools`, add the built-in `{"type": "code_interpreter", ...}` when the model supports `code_interpreter_tool` and the valve/feature flag enables it; honor container override; default to `{"type": "auto"}`. (Optionally also add `file_search` parity toggle.)
- [ ] **Include wiring**: In `Pipe._apply_parallel_tool_policy`, when a `code_interpreter` tool is present and `CODE_INTERPRETER_INCLUDE_OUTPUTS` is True, ensure `responses_body.include` contains `"code_interpreter_call.outputs"`; keep existing `web_search`/parallel handling.
- [ ] **Streaming UX**: In `_StreamSession.handle_event` (`domain/engine.py`), handle `ResponseCodeInterpreterCall*` events to emit meaningful statuses (start, interpreting, code done/completed) and optionally show executed code as a hidden status.
- [ ] **Output surfacing (optional)**: When handling a `code_interpreter_call` item in `_handle_item_done`, surface logs from `outputs` as a hidden status; consider follow-up work to map file/image outputs to citations or attachments.
- [ ] **Model features sanity**: Confirm `core/model_catalog.py::MODEL_FEATURES` entries for code-interpreter-capable models remain accurate; adjust if needed.
- [ ] **Tests**: Add/extend tests to cover:
  - Code interpreter enabled: `tools` includes `code_interpreter`; `include` has `code_interpreter_call.outputs`; statuses appear.
  - Code interpreter disabled: no tool entry.
  - Coexistence with custom function tools (native function-calling guard only triggers for functions).
  - Strict schema no longer nulls defaults.
- [ ] **Build & bundle**: Run `make test` (or equivalent) and `make build` to regenerate `openai_responses_manifold.py` once changes are made.
