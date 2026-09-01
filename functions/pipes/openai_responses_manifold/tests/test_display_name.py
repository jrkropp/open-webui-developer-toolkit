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

from functions.pipes.openai_responses_manifold.openai_responses_manifold import ModelFamily


def test_display_name_gpt_families():
    assert ModelFamily.display_name("gpt-5.6-luna") == "GPT 5.6 Luna"
    assert ModelFamily.display_name("gpt-5.6-sol-pro-xhigh") == "GPT 5.6 Sol Pro XHigh"
    assert ModelFamily.display_name("gpt-4.1-mini") == "GPT 4.1 Mini"
    assert ModelFamily.display_name("gpt-4o") == "GPT 4o"
    assert ModelFamily.display_name("gpt-5-chat-latest") == "GPT 5 Chat Latest"


def test_display_name_drops_none_effort_suffix():
    assert ModelFamily.display_name("gpt-5.6-luna-none") == "GPT 5.6 Luna"
    assert ModelFamily.display_name("gpt-5.6-sol-none") == "GPT 5.6 Sol"


def test_display_name_o_series_and_chatgpt():
    assert ModelFamily.display_name("o3-mini-high") == "o3 Mini High"
    assert ModelFamily.display_name("o4-mini-deep-research") == "o4 Mini Deep Research"
    assert ModelFamily.display_name("chatgpt-4o-latest") == "ChatGPT 4o Latest"


def test_display_name_strips_prefix_and_date():
    assert ModelFamily.display_name("openai_responses.gpt-5.6-terra") == "GPT 5.6 Terra"
    assert ModelFamily.display_name("gpt-4o-2024-08-06") == "GPT 4o"
