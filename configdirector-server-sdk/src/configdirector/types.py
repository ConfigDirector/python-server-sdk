"""Public types for the ConfigDirector server SDK."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
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
    "TrackedEvent",
    "TrackedEventDetailValue",
    "TrackedEventDetails",
    "Variation",
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

ConnectionMode = Literal["streaming", "polling", "offline"]
"""How the SDK retrieves config state from ConfigDirector, or ``"offline"`` to serve the values the
application gives it without connecting."""

EvaluationReason = Literal[
    "found-match",
    "rollout-skipped-no-identifier",
    "config-state-missing",
    "client-not-ready",
    "type-mismatch",
    "value-missing",
    "invalid-number",
    "invalid-json",
    "invalid-boolean",
]
"""Why an evaluation produced the value that it did.

``"found-match"`` returns a value from ConfigDirector. ``"rollout-skipped-no-identifier"`` returns
the default targeting rule value: the SDK skipped a percentage rollout because the context has no
``id`` to place it in a share. ``"value-missing"`` returns the in-code default value because the
config has no value. Every other reason returns the in-code default value because of an error: the
config does not exist (``"config-state-missing"``), no values have arrived yet
(``"client-not-ready"``), or the value cannot be read as the type of the in-code default value
(``"type-mismatch"``, ``"invalid-number"``, ``"invalid-json"``, ``"invalid-boolean"``)."""


TrackedEventDetailValue = (
    str
    | int
    | float
    | bool
    | datetime
    | Sequence["TrackedEventDetailValue"]
    | Mapping[str, "TrackedEventDetailValue"]
)
"""A value in the details of a tracked event: a string, a number, a boolean, a ``datetime``, which
is sent as ISO 8601 text, or a nested object or list of such values."""

TrackedEventDetails = Mapping[str, TrackedEventDetailValue]
"""Details of a tracked event, such as the plan a customer chose. Details with more than 20
top-level keys, or larger than 1 KB as JSON, are left out and the event is still reported."""


@dataclass(frozen=True, slots=True)
class Context:
    """The user's context, used for targeting rule evaluation.

    Attributes:
        id: The user's identifier. This should uniquely identify an application user.
            For anonymous users you may generate a UUID or use a session ID. Keep in mind this
            value segments users in percentage rollouts, so changing it can move a user into a
            different percentile. A context without an ``id`` skips percentage rollouts: the
            targeting rules after the rollout are tried, and it is served the default targeting
            rule value when none applies.
        name: The user's display name. Shown in the ConfigDirector dashboard and usable in
            targeting rules.
        traits: Arbitrary traits for the current user. Shown in the ConfigDirector dashboard
            and usable in targeting rules.
        anonymous: When ``True``, the context is used for targeting rule evaluation but is
            not persisted and will not appear in the dashboard. Defaults to ``False``.
        kind: What kind of entity the context represents, such as ``"device"``,
            ``"organization"`` or ``"tenant"``. A keyword-only argument. Leaving it out, or passing
            ``None``, means ``"user"``. A kind has 1 to 64 characters, using only lowercase
            letters, digits, ``-`` and ``_``, and is used exactly as given, without trimming or
            changing its case. Contexts of different kinds that share an ``id`` are different
            contexts, and percentage rollouts assign each kind its own percentile.

            Building a context never fails because of its kind. When a context's kind is
            invalid, including any kind that is not a ``str``, the SDK ignores the whole
            context: it evaluates exactly as if no context had been supplied, logs an error, and
            reports the evaluation's context as ``None``.
    """

    id: str | None = None
    name: str | None = None
    traits: dict[str, Any] | None = None
    anonymous: bool = False
    kind: str | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class TrackedEvent:
    """An event the code under test tracked, as a test client recorded it.

    Attributes:
        name: The name the event was tracked with.
        context: The context the event was tracked for, if any.
        value: The value the event was tracked with, when it is a finite number.
        details: The details the event was tracked with, when they are within the limits, as the
            SDK would report them: a ``datetime`` is held as its ISO 8601 text.
    """

    name: str
    context: Context | None = None
    value: int | float | Decimal | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Metadata:
    """Metadata about your application.

    It is recommended you supply these values when creating a client so that they can be
    referenced from targeting rules.
    """

    app_name: str | None = None
    app_version: str | None = None


@dataclass(frozen=True, slots=True)
class Variation:
    """One of the values a config can serve, such as the control or a treatment of an experiment.

    Attributes:
        id: The ID ConfigDirector assigned to the variation, which stays the same when it is
            renamed.
        name: The variation's name, or ``None`` when it has none.
    """

    id: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigState:
    """The raw, evaluated state of a single config, before type parsing.

    Attributes:
        id: The config's ID.
        key: The config's key.
        type: The type the config was declared with.
        value: The value served, as text.
        value_id: The ID ConfigDirector assigned to the value served, when it sent one.
        variation: The variation that was served, or ``None`` when the config has no variations.
        rule_id: The ID of the percentage rollout's targeting rule when a rollout served the
            value, otherwise ``None``.
        share_id: The ID of the percentage rollout's share when a rollout served the value,
            otherwise ``None``.
    """

    id: str
    key: str
    type: ConfigType
    value: str | None
    value_id: str | None = None
    variation: Variation | None = None
    rule_id: str | None = None
    share_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigEvaluation:
    """The result of evaluating a single config key.

    Attributes:
        key: The config key that was evaluated.
        value: The value the evaluation returned.
        is_default: Whether the evaluation returned the in-code default value.
        reason: Why the evaluation returned this value.
        value_id: The ID of the value returned.
        context: The context the config was evaluated for, or ``None`` when no context was
            supplied or it was ignored for an invalid kind.
        variation: The variation that was served, or ``None`` when the config has no variations
            or the in-code default value is returned.
    """

    key: str
    value: ConfigValue
    is_default: bool
    reason: EvaluationReason
    value_id: str | None = None
    context: Context | None = None
    variation: Variation | None = None


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
        mode: The connection mode, one of ``"streaming"`` (default), ``"polling"`` or
            ``"offline"``.

            With ``"streaming"``, the connection stays open and receives updates whenever
            config state changes in the ConfigDirector dashboard.

            With ``"polling"``, config state is retrieved once during initialization and then
            re-fetched every ``polling_interval``.

            With ``"offline"``, the client never connects to ConfigDirector and sends nothing.
            It needs no server SDK key, and serves the values given in ``file`` or ``values``
            to every context. With neither, every config returns its in-code default value.
        polling_interval: The polling interval **in seconds**, used only when ``mode`` is
            ``"polling"``. Defaults to 5 minutes (300 seconds) when omitted. The minimum is 60
            seconds. A value below the minimum is raised to the minimum and a warning is logged.
        timeout: The timeout **in seconds** applied to initialization. When streaming is
            enabled, initialization may still succeed after the timeout elapses as long as no
            unrecoverable error (such as an invalid SDK key) is encountered. When streaming is
            disabled, a timed-out initialization is not retried. Defaults to 3 seconds. Not used
            when ``mode`` is ``"offline"``.
        url: The base URL of the ConfigDirector SDK server. Only needed when routing through a
            proxy; refer to the docs on configuring a proxy for the server SDK. Not used when
            ``mode`` is ``"offline"``.
        file: The path of a JSON file holding the values to serve when ``mode`` is
            ``"offline"``, as one JSON object with one value per config key, such as
            ``{"new-checkout": true, "max-items": 20}``. A relative path is resolved against the
            working directory. The file is read when :meth:`ConfigDirectorClient.initialize`
            is called.
        values: The values to serve when ``mode`` is ``"offline"``, keyed by config key. The
            config type follows from each value's type: a ``bool``; an ``int`` (an integer
            config); a ``float`` (a float config); a ``str``; or a ``dict`` with ``str`` keys or a
            ``list`` (a JSON config). The values of a ``file`` follow the same rule once read.

            Only one of ``file`` and ``values`` can be given, and only when ``mode`` is
            ``"offline"``; otherwise :meth:`ConfigDirectorClient.initialize` raises
            :class:`~configdirector.ConfigDirectorInitializationError`.
    """

    mode: ConnectionMode = "streaming"
    polling_interval: float | None = None
    timeout: float = 3.0
    url: str | None = None
    file: str | os.PathLike[str] | None = None
    values: Mapping[str, ConfigValue] | None = None


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
        keys: The config keys included in the update, and the keys of every config whose
            targeting rules use a segment the update included, sorted.
        removed_keys: The keys a full update no longer included, so the client stopped serving
            them, sorted. Empty when nothing was removed, and always empty for a delta update.
    """

    keys: list[str]
    removed_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConfigEvaluatedEvent:
    """Emitted every time a config is evaluated."""

    evaluation: ConfigEvaluation


ClientEvent = Literal["client_ready", "configs_updated", "config_evaluated"]
"""The names of the events emitted by the client."""

WatchHandler = Callable[[ConfigValueT], None]
"""A callback invoked with the newly evaluated value whenever an update carries the watched
config or a segment its targeting rules use, and with the default whenever a full update no
longer carries it."""

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

        When the connection mode is ``"offline"``, this connects to nothing: it loads the offline
        values, makes the client ready and returns at once, and ``timeout`` is not used. Calling
        it again loads the values again, reading the file again when they come from a file.

        Args:
            timeout: Seconds to wait, overriding
                :attr:`~configdirector.types.ConnectionOptions.timeout` for this call.

        Raises:
            ConfigDirectorValidationError: If ``timeout`` is not positive outside offline mode, or
                the client is closed.
            ConfigDirectorInitializationError: If the offline values cannot be loaded: the file is
                missing, cannot be read, is not valid JSON or does not hold a JSON object; a value
                is ``None`` or another value a config cannot hold; ``file`` and ``values`` are both
                given; or either is given when the connection mode is ``"streaming"`` or
                ``"polling"``. The client stays not ready, or keeps serving the values an earlier
                call loaded.
        """
        ...

    @property
    def is_ready(self) -> bool:
        """Whether the client is ready following a call to :meth:`initialize`.

        Ready means the connection to the server succeeded and config definitions were received,
        or, in offline mode, that the offline values were loaded.
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

    def evaluate(
        self,
        config_key: str,
        default: ConfigValue,
        context: Context | None = None,
    ) -> ConfigEvaluation:
        """Evaluate a config as :meth:`get_value` does and return the evaluation: the value, the
        reason it was served, its value ID and its variation.

        Like every read, it fires ``config_evaluated`` and is counted in telemetry.

        Args:
            config_key: The config key to evaluate.
            default: The in-code default value, returned when no value from ConfigDirector can be
                served. Its type also determines the type the config is parsed as.
            context: The user's context, used for targeting rule evaluation.

        Returns:
            The evaluation, whose ``value`` is what :meth:`get_value` returns.

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
        except that a call given a context with an invalid kind is counted once as an invalid
        context submission and may log an error. It returns an empty mapping when the client is
        not yet ready.

        Args:
            context: The user's context, used for targeting rule evaluation.
            config_keys: Restrict the result to these keys. When omitted, every known key is
                returned.
        """
        ...

    def track(
        self,
        event_name: str,
        context: Context | None = None,
        *,
        value: int | float | Decimal | None = None,
        details: TrackedEventDetails | None = None,
    ) -> None:
        """Report to ConfigDirector that something happened, such as a completed checkout, so it
        can be counted. The event is sent with the next telemetry batch. ``track`` never raises,
        and does nothing in offline mode or after :meth:`close`.

        An event counts for an experiment only when it is tracked for a context with an ``id``,
        the one the experiment's config was evaluated for. Without a context, or for a context
        without an ``id``, the event is still reported. The ``id`` of a context marked
        ``anonymous`` is not sent.

        A telemetry batch holds at most 1,000 tracked events, and events beyond that are not
        reported. Each cause of an event being dropped or sent without its value or details logs
        one warning per telemetry batch.

        Args:
            event_name: The name of the event, 1 to 150 characters. An event with any other name
                is not reported.
            context: The context the event happened for. When its kind is invalid, the SDK logs
                an error as it does for an evaluation and sends the event without a context.
            value: A number the event measures, such as an amount of money, a count or a
                duration. ConfigDirector stores it as an exact decimal, and a ``Decimal`` is sent
                with every digit. A value that is not a finite number is left out and the event
                is still reported.
            details: Details of the event, whose values are strings, numbers, booleans, ``datetime``
                values, or nested objects and lists. A ``datetime`` is sent as ISO 8601 text,
                keeping its UTC offset if it has one, and counts toward the size as that text.
                Details with more than 20 top-level keys, larger than 1 KB as JSON, or holding any
                other type of value are left out and the event is still reported.
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
        """Call ``callback`` with the newly evaluated value whenever an update carries
        ``config_key`` or a segment its targeting rules use, and with ``default`` whenever a full
        update no longer carries it.

        The callback runs on the SDK's background connection thread rather than the thread that
        registered it, so it should be quick and thread-safe. An exception it raises is logged
        and does not affect other watchers.

        Args:
            config_key: The config key to watch.
            default: The value passed to the callback when config state is unavailable or the
                config was removed. Its type also determines the type the config is parsed as.
            callback: Called with the newly evaluated value on every update that carries or
                removes ``config_key``, or that carries a segment its targeting rules use.
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
