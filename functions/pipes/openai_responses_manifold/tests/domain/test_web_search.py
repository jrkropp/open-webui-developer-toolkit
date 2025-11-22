from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.core.model_catalog import features
from openai_responses_manifold.domain.web_search import build_web_search_tools


def _cfg(**overrides):
    return merge_valves(PipeValves(**overrides), UserValves())


def test_web_search_skipped_when_capability_missing():
    cfg = _cfg(ENABLE_WEB_SEARCH_TOOL=True)
    tools = build_web_search_tools(
        model_id="chatgpt-4o-latest",
        features=features("chatgpt-4o-latest"),
        cfg=cfg,
    )
    assert tools == []


def test_web_search_skipped_when_disabled():
    cfg = _cfg()
    tools = build_web_search_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
    )
    assert tools == []


def test_web_search_constructs_tool_with_location_and_context():
    cfg = _cfg(
        ENABLE_WEB_SEARCH_TOOL=True,
        WEB_SEARCH_CONTEXT_SIZE="high",
        WEB_SEARCH_USER_LOCATION='{"country": "US"}',
    )
    tools = build_web_search_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
    )

    assert tools == [
        {
            "type": "web_search",
            "search_context_size": "high",
            "user_location": {"country": "US"},
        }
    ]


def test_web_search_skips_on_minimal_reasoning():
    cfg = _cfg(ENABLE_WEB_SEARCH_TOOL=True)
    tools = build_web_search_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
        reasoning_effort="minimal",
    )
    assert tools == []


def test_web_search_invalid_location_is_ignored(capsys):
    cfg = _cfg(
        ENABLE_WEB_SEARCH_TOOL=True,
        WEB_SEARCH_USER_LOCATION="not-json",
    )
    tools = build_web_search_tools(
        model_id="gpt-5",
        features=features("gpt-5"),
        cfg=cfg,
    )

    assert tools == [
        {
            "type": "web_search",
            "search_context_size": cfg.WEB_SEARCH_CONTEXT_SIZE,
        }
    ]
