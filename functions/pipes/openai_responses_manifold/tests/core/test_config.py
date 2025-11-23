import pytest

from openai_responses_manifold.core.config import (
    PipeValves,
    RuntimeConfig,
    UserValves,
    merge_valves,
)


def test_pipe_valves_defaults_match_docs():
    valves = PipeValves()

    assert valves.BASE_URL == "https://api.openai.com/v1"
    assert valves.API_KEY == ""
    assert (
        valves.MODEL_ID
        == "gpt-5-auto, gpt-5-chat-latest, gpt-5-thinking, gpt-5-thinking-high, gpt-5-thinking-minimal, gpt-4.1-nano, chatgpt-4o-latest, o3, gpt-4o"
    )
    assert valves.REASONING_SUMMARY == "disabled"
    assert valves.PERSIST_REASONING_TOKENS == "disabled"
    assert valves.PERSIST_TOOL_RESULTS is True
    assert valves.PARALLEL_TOOL_CALLS is True
    assert valves.ENABLE_STRICT_TOOL_CALLING is True
    assert valves.MAX_TOOL_CALLS is None
    assert valves.MAX_FUNCTION_CALL_LOOPS == 10
    assert valves.ENABLE_WEB_SEARCH_TOOL is False
    assert valves.WEB_SEARCH_CONTEXT_SIZE == "medium"
    assert valves.WEB_SEARCH_USER_LOCATION is None
    assert valves.WEB_SEARCH_ALLOWED_DOMAINS is None
    assert valves.WEB_SEARCH_EXTERNAL_WEB_ACCESS is True
    assert valves.WEB_SEARCH_INCLUDE_SOURCES is True
    assert valves.ENABLE_CODE_INTERPRETER_TOOL is False
    assert valves.CODE_INTERPRETER_CONTAINER_JSON is None
    assert valves.REMOTE_MCP_SERVERS_JSON is None
    assert valves.TRUNCATION == "auto"
    assert valves.PROMPT_CACHE_KEY == "id"
    assert valves.LOG_LEVEL == "INFO"


@pytest.mark.parametrize(
    "user_level,expected",
    [("INHERIT", "INFO"), ("inherit", "INFO"), ("debug", "DEBUG")],
)
def test_merge_valves_respects_user_log_level(user_level: str, expected: str):
    pipe_valves = PipeValves(LOG_LEVEL="INFO")
    user_valves = UserValves(LOG_LEVEL=user_level)  # type: ignore[arg-type]

    config = merge_valves(pipe_valves, user_valves)

    assert isinstance(config, RuntimeConfig)
    assert config.LOG_LEVEL == expected

