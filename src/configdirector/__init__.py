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
    ClientReadyHandler,
    ConfigDirectorLogger,
    ConfigEvaluatedEvent,
    ConfigEvaluatedHandler,
    ConfigEvaluation,
    ConfigState,
    ConfigsUpdatedEvent,
    ConfigsUpdatedHandler,
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
    "ClientReadyHandler",
    "ConfigDirectorClient",
    "ConfigDirectorConnectionError",
    "ConfigDirectorError",
    "ConfigDirectorInitializationError",
    "ConfigDirectorLogger",
    "ConfigDirectorTypeError",
    "ConfigDirectorValidationError",
    "ConfigEvaluatedEvent",
    "ConfigEvaluatedHandler",
    "ConfigEvaluation",
    "ConfigState",
    "ConfigType",
    "ConfigValue",
    "ConfigsUpdatedEvent",
    "ConfigsUpdatedHandler",
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
