"""Public types for the ConfigDirector server SDK."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, TypeVar, overload, runtime_checkable

__all__ = [
    "ClientEvent",
    "ClientHooks",
    "ClientReadyEvent",
    "ClientReadyHandler",
    "ConfigDirectorClient",
    "ConfigDirectorLogger",
    "ConfigEvaluatedEvent",
    "ConfigEvaluatedHandler",
    "ConfigEvaluation",
    "ConfigState",
    "ConfigType",
    "ConfigValue",
    "ConfigValueT",
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

ConnectionMode = Literal["streaming", "polling"]
"""How the SDK retrieves config state from ConfigDirector."""

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

        client = create_client("YOUR-SERVER-SDK-KEY", logger=logging.getLogger("my_app"))

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
        mode: The connection mode, one of ``"streaming"`` (default) or ``"polling"``.

            With ``"streaming"``, the connection stays open and receives updates whenever
            config state changes in the ConfigDirector dashboard.

            With ``"polling"``, config state is retrieved once during initialization and then
            re-fetched every ``polling_interval``.
        polling_interval: The polling interval **in seconds**, used only when ``mode`` is
            ``"polling"``. Must be at least 60 seconds. Defaults to 5 minutes (300 seconds)
            when omitted.
        timeout: The timeout **in seconds** applied to initialization. When streaming is
            enabled, initialization may still succeed after the timeout elapses as long as no
            unrecoverable error (such as an invalid SDK key) is encountered. When streaming is
            disabled, a timed-out initialization is not retried. Defaults to 3 seconds.
        url: The base URL of the ConfigDirector SDK server. Only needed when routing through a
            proxy; refer to the docs on configuring a proxy for the server SDK.
    """

    mode: ConnectionMode = "streaming"
    polling_interval: float | None = None
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
"""A handler for the ``client_ready`` event."""

ConfigsUpdatedHandler = Callable[[ConfigsUpdatedEvent], None]
"""A handler for the ``configs_updated`` event."""

ConfigEvaluatedHandler = Callable[[ConfigEvaluatedEvent], None]
"""A handler for the ``config_evaluated`` event."""


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


@runtime_checkable
class ConfigDirectorClient(Protocol):
    """The ConfigDirector SDK client.

    This is the public type of a client: the interface applications program against, and what
    :func:`~configdirector.create_client` returns. It is an interface rather than a class, so it
    cannot be instantiated — build a client with :func:`~configdirector.create_client`, which is
    the only supported entry point::

        from configdirector import ConfigDirectorClient, create_client

        def in_new_checkout(client: ConfigDirectorClient, user_id: str) -> bool:
            return client.get_value("new-checkout", False, Context(id=user_id))

        client = create_client("YOUR-SERVER-SDK-KEY")

    Applications should create a single client, call :meth:`initialize` during startup, and
    :meth:`close` during shutdown. The client is safe to share across threads.

    Using it as a context manager initializes it on entry and closes it on exit::

        with create_client("YOUR-SERVER-SDK-KEY") as client:
            if client.get_value("new-checkout", False, Context(id="user-123")):
                ...
    """

    # -- lifecycle --------------------------------------------------------------------

    def initialize(self, timeout: float | None = None) -> None:
        """Connect to ConfigDirector and retrieve config definitions.

        This blocks until the initial config state has been received or the timeout elapses.
        Until initialization succeeds, every config returns the default you pass to
        :meth:`get_value` or :meth:`watch`.

        If the connection fails or is interrupted by a transient error (network error, internal
        server error, and so on) the client keeps trying to connect. If it fails with a
        persistent error, such as an invalid SDK key, the client stops retrying and the error is
        logged.

        This does not raise on connection failure — check :attr:`is_ready` to find out whether
        config state was actually received.

        Args:
            timeout: Seconds to wait, overriding
                :attr:`~configdirector.types.ConnectionOptions.timeout` for this call.

        Raises:
            ConfigDirectorValidationError: If ``timeout`` is not positive, or the client is
                closed.
        """
        ...

    @property
    def is_ready(self) -> bool:
        """Whether the client is ready following a call to :meth:`initialize`.

        Ready means the connection to the server succeeded and config definitions were received.
        """
        ...

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        ...

    def close(self) -> None:
        """Close the client.

        Closes all connections, flushes pending telemetry, and cancels every event and config
        key subscription. Intended to be called when your application shuts down. Safe to call
        more than once.
        """
        ...

    def __enter__(self) -> ConfigDirectorClient:
        """Initialize the client, unless it is ready already, and return it."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client."""
        ...

    # -- evaluation -------------------------------------------------------------------

    def get_value(
        self,
        config_key: str,
        default: ConfigValueT,
        context: Context | None = None,
    ) -> ConfigValueT:
        """Evaluate a config and return its value for the given context.

        Args:
            config_key: The config key to evaluate.
            default: The value to return if config state is unavailable — for example if the
                client is not ready, the key is unknown, or the stored value cannot be read as
                the default's type. Its type also determines the type the config is parsed as.
            context: The user's context, used for targeting rule evaluation.

        Raises:
            ConfigDirectorValidationError: If ``config_key`` is blank.
            ConfigDirectorTypeError: If ``default`` is ``None`` or of an unsupported type.
        """
        ...

    def get_all_configs(
        self,
        context: Context | None = None,
        config_keys: Sequence[str] | None = None,
    ) -> dict[str, ConfigState]:
        """Return the evaluated :class:`ConfigState` for every known key.

        Intended for server-side rendering hydration. This does **not** record telemetry events,
        and returns an empty mapping when the client is not yet ready.

        Args:
            context: The user's context, used for targeting rule evaluation.
            config_keys: Restrict the result to these keys. When omitted, every known key is
                returned.
        """
        ...

    # -- watching ---------------------------------------------------------------------

    def watch(
        self,
        config_key: str,
        default: ConfigValueT,
        callback: WatchHandler[ConfigValueT],
        context: Context | None = None,
    ) -> Subscription:
        """Call ``callback`` with the new value whenever ``config_key`` changes.

        The callback runs on the SDK's background connection thread rather than the thread that
        registered it, so it should be quick and thread-safe. An exception it raises is logged
        and does not affect other watchers.

        Args:
            config_key: The config key to watch.
            default: The value passed to the callback when config state is unavailable. Its type
                also determines the type the config is parsed as.
            callback: Called with the new value on every change.
            context: The user's context, used for targeting rule evaluation.

        Returns:
            A :class:`Subscription`. Call ``close()`` on it to stop watching, or use it as a
            context manager.

        Raises:
            ConfigDirectorValidationError: If ``config_key`` is blank.
            ConfigDirectorTypeError: If ``default`` is unsupported or ``callback`` is not
                callable.
        """
        ...

    def unwatch(self, config_key: str, callback: WatchHandler[Any] | None = None) -> None:
        """Remove one or every watcher for ``config_key``.

        Args:
            config_key: The config key to remove watchers from.
            callback: The callback to remove. When omitted, every watcher for ``config_key`` is
                removed.
        """
        ...

    def unwatch_all(self) -> None:
        """Remove every watcher for every config key."""
        ...

    # -- events -----------------------------------------------------------------------

    @overload
    def on(
        self, event: Literal["client_ready"], handler: Callable[[ClientReadyEvent], None]
    ) -> Subscription: ...

    @overload
    def on(
        self, event: Literal["configs_updated"], handler: Callable[[ConfigsUpdatedEvent], None]
    ) -> Subscription: ...

    @overload
    def on(
        self, event: Literal["config_evaluated"], handler: Callable[[ConfigEvaluatedEvent], None]
    ) -> Subscription: ...

    def on(self, event: ClientEvent, handler: Callable[[Any], None]) -> Subscription:
        """Register ``handler`` to be called whenever ``event`` is emitted.

        Args:
            event: One of ``"client_ready"``, ``"configs_updated"``, or ``"config_evaluated"``.
            handler: Called with the event payload.

        Returns:
            A :class:`Subscription`. Call ``close()`` on it to unregister the handler, or use it
            as a context manager.

        Raises:
            ConfigDirectorValidationError: If ``event`` is not a known event name.
            ConfigDirectorTypeError: If ``handler`` is not callable.
        """
        ...

    @overload
    def off(
        self, event: Literal["client_ready"], handler: Callable[[ClientReadyEvent], None] | None = None
    ) -> None: ...

    @overload
    def off(
        self,
        event: Literal["configs_updated"],
        handler: Callable[[ConfigsUpdatedEvent], None] | None = None,
    ) -> None: ...

    @overload
    def off(
        self,
        event: Literal["config_evaluated"],
        handler: Callable[[ConfigEvaluatedEvent], None] | None = None,
    ) -> None: ...

    def off(self, event: ClientEvent, handler: Callable[[Any], None] | None = None) -> None:
        """Unregister an event handler.

        Args:
            event: One of ``"client_ready"``, ``"configs_updated"``, or ``"config_evaluated"``.
            handler: The handler to remove. When omitted, every handler for ``event`` is
                removed.

        Raises:
            ConfigDirectorValidationError: If ``event`` is not a known event name.
        """
        ...
