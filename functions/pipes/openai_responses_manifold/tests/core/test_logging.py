import logging

from openai_responses_manifold.core.logging import (
    OWUI_LOG_LEVEL,
    clear_session_logs,
    consume_session_logs,
    get_logger,
    get_session_logs,
    logging_context,
    truncate_for_log,
)


def test_logging_context_sets_fields_and_filters_levels():
    logger = get_logger(__name__)
    clear_session_logs("s1")

    with logging_context("s1", logging.WARNING, chat_id="c1", message_id="m1", user_id="u1"):
        logger.info("ignore me")
        logger.warning("capture me")

    logs = get_session_logs("s1")

    assert len(logs) == 1
    assert "capture me" in logs[0]
    assert "session_id=s1" in logs[0]
    assert "chat_id=c1" in logs[0]
    assert "message_id=m1" in logs[0]
    assert "user_id=u1" in logs[0]
    assert OWUI_LOG_LEVEL.get() == logging.INFO  # restored after context


def test_consume_session_logs_clears_buffer():
    logger = get_logger(__name__)
    clear_session_logs("s2")

    with logging_context("s2", logging.INFO):
        logger.info("first")
        logger.info("second")

    lines = consume_session_logs("s2")

    assert [
        any("first" in line for line in lines),
        any("second" in line for line in lines),
    ] == [True, True]
    assert get_session_logs("s2") == []


def test_truncate_for_log_behaviors():
    assert truncate_for_log(None) == ("", False)

    short, truncated = truncate_for_log("abc", limit=5)
    assert short == "abc"
    assert truncated is False

    long_text = "x" * 10
    truncated_text, truncated = truncate_for_log(long_text, limit=5)
    assert truncated_text == "x" * 5
    assert truncated is True

    # Non-string values are coerced to strings
    value, truncated = truncate_for_log(123, limit=10)
    assert value == "123"
    assert truncated is False
