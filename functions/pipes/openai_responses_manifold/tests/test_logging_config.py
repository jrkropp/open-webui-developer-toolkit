from __future__ import annotations

import logging

import pytest

import openai_responses_manifold as orm


def _emit_logs(logger: logging.Logger, *, include_debug: bool = True) -> None:
    if include_debug:
        logger.debug("debug line")
    logger.info("info line")


def test_logs_buffer_respects_level_and_formatting() -> None:
    logger = orm.get_logger("openai_responses_manifold.tests")

    tokens = orm.push_logging_context("session-a", logging.INFO)
    try:
        _emit_logs(logger)
    finally:
        orm.pop_logging_context(tokens)

    lines = orm.get_session_logs("session-a")
    assert any("info line" in line for line in lines)
    assert not any("debug line" in line for line in lines)

    orm.clear_session_logs("session-a")


def test_sessions_are_isolated_and_resettable() -> None:
    logger = orm.get_logger("openai_responses_manifold.tests")

    first_tokens = orm.push_logging_context("session-one", logging.DEBUG)
    try:
        _emit_logs(logger)
    finally:
        orm.pop_logging_context(first_tokens)

    second_tokens = orm.push_logging_context("session-two", logging.DEBUG)
    try:
        logger.info("second session")
    finally:
        orm.pop_logging_context(second_tokens)

    first_logs = orm.consume_session_logs("session-one")
    second_logs = orm.consume_session_logs("session-two")

    assert any("info line" in line for line in first_logs)
    assert any("second session" in line for line in second_logs)
    assert not first_logs == second_logs


@pytest.mark.asyncio()
async def test_session_logging_context_manager() -> None:
    logger = orm.get_logger("openai_responses_manifold.tests")

    with orm.logging_context("session-cm", logging.WARNING):
        logger.error("captured")
        logger.info("filtered out")

    logs = orm.consume_session_logs("session-cm")
    assert any("captured" in line for line in logs)
    assert not any("filtered out" in line for line in logs)
