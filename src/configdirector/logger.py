"""Logging for the SDK.

By default the SDK logs to the standard library logger named ``configdirector``, leaving your
application in control of formatting, levels, and destinations. With no logging configured at
all, Python's last-resort handler still surfaces warnings and errors on ``stderr``, so an
invalid SDK key never passes silently.

Use :func:`create_console_logger` instead if you want SDK output without configuring the
:mod:`logging` module.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

from .types import ConfigDirectorLogger, LoggingLevel

__all__ = ["ConsoleLogger", "create_console_logger", "get_default_logger"]

LOGGER_NAME = "configdirector"

_LEVELS: dict[LoggingLevel, int] = {
    "off": -1,
    "error": 0,
    "warning": 1,
    "info": 2,
    "debug": 3,
}

_PREFIX = "[ConfigDirector:python-server-sdk]"


def get_default_logger() -> ConfigDirectorLogger:
    """Return the standard library logger the SDK uses when none is supplied.

    Configure it like any other logger::

        logging.getLogger("configdirector").setLevel(logging.DEBUG)
    """
    return logging.getLogger(LOGGER_NAME)


class ConsoleLogger:
    """Writes SDK log messages to a stream, ``sys.stderr`` by default.

    Messages below ``level`` are discarded. ``message`` is a printf-style template and ``args``
    are its arguments, matching :class:`logging.Logger`.
    """

    __slots__ = ("_level", "_stream")

    def __init__(self, level: LoggingLevel = "warning", stream: TextIO | None = None) -> None:
        if level not in _LEVELS:
            raise ValueError(f"Invalid logging level '{level}'. Expected one of: {', '.join(_LEVELS)}.")
        self._level = level
        self._stream = stream

    @property
    def level(self) -> LoggingLevel:
        return self._level

    def debug(self, message: str, /, *args: Any) -> None:
        self._log("debug", message, *args)

    def info(self, message: str, /, *args: Any) -> None:
        self._log("info", message, *args)

    def warning(self, message: str, /, *args: Any) -> None:
        self._log("warning", message, *args)

    def error(self, message: str, /, *args: Any) -> None:
        self._log("error", message, *args)

    def _log(self, level: LoggingLevel, message: str, *args: Any) -> None:
        if _LEVELS[self._level] < _LEVELS[level]:
            return

        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        # Resolved at call time so that tools which swap out sys.stderr keep working.
        stream = self._stream if self._stream is not None else sys.stderr
        print(f"[{timestamp}] {_PREFIX} [{level.upper()}] {message % args if args else message}", file=stream)


def create_console_logger(level: LoggingLevel = "warning") -> ConfigDirectorLogger:
    """Create a logger that writes SDK output straight to ``stderr``.

    Useful for turning up SDK verbosity without wiring in the :mod:`logging` module::

        from configdirector import ConfigDirectorClient, create_console_logger

        client = ConfigDirectorClient("YOUR-SERVER-SDK-KEY", logger=create_console_logger("debug"))

    Args:
        level: One of ``"debug"``, ``"info"``, ``"warning"``, ``"error"``, or ``"off"``.
            Defaults to ``"warning"``.

    Raises:
        ValueError: If ``level`` is not a valid logging level.
    """
    return ConsoleLogger(level)
