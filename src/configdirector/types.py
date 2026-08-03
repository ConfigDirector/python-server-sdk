"""Public types for the ConfigDirector server SDK."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

__all__ = [
    "ClientEvent",
    "ClientHooks",
    "ClientReadyEvent",
    "ConfigDirectorLogger",
    "ConfigEvaluatedEvent",
    "ConfigEvaluation",
    "ConfigState",
    "ConfigType",
    "ConfigValue",
    "ConfigValueT",
    "ConfigsUpdatedEvent",
    "ConnectionMode",
    "ConnectionOptions",
    "Context",
    "EvaluationReason",
    "LoggingLevel",
    "Metadata",
    "Subscription",
    "TelemetryOptions",
    "WatchHandler",
]


ConfigType = Literal[
    "custom",
    "boolean",
    "string",
    "integer",
    "float",
    "enum",
    "url",
    "json",
]
"""The type a config was declared with in the ConfigDirector dashboard."""

ConfigValue = str | int | float | bool | dict[str, Any] | list[Any]
"""Every value type a config can evaluate to."""

ConfigValueT = TypeVar("ConfigValueT", bound=ConfigValue)

ConnectionMode = Literal["streaming", "polling", "one-time"]
"""How the SDK retrieves config state from ConfigDirector."""

LoggingLevel = Literal["debug", "info", "warning", "error", "off"]
"""Verbosity of the SDK's console logger."""

EvaluationReason = Literal[
    "found-match",
    "config-state-missing",
    "client-not-ready",
    "type-mismatch",
    "value-missing",
    "invalid-number",
    "invalid-json",
    "invalid-boolean",
]
"""Why an evaluation produced the value that it did."""


@dataclass(frozen=True, slots=True)
class Context:
    """The user's context, used for targeting rule evaluation.

    Attributes:
        id: The user's identifier. This should uniquely identify an application user.
            For anonymous users you may generate a UUID, or omit ``id`` entirely and let
            the SDK generate one. Keep in mind this value segments users in percentage
            rollouts, so changing it can move a user into a different percentile.
        name: The user's display name. Shown in the ConfigDirector dashboard and usable in
            targeting rules.
        traits: Arbitrary traits for the current user. Shown in the ConfigDirector dashboard
            and usable in targeting rules.
        anonymous: When ``True``, the context is used for targeting rule evaluation but is
            not persisted and will not appear in the dashboard. Defaults to ``False``.
    """

    id: str | None = None
    name: str | None = None
    traits: dict[str, Any] | None = None
    anonymous: bool = False


@dataclass(frozen=True, slots=True)
class Metadata:
    """Metadata about your application.

    It is recommended you supply these values when creating a client so that they can be
    referenced from targeting rules.
    """

    app_name: str | None = None
    app_version: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigState:
    """The raw, evaluated state of a single config, before type parsing."""

    id: str
    key: str
    type: ConfigType
    value: str | None
    value_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigEvaluation:
    """The result of evaluating a single config key."""

    key: str
    value: ConfigValue
    is_default: bool
    reason: EvaluationReason
    value_id: str | None = None
    context: Context | None = None


@runtime_checkable
class ConfigDirectorLogger(Protocol):
    """The logging interface the SDK writes to.

    The signatures match :class:`logging.Logger`, so a standard library logger can be passed
    straight through::

        import logging

        client = ConfigDirectorClient("YOUR-SERVER-SDK-KEY", logger=logging.getLogger("my_app"))

    The SDK always logs lazily — ``message`` is a printf-style template and ``args`` are its
    arguments — so that suppressed messages cost nothing to build.
    """

    def debug(self, message: str, /, *args: Any) -> None: ...

    def info(self, message: str, /, *args: Any) -> None: ...

    def warning(self, message: str, /, *args: Any) -> None: ...

    def error(self, message: str, /, *args: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class ConnectionOptions:
    """Options controlling how the client connects to ConfigDirector.

    Attributes:
        mode: The connection mode, one of ``"streaming"`` (default), ``"polling"``, or
            ``"one-time"``.

            With ``"streaming"``, the connection stays open and receives updates whenever
            config state changes in the ConfigDirector dashboard.

            With ``"polling"``, config state is retrieved once during initialization and then
            re-fetched every ``polling_interval``.

            With ``"one-time"``, config state is only retrieved during initialization and is
            never refreshed.
        polling_interval: The polling interval **in seconds**, used only when ``mode`` is
            ``"polling"``. Defaults to 60 seconds.
        timeout: The timeout **in seconds** applied to initialization. When streaming is
            enabled, initialization may still succeed after the timeout elapses as long as no
            unrecoverable error (such as an invalid SDK key) is encountered. When streaming is
            disabled, a timed-out initialization is not retried. Defaults to 3 seconds.
        url: The base URL of the ConfigDirector SDK server. Only needed when routing through a
            proxy; refer to the docs on configuring a proxy for the server SDK.
    """

    mode: ConnectionMode = "streaming"
    polling_interval: float = 60.0
    timeout: float = 3.0
    url: str | None = None


@dataclass(frozen=True, slots=True)
class TelemetryOptions:
    """Telemetry tuning.

    It is unlikely these settings need adjusting. However, if your application performs a large
    number of evaluations per second, they let you trade memory footprint against how often
    telemetry requests are made.

    Keep in mind that ConfigDirector relies on these telemetry events to power insights and
    features related to the configs being used.

    Attributes:
        event_queue_limit: The size limit of the telemetry event queues. If the limit is reached
            before events are flushed to the network, older events are dropped.

            ConfigDirector keeps a count of dropped events. If more than 50% of total events are
            dropped, ConfigDirector raises a notification alert in the dashboard.

            A number between 100 and 100,000. Defaults to 5,000.
        flush_interval: How often events are flushed and sent over the network, **in seconds**.
            Decrease this if your application consistently captures a large number of events in
            short bursts, to keep the event queue small. Defaults to 30 seconds.
    """

    event_queue_limit: int = 5_000
    flush_interval: float = 30.0


@dataclass(frozen=True, slots=True)
class ClientReadyEvent:
    """Emitted once the client has received its initial config state from the server."""


@dataclass(frozen=True, slots=True)
class ConfigsUpdatedEvent:
    """Emitted whenever config definitions are received from the server.

    Attributes:
        keys: The config keys included in the update.
    """

    keys: list[str]


@dataclass(frozen=True, slots=True)
class ConfigEvaluatedEvent:
    """Emitted every time a config is evaluated."""

    evaluation: ConfigEvaluation


ClientEvent = Literal["client_ready", "configs_updated", "config_evaluated"]
"""The names of the events emitted by the client."""

WatchHandler = Callable[[ConfigValueT], None]
"""A callback invoked with the new value whenever a watched config changes."""

ClientReadyHandler = Callable[[ClientReadyEvent], None]
ConfigsUpdatedHandler = Callable[[ConfigsUpdatedEvent], None]
ConfigEvaluatedHandler = Callable[[ConfigEvaluatedEvent], None]


class Subscription:
    """A handle to an active subscription, returned by ``watch()`` and ``on()``.

    Call :meth:`close` to cancel it, or use it as a context manager to scope it to a block::

        with client.watch("new-checkout", False, on_change):
            ...
        # no longer watching here

    Closing is idempotent.
    """

    __slots__ = ("_cancel", "_closed")

    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether this subscription has been cancelled."""
        return self._closed

    def close(self) -> None:
        """Cancel the subscription. Safe to call more than once."""
        if not self._closed:
            self._closed = True
            self._cancel()

    def __enter__(self) -> Subscription:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class ClientHooks:
    """Event handlers to attach when constructing a client.

    Purely a convenience over :meth:`ConfigDirectorClient.on` for code that configures the
    client declaratively; anything registered here can equally be registered afterwards. To
    attach more than one handler per event, call ``on()``.

    Example::

        client = ConfigDirectorClient(
            "YOUR-SERVER-SDK-KEY",
            hooks=ClientHooks(config_evaluated=lambda event: print(event.evaluation)),
        )
    """

    client_ready: ClientReadyHandler | None = None
    configs_updated: ConfigsUpdatedHandler | None = None
    config_evaluated: ConfigEvaluatedHandler | None = None
