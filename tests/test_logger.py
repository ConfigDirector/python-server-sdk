from __future__ import annotations

import io
import logging

import pytest

from configdirector import (
    ConfigDirectorClient,
    ConfigDirectorLogger,
    ConsoleLogger,
    create_console_logger,
    get_default_logger,
)
from configdirector.logger import LOGGER_NAME
from configdirector.types import LoggingLevel

SDK_KEY = "test-server-sdk-key"


def test_the_default_logger_is_the_stdlib_configdirector_logger() -> None:
    assert get_default_logger() is logging.getLogger(LOGGER_NAME)


def test_the_sdk_logs_through_the_default_logger(caplog: pytest.LogCaptureFixture) -> None:
    client = ConfigDirectorClient(SDK_KEY)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        client.initialize()

    assert any("client is ready" in record.message for record in caplog.records)
    assert all(record.name == LOGGER_NAME for record in caplog.records)


def test_debug_logs_are_suppressed_by_default(caplog: pytest.LogCaptureFixture) -> None:
    client = ConfigDirectorClient(SDK_KEY)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        client.initialize()

    assert caplog.records == []


def test_log_arguments_are_formatted_lazily(caplog: pytest.LogCaptureFixture) -> None:
    client = ConfigDirectorClient(SDK_KEY)
    client.initialize()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        client.get_value("my-flag", "fallback")

    record = next(r for r in caplog.records if "No config state" in r.message)
    # The template is stored unformatted, so a suppressed record costs nothing to build.
    assert record.msg == "No config state found for %r, returning default value %r"
    assert record.args == ("my-flag", "fallback")


def test_a_custom_logger_can_be_supplied() -> None:
    stream = io.StringIO()
    client = ConfigDirectorClient(SDK_KEY, logger=ConsoleLogger("debug", stream=stream))

    client.initialize()

    assert "client is ready" in stream.getvalue()


def test_create_console_logger_defaults_to_warning() -> None:
    logger = create_console_logger()

    assert isinstance(logger, ConsoleLogger)
    assert logger.level == "warning"


def test_create_console_logger_rejects_an_unknown_level() -> None:
    with pytest.raises(ValueError, match="Invalid logging level"):
        create_console_logger("verbose")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("debug", ["debug", "info", "warning", "error"]),
        ("info", ["info", "warning", "error"]),
        ("warning", ["warning", "error"]),
        ("error", ["error"]),
        ("off", []),
    ],
)
def test_console_logger_respects_its_level(level: LoggingLevel, expected: list[str]) -> None:
    stream = io.StringIO()
    logger = ConsoleLogger(level, stream=stream)

    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")

    logged = [line.split("] ")[2].strip("[]").lower() for line in stream.getvalue().splitlines()]
    assert logged == expected


def test_console_logger_applies_printf_style_arguments() -> None:
    stream = io.StringIO()

    ConsoleLogger("debug", stream=stream).debug("evaluated %r to %r", "my-flag", True)

    output = stream.getvalue()
    assert "[ConfigDirector:python-server-sdk]" in output
    assert "evaluated 'my-flag' to True" in output


def test_a_stdlib_logger_satisfies_the_logger_protocol() -> None:
    stdlib_logger: ConfigDirectorLogger = logging.getLogger("configdirector.test")

    assert isinstance(stdlib_logger, ConfigDirectorLogger)


def test_a_stdlib_logger_can_be_supplied(caplog: pytest.LogCaptureFixture) -> None:
    client = ConfigDirectorClient(SDK_KEY, logger=logging.getLogger("my_app.flags"))

    with caplog.at_level(logging.DEBUG, logger="my_app.flags"):
        client.initialize()

    assert any("client is ready" in record.message for record in caplog.records)
