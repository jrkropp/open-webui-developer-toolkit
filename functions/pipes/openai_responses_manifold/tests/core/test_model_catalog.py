import pytest

from openai_responses_manifold.core import model_catalog


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("openai_responses.gpt-5.1-chat-latest", "gpt-5.1-chat-latest"),
        (" gpt-5-ThInKiNg-High ", "gpt-5-thinking-high"),
        ("gpt-5.1-2025-05-20", "gpt-5.1"),
    ],
)
def test_normalize_strips_prefix_dates_and_lowercases(raw: str, expected: str):
    assert model_catalog.normalize(raw) == expected


def test_base_model_resolves_aliases_and_defaults_to_normalized():
    assert model_catalog.base_model("gpt-5-thinking-high") == "gpt-5"
    assert model_catalog.base_model("openai_responses.gpt-5.1-chat-latest") == "gpt-5.1-chat-latest"


def test_alias_defaults_are_copied():
    defaults = model_catalog.alias_defaults("gpt-5-thinking-high")

    assert defaults == {"reasoning": {"effort": "high"}}
    defaults["reasoning"]["effort"] = "minimal"
    assert model_catalog.alias_defaults("gpt-5-thinking-high") == {"reasoning": {"effort": "high"}}


def test_features_and_supports_match_specs():
    assert model_catalog.features("gpt-5-thinking-mini") == {
        "function_calling",
        "reasoning",
        "reasoning_summary",
        "file_search_tool",
        "image_gen_tool",
        "code_interpreter_tool",
        "web_search_tool",
        "verbosity",
    }
    assert model_catalog.supports("web_search_tool", "gpt-4o") is True
    assert model_catalog.supports("reasoning", "gpt-4o") is False
    assert model_catalog.features("unknown-model") == set()
