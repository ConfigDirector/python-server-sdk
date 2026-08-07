"""ConfigDirector Python server SDK.

ConfigDirector is a remote configuration and feature flag service.

Example::

    from configdirector import ConfigDirectorClient, Context, Metadata

    client = ConfigDirectorClient(
        "YOUR-SERVER-SDK-KEY",
        metadata=Metadata(app_name="my-awesome-app", app_version="1.0.0"),
    )
    client.initialize()

    if client.get_value("new-checkout", False, Context(id="user-123")):
        ...
"""

from ._version import __version__
from .client import ConfigDirectorClient, create_client
from .errors import (
    ConfigDirectorConnectionError,
    ConfigDirectorError,
    ConfigDirectorInitializationError,
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
)
from .types import (
    ClientEvent,
    ClientHooks,
    ClientReadyEvent,
    ConfigDirectorLogger,
    ConfigEvaluatedEvent,
    ConfigEvaluation,
    ConfigState,
    ConfigsUpdatedEvent,
    ConfigType,
    ConfigValue,
    ConnectionMode,
    ConnectionOptions,
    Context,
    EvaluationReason,
    Metadata,
    Subscription,
    TelemetryOptions,
    WatchHandler,
)

__all__ = [
    "ClientEvent",
    "ClientHooks",
    "ClientReadyEvent",
    "ConfigDirectorClient",
    "ConfigDirectorConnectionError",
    "ConfigDirectorError",
    "ConfigDirectorInitializationError",
    "ConfigDirectorLogger",
    "ConfigDirectorTypeError",
    "ConfigDirectorValidationError",
    "ConfigEvaluatedEvent",
    "ConfigEvaluation",
    "ConfigState",
    "ConfigType",
    "ConfigValue",
    "ConfigsUpdatedEvent",
    "ConnectionMode",
    "ConnectionOptions",
    "Context",
    "EvaluationReason",
    "Metadata",
    "Subscription",
    "TelemetryOptions",
    "WatchHandler",
    "__version__",
    "create_client",
]
