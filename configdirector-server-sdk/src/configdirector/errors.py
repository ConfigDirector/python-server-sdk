"""Exceptions raised by the ConfigDirector SDK.

Every exception inherits from :class:`ConfigDirectorError`, so ``except ConfigDirectorError``
catches anything the SDK raises. The argument-validation errors additionally inherit from the
built-in exception a Python caller would expect — :class:`ValueError` for a bad value,
:class:`TypeError` for a bad type — so ordinary handlers keep working too.
"""

from __future__ import annotations

__all__ = [
    "ConfigDirectorConnectionError",
    "ConfigDirectorError",
    "ConfigDirectorInitializationError",
    "ConfigDirectorTypeError",
    "ConfigDirectorValidationError",
]


class ConfigDirectorError(Exception):
    """Base class for every error raised by the ConfigDirector SDK."""


class ConfigDirectorConnectionError(ConfigDirectorError):
    """Raised when the SDK fails to communicate with the ConfigDirector servers.

    Attributes:
        status: The HTTP status code returned by the server, when one was received.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ConfigDirectorValidationError(ConfigDirectorError, ValueError):
    """Raised when an argument has an unusable value, such as an empty config key."""


class ConfigDirectorTypeError(ConfigDirectorError, TypeError):
    """Raised when an argument has an unsupported type, such as a ``set`` default value."""


class ConfigDirectorInitializationError(ConfigDirectorError):
    """Raised when the client cannot be initialized."""
