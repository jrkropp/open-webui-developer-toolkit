from importlib.util import spec_from_file_location, module_from_spec
import json
import sys
from pathlib import Path
import types
from unittest.mock import AsyncMock, patch
import pytest


def _reload_pipeline():
    path = Path(__file__).resolve().parents[1] / "functions" / "pipes" / "openai_responses_api_pipeline.py"
    spec = spec_from_file_location("openai_responses_api_pipeline", path)
    mod = module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_prepare_tools_variants(dummy_chat):
    pipeline = _reload_pipeline()
    reg = {
        "tools": {
            "one": {
                "spec": {
                    "name": "foo",
                    "description": "d",
                    "parameters": {"type": "object"},
                }
            },
            "two": {"spec": {"function": {"name": "bar"}}},
        }
    }
    tools = pipeline.prepare_tools(reg)
    assert tools[0]["name"] == "foo"
    assert tools[1]["name"] == "bar"
    assert tools[0]["type"] == "function"
    assert tools[1]["type"] == "function"


@pytest.mark.asyncio
async def test_build_responses_payload(dummy_chat):
    pipeline = _reload_pipeline()
    dummy_chat["history"] = {
        "currentId": "m2",
        "messages": {
            "m1": {"role": "user", "content": [{"text": "hi"}], "parentId": None},
            "m2": {
                "role": "assistant",
                "content": [{"text": "hello"}],
                "parentId": "m1",
            },
        },
    }

    payload = await pipeline.load_chat_input("chat1")
    assert payload == [
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "hello"}]},
    ]


def test_pretty_log_block(dummy_chat):
    pipeline = _reload_pipeline()
    out = pipeline.pretty_log_block({"a": 1}, label="lbl")
    assert "lbl =" in out
    assert '{\n  "a": 1\n}' in out


def test_extract_instructions(dummy_chat):
    pipeline = _reload_pipeline()
    body = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "one"},
            {"role": "system", "content": "two"},
        ]
    }
    assert pipeline.Pipe._extract_instructions(body) == "two"


def test_instruction_suffix_helpers(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    date_line = pipe._get_current_date_suffix()
    assert "Today's date:" in date_line

    req = types.SimpleNamespace(
        headers={
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
        },
        client=types.SimpleNamespace(host="207.194.4.18", port=0),
    )
    user_line = pipe._get_user_info_suffix({"name": "Justin", "email": "me@example.com"})
    assert user_line == "user_info: Justin <me@example.com>"

    browser_line = pipe._get_browser_info_suffix(req)
    assert browser_line.startswith("browser_info:")

    ip_line = pipe._get_ip_info_suffix(req)
    assert ip_line.startswith("ip_info: 207.194.4.18")


@pytest.mark.asyncio
async def test_ip_lookup_cached(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    class DummyResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def json(self):
            return self._data

        def raise_for_status(self):
            pass

    class DummyClient:
        async def get(self, url):
            assert url.endswith("207.194.4.18")
            return DummyResp({"city": "Waterloo", "regionName": "Ontario", "country": "Canada"})

    async def fake_client():
        return DummyClient()

    pipe.get_http_client = fake_client

    req = types.SimpleNamespace(
        headers={
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
        },
        client=types.SimpleNamespace(host="207.194.4.18", port=0),
    )

    first = pipe._get_ip_info_suffix(req)
    assert "Waterloo" not in first
    for task in list(pipe._ip_tasks.values()):
        await task
    second = pipe._get_ip_info_suffix(req)
    assert "Waterloo" in second
    assert pipe._ip_cache.get("207.194.4.18")


def test_apply_user_overrides_sets_log_level(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    class Dummy:
        def __init__(self, **vals):
            self._vals = vals

        def model_dump(self, exclude_none=True):  # mimic pydantic v2 API
            return self._vals

    overrides = Dummy(CUSTOM_LOG_LEVEL="DEBUG")
    new_valves = pipe._apply_user_overrides(overrides)
    assert pipe.valves.CUSTOM_LOG_LEVEL != "DEBUG"
    assert new_valves.CUSTOM_LOG_LEVEL == "DEBUG"
    import logging

    assert pipe.log.level == logging.DEBUG


@pytest.mark.asyncio
async def test_build_params_includes_reasoning(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()
    pipe.valves.REASON_SUMMARY = "concise"
    body = {
        "model": "openai_responses.o3",
        "max_tokens": 50,
        "temperature": 0.4,
        "top_p": 0.9,
        "reasoning_effort": "high",
    }
    params = await pipeline.prepare_payload(
        pipe.valves,
        body,
        "ins",
        [{"type": "function"}],
        "me@example.com",
        chat_id="chat1",
    )
    assert params["tool_choice"] == "auto"
    assert params["max_output_tokens"] == 50
    assert params["temperature"] == 0.4
    assert params["top_p"] == 0.9
    assert params["user"] == "me@example.com"
    assert params["reasoning"] == {"effort": "high", "summary": "concise"}


@pytest.mark.asyncio
async def test_build_params_drops_reasoning_for_base_model(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()
    body = {"model": "openai_responses.gpt-4.1", "reasoning_effort": "high"}
    params = await pipeline.prepare_payload(
        pipe.valves,
        body,
        "ins",
        [],
        None,
        chat_id="chat1",
    )
    assert "reasoning" not in params


@pytest.mark.asyncio
async def test_assemble_payload_omits_tool_fields_when_none(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()
    params = await pipeline.prepare_payload(
        pipe.valves,
        {},
        "ins",
        None,
        None,
        chat_id="chat1",
    )
    assert "tools" not in params
    assert "tool_choice" not in params


def test_update_usage_accumulates(dummy_chat):
    pipeline = _reload_pipeline()
    total = {}
    pipeline.Pipe._update_usage(total, {"input_tokens": 1, "output_tokens": 2, "pricing": {"total": 1}}, 1)
    pipeline.Pipe._update_usage(total, {"input_tokens": 4, "output_tokens": 3, "pricing": {"total": 2}}, 2)
    assert total == {
        "input_tokens": 5,
        "output_tokens": 5,
        "pricing": {"total": 3},
        "loops": 2,
    }

def test_parse_responses_sse_handles_extra_fields(dummy_chat):
    pipeline = _reload_pipeline()
    raw = json.dumps({"annotation": {"title": "t"}, "delta": "x"})
    event = pipeline.parse_responses_sse("response.output_text.annotation.added", raw)
    assert event.type == "response.output_text.annotation.added"
    assert event.delta == "x"
    assert getattr(event, "annotation").title == "t"


@pytest.mark.asyncio
async def test_build_responses_payload_complex(dummy_chat):
    pipeline = _reload_pipeline()
    dummy_chat["history"] = {
        "currentId": "m2",
        "messages": {
            "m1": {
                "role": "user",
                "content": [{"text": "hi"}],
                "parentId": None,
                "files": [{"type": "image", "url": "img"}],
            },
            "m2": {
                "role": "assistant",
                "content": [{"text": "ok"}],
                "parentId": "m1",
                "sources": [
                    {
                        "_fc": [
                            {
                                "call_id": "c1",
                                "name": "t",
                                "arguments": "{}",
                                "output": "42",
                            }
                        ]
                    }
                ],
            },
        },
    }
    payload = await pipeline.load_chat_input("chat1")
    assert payload == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "hi"},
                {"type": "input_image", "image_url": "img"},
            ],
        },
        {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "42"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "ok"}]},
    ]




@pytest.mark.asyncio
async def test_pipe_stream_loop(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.reasoning_summary_part.added"),
        types.SimpleNamespace(type="response.reasoning_summary_text.delta", delta="t"),
        types.SimpleNamespace(type="response.reasoning_summary_text.done", item_id="sum1", text="end"),
        types.SimpleNamespace(type="response.content_part.added"),
        types.SimpleNamespace(type="response.output_text.delta", delta="hi"),
        types.SimpleNamespace(type="response.output_text.done", text="hi"),
        types.SimpleNamespace(
            type="response.completed",
            response=types.SimpleNamespace(
                usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
            ),
        ),
    ]

    async def fake_stream(client, base_url, api_key, params):
        for e in events:
            yield e

    emitted: list[dict] = []

    async def emitter(evt: dict):
        emitted.append(evt)

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        gen = pipe.pipe(
            {},
            {},
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {},
        )
        tokens = []
        async for chunk in gen:
            tokens.append(chunk)
    await pipe.on_shutdown()

    assert tokens == ["<think>", "t", "\n\n---\n\n", "</think>\n", "hi"]
    assert [e["data"] for e in emitted if e["type"] == "chat:completion"] == [
        {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "loops": 1}},
        {"done": True},
    ]
    assert emitted[-1]["type"] == "chat:completion"  # done event


@pytest.mark.asyncio
async def test_pipe_deletes_response(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="rX")),
        types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
        types.SimpleNamespace(type="response.output_text.done", text="ok"),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(client, base_url, api_key, params):
        for e in events:
            yield e

    emitter = AsyncMock()

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipeline, "delete_response", AsyncMock()
    ) as del_mock, patch.object(pipe, "get_http_client", AsyncMock(return_value=object())):
        await pipe.pipe(
            {},
            {},
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {},
        )
    await pipe.on_shutdown()

    del_mock.assert_awaited_once()
    args = del_mock.await_args.args
    assert args[1:] == (pipe.valves.BASE_URL, pipe.valves.API_KEY, "rX")


@pytest.mark.asyncio
async def test_debug_logs_citation_emitted(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    class Dummy:
        def __init__(self, **vals):
            self._vals = vals

        def model_dump(self, exclude_none=True):
            return self._vals

    user = {"valves": Dummy(CUSTOM_LOG_LEVEL="DEBUG")}

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
        types.SimpleNamespace(type="response.output_text.done", text="ok"),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(client, base_url, api_key, params):
        for e in events:
            yield e

    emitted = []

    async def emitter(evt: dict):
        emitted.append(evt)

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        await pipe.pipe(
            {},
            user,
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {},
        )
    await pipe.on_shutdown()

    assert emitted[-1]["type"] == "citation"
    assert "Loop iteration" in emitted[-1]["data"]["document"][0]


@pytest.mark.asyncio
async def test_debug_logs_citation_saved_with_tool(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    class Dummy:
        def __init__(self, **vals):
            self._vals = vals

        def model_dump(self, exclude_none=True):
            return self._vals

    user = {"valves": Dummy(CUSTOM_LOG_LEVEL="DEBUG")}

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_item.added", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.output_item.done", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(client, base_url, api_key, params):
        for e in events:
            yield e

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ), patch.object(pipe, "_store_citation") as store_mock:
        await pipe.pipe(
            {},
            user,
            None,
            AsyncMock(),
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {},
        )
    await pipe.on_shutdown()

    store_mock.assert_called_once()


@pytest.mark.asyncio
async def test_debug_logs_citation_multiple_turns(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    class Dummy:
        def __init__(self, **vals):
            self._vals = vals

        def model_dump(self, exclude_none=True):
            return self._vals

    user = {"valves": Dummy(CUSTOM_LOG_LEVEL="DEBUG")}

    events_first = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_item.added", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.output_item.done", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]
    events_second = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r2")),
        types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
        types.SimpleNamespace(type="response.output_text.done", text="ok"),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream1(*_a, **_kw):
        for e in events_first:
            yield e

    async def fake_stream2(*_a, **_kw):
        for e in events_second:
            yield e

    emitted = []

    async def emitter(evt: dict):
        emitted.append(evt)

    with patch.object(
        pipeline,
        "stream_responses",
        side_effect=[fake_stream1, fake_stream2],
    ), patch.object(pipe, "get_http_client", AsyncMock(return_value=object())):
        gen = pipe.pipe(
            {},
            user,
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {"t": {"callable": AsyncMock(return_value="42")}},
        )
        async for _ in gen:
            pass
    await pipe.on_shutdown()

    assert emitted[-1]["type"] == "chat:completion"
    assert emitted[-1]["data"] == {"done": True}
    assert any(e["type"] == "citation" and e["data"]["source"]["name"] == "Debug Logs" for e in emitted)


@pytest.mark.asyncio
async def test_tool_metadata_persisted(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_item.added", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.output_item.done", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(client, base_url, api_key, params):
        for e in events:
            yield e

    tools = {"t": {"callable": AsyncMock(return_value="42")}}
    emitted = []

    async def emitter(evt: dict):
        emitted.append(evt)

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        await pipe.pipe(
            {},
            {},
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            tools,
        )
    await pipe.on_shutdown()

    citation = next(e for e in emitted if e["type"] == "citation")
    assert citation["data"].get("_fc")
    fc = citation["data"]["_fc"][0]
    assert fc["name"] == "t"
    assert fc["output"] == "42"


@pytest.mark.asyncio
async def test_previous_response_cleanup(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    events_first = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_item.added", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.output_item.done", item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}")),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]
    events_second = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r2")),
        types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
        types.SimpleNamespace(type="response.output_text.done", text="ok"),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream1(*_args, **_kwargs):
        for e in events_first:
            yield e

    async def fake_stream2(*_args, **_kwargs):
        for e in events_second:
            yield e

    with patch.object(
        pipeline,
        "stream_responses",
        side_effect=[fake_stream1, fake_stream2],
    ), patch.object(
        pipeline,
        "delete_response",
        AsyncMock(),
    ) as del_mock, patch.object(
        pipe,
        "get_http_client",
        AsyncMock(return_value=object()),
    ):
        await pipe.pipe(
            {},
            {},
            None,
            AsyncMock(),
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {"t": {"callable": AsyncMock(return_value="42")}},
        )
    await pipe.on_shutdown()

    assert del_mock.await_count == 2
    ids = [c.args[3] for c in del_mock.await_args_list]
    assert ids == ["r1", "r2"]


@pytest.mark.asyncio
async def test_function_call_output_persisted(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    dummy_chat["history"] = {
        "currentId": "u1",
        "messages": {
            "u1": {"role": "user", "content": [{"text": "hi"}], "parentId": None},
            "m1": {"role": "assistant", "parentId": "u1"},
        },
    }

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(
            type="response.output_item.added",
            item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}"),
        ),
        types.SimpleNamespace(
            type="response.output_item.done",
            item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}"),
        ),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(*_a, **_kw):
        for e in events:
            yield e

    tools = {"t": {"callable": AsyncMock(return_value="42")}}

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        async def emitter(evt: dict):
            if evt.get("type") == "citation":
                msgs = dummy_chat["history"].setdefault("messages", {})
                m = msgs.setdefault("m1", {"role": "assistant"})
                srcs = list(m.get("sources", []))
                srcs.append(evt["data"])
                m["sources"] = srcs
        gen = pipe.pipe(
            {},
            {},
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            tools,
        )
        async for _ in gen:
            pass
    await pipe.on_shutdown()

    payload = await pipeline.load_chat_input("chat1")
    assert {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}"} in payload
    assert {"type": "function_call_output", "call_id": "c1", "output": "42"} in payload


@pytest.mark.asyncio
async def test_persist_tool_results_valve_off(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()
    pipe.valves.PERSIST_TOOL_RESULTS = False

    dummy_chat["history"] = {
        "currentId": "u1",
        "messages": {
            "u1": {"role": "user", "content": [{"text": "hi"}], "parentId": None},
            "m1": {"role": "assistant", "parentId": "u1"},
        },
    }

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(
            type="response.output_item.added",
            item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}"),
        ),
        types.SimpleNamespace(
            type="response.output_item.done",
            item=types.SimpleNamespace(type="function_call", name="t", call_id="c1", arguments="{}"),
        ),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    async def fake_stream(*_a, **_kw):
        for e in events:
            yield e

    tools = {"t": {"callable": AsyncMock(return_value="42")}}

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        async def emitter(evt: dict):
            if evt.get("type") == "citation":
                msgs = dummy_chat["history"].setdefault("messages", {})
                m = msgs.setdefault("m1", {"role": "assistant"})
                srcs = list(m.get("sources", []))
                srcs.append(evt["data"])
                m["sources"] = srcs
        gen = pipe.pipe(
            {},
            {},
            None,
            emitter,
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            tools,
        )
        async for _ in gen:
            pass
    await pipe.on_shutdown()

    payload = await pipeline.load_chat_input("chat1")
    assert {
        "type": "function_call",
        "call_id": "c1",
        "name": "t",
        "arguments": "{}",
    } not in payload
    assert not dummy_chat["history"]["messages"]["m1"]["sources"][0].get("_fc")


def test_pipes_returns_multiple_models(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()
    pipe.valves.MODEL_ID = "gpt-4o,gpt-4o-mini"
    models = pipe.pipes()
    assert models == [
        {"id": "gpt-4o", "name": "OpenAI: gpt-4o"},
        {"id": "gpt-4o-mini", "name": "OpenAI: gpt-4o-mini"},
    ]


@pytest.mark.asyncio
async def test_tools_removed_for_unsupported_model(dummy_chat):
    pipeline = _reload_pipeline()
    pipe = pipeline.Pipe()

    events = [
        types.SimpleNamespace(type="response.created", response=types.SimpleNamespace(id="r1")),
        types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
        types.SimpleNamespace(type="response.output_text.done", text="ok"),
        types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage={})),
    ]

    captured_params = []

    async def fake_stream(client, base_url, api_key, params):
        captured_params.append(params)
        for e in events:
            yield e

    with patch.object(pipeline, "stream_responses", fake_stream), patch.object(
        pipe, "get_http_client", AsyncMock(return_value=object())
    ):
        await pipe.pipe(
            {"model": "openai_responses.chatgpt-4o-latest"},
            {},
            None,
            AsyncMock(),
            AsyncMock(),
            [],
            {"chat_id": "chat1", "message_id": "m1", "function_calling": "native"},
            {},
        )
    await pipe.on_shutdown()

    assert "tools" not in captured_params[0]
    assert "tool_choice" not in captured_params[0]


def test_simplify_user_agent_helper(dummy_chat):
    pipeline = _reload_pipeline()
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36"
    assert pipeline.simplify_user_agent(ua) == "Chrome 136"


@pytest.mark.asyncio
async def test_execute_tool_calls_sync_function(dummy_chat):
    pipeline = _reload_pipeline()
    call = types.SimpleNamespace(name="t", arguments="{}")

    def sync_tool() -> str:
        return "42"

    results = await pipeline.execute_responses_tool_calls(
        [call], {"t": {"callable": sync_tool}}
    )
    assert results == ["42"]
