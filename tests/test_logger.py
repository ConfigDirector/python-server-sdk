from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from configdirector import ConfigDirectorClient, create_client
from configdirector._logger import get_default_logger

SDK_KEY = "test-server-sdk-key"

# Spelled out rather than imported, because the name being exactly this is what is under test.
LOGGER_NAME = "configdirector"


@pytest.fixture(autouse=True)
def restore_the_package_logger() -> Iterator[None]:
    """Loggers are process-wide, so a test that changes one has to hand it back."""
    logger = logging.getLogger(LOGGER_NAME)
    level = logger.level
    yield
    logger.setLevel(level)


def test_the_default_logger_is_named_for_the_package() -> None:
    assert get_default_logger().name == "configdirector"


def test_no_level_is_imposed_when_none_is_given() -> None:
    assert get_default_logger().level == logging.NOTSET


def test_the_application_keeps_control_of_the_level() -> None:
    # The configuration the README and the client docstring both tell users to write.
    logging.getLogger("configdirector").setLevel(logging.DEBUG)

    assert get_default_logger().isEnabledFor(logging.DEBUG) is True


def test_warnings_reach_an_application_that_configured_nothing() -> None:
    # An unconfigured application inherits the root logger's WARNING, which logging.lastResort
    # then carries to stderr. That is what keeps an invalid SDK key from failing silently.
    assert get_default_logger().isEnabledFor(logging.WARNING) is True


@pytest.mark.parametrize(
    ("log_level", "expected"),
    [(logging.DEBUG, logging.DEBUG), ("INFO", logging.INFO)],
)
def test_applies_an_explicit_log_level(log_level: int | str, expected: int) -> None:
    assert get_default_logger(log_level).level == expected


def test_the_client_logs_through_the_package_logger() -> None:
    client = ConfigDirectorClient(SDK_KEY)

    assert client._logger is logging.getLogger("configdirector")


def test_the_client_applies_an_explicit_log_level() -> None:
    client = ConfigDirectorClient(SDK_KEY, log_level="DEBUG")

    assert isinstance(client._logger, logging.Logger)
    assert client._logger.isEnabledFor(logging.DEBUG) is True


def test_create_client_applies_an_explicit_log_level() -> None:
    client = create_client(SDK_KEY, log_level="DEBUG")

    assert isinstance(client._logger, logging.Logger)
    assert client._logger.isEnabledFor(logging.DEBUG) is True
