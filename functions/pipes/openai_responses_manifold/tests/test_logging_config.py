from __future__ import annotations

import logging

import pytest

import openai_responses_manifold as orm


def _emit_logs(logger: logging.Logger, *, include_debug: bool = True) -> None:
    if include_debug:
        logger.debug("debug line")
    logger.info("info line")


def test_logs_buffer_respects_level_and_formatting() -> None:
    logger = orm.SessionLogger.get_logger("openai_responses_manifold.tests")

    tokens = orm.SessionLogger.set_session("session-a", logging.INFO)
    try:
        _emit_logs(logger)
    finally:
        orm.SessionLogger.reset_session(tokens)

    lines = orm.SessionLogger.get_session_logs("session-a")
    assert any("info line" in line for line in lines)
    assert not any("debug line" in line for line in lines)

    orm.SessionLogger.clear_session_logs("session-a")


def test_sessions_are_isolated_and_resettable() -> None:
    logger = orm.SessionLogger.get_logger("openai_responses_manifold.tests")

    first_tokens = orm.SessionLogger.set_session("session-one", logging.DEBUG)
    try:
        _emit_logs(logger)
    finally:
        orm.SessionLogger.reset_session(first_tokens)

    second_tokens = orm.SessionLogger.set_session("session-two", logging.DEBUG)
    try:
        logger.info("second session")
    finally:
        orm.SessionLogger.reset_session(second_tokens)

    first_logs = orm.SessionLogger.consume_session_logs("session-one")
    second_logs = orm.SessionLogger.consume_session_logs("session-two")

    assert any("info line" in line for line in first_logs)
    assert any("second session" in line for line in second_logs)
    assert not first_logs == second_logs


@pytest.mark.asyncio()
async def test_session_logging_context_manager() -> None:
    logger = orm.SessionLogger.get_logger("openai_responses_manifold.tests")

    with orm.SessionLogger.session_logging("session-cm", logging.WARNING):
        logger.error("captured")
        logger.info("filtered out")

    logs = orm.SessionLogger.consume_session_logs("session-cm")
    assert any("captured" in line for line in logs)
    assert not any("filtered out" in line for line in logs)
