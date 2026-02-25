import sys
import types

# Stub minimal open_webui modules required for import
owui_root = types.ModuleType("open_webui")
models_pkg = types.ModuleType("open_webui.models")
sys.modules.setdefault("open_webui", owui_root)
sys.modules.setdefault("open_webui.models", models_pkg)
sys.modules.setdefault("open_webui.models.chats", types.SimpleNamespace(Chats=object))
sys.modules.setdefault(
    "open_webui.models.models",
    types.SimpleNamespace(ModelForm=object, Models=object),
)
sys.modules.setdefault("open_webui.utils", types.ModuleType("open_webui.utils"))
sys.modules.setdefault(
    "open_webui.utils.misc",
    types.SimpleNamespace(get_last_user_message=lambda messages: messages[-1] if messages else {}),
)

from functions.pipes.openai_responses_manifold.openai_responses_manifold import (
    ModelFamily,
    Pipe,
    ResponsesBody,
    build_tools,
)


def test_gpt52_minimal_alias_maps_to_none_effort():
    body = ResponsesBody(model="gpt-5.2-thinking-minimal", input="hello")

    assert body.model == "gpt-5.2"
    assert body.reasoning == {"effort": "none"}


def test_gpt52_xhigh_and_codex_aliases_are_supported():
    body = ResponsesBody(model="gpt-5.2-codex-thinking-xhigh", input="hello")

    assert ModelFamily.supports("function_calling", "gpt-5.2-codex")
    assert body.model == "gpt-5.2-codex"
    assert body.reasoning == {"effort": "xhigh"}


def test_gpt53_codex_xhigh_alias_is_supported():
    body = ResponsesBody(model="gpt-5.3-codex-thinking-xhigh", input="hello")

    assert ModelFamily.supports("function_calling", "gpt-5.3-codex")
    assert body.model == "gpt-5.3-codex"
    assert body.reasoning == {"effort": "xhigh"}


def test_build_tools_skips_web_search_when_effort_is_none():
    valves = Pipe.Valves()
    valves.ENABLE_WEB_SEARCH_TOOL = True

    body = ResponsesBody(
        model="gpt-5.2",
        input="hello",
        reasoning={"effort": "none"},
    )

    tools = build_tools(body, valves, __tools__={})

    assert all(tool.get("type") != "web_search" for tool in tools)
