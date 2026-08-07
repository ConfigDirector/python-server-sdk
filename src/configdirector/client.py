"""The ConfigDirector client."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, cast, overload
from urllib.parse import urlparse

from ._bundle import ConfigBundle
from ._evaluation import Config, ConfigEvaluator, EvaluationContext
from ._http import HttpClient
from ._logger import get_default_logger
from ._telemetry import (
    MAX_EVENT_QUEUE_LIMIT,
    MIN_EVENT_QUEUE_LIMIT,
    TelemetryCollector,
    TelemetryCollectorOptions,
    value_id_for,
)
from ._transport import TransportOptions, create_transport
from ._value_parser import parse_config_value
from ._version import _SDK_NAME, __version__
from .errors import ConfigDirectorTypeError, ConfigDirectorValidationError
from .types import (
    ClientEvent,
    ClientHooks,
    ClientReadyEvent,
    ConfigDirectorLogger,
    ConfigEvaluatedEvent,
    ConfigEvaluation,
    ConfigState,
    ConfigsUpdatedEvent,
    ConfigValue,
    ConfigValueT,
    ConnectionOptions,
    Context,
    EvaluationReason,
    Metadata,
    Subscription,
    TelemetryOptions,
    WatchHandler,
)

__all__ = ["ConfigDirectorClient", "create_client"]

_DEFAULT_BASE_URL = "https://server-sdk-api.configdirector.com"

_EVENT_NAMES: frozenset[str] = frozenset({"client_ready", "configs_updated", "config_evaluated"})

_VALID_VALUE_TYPES: tuple[type, ...] = (str, int, float, bool, dict, list)


@dataclass(slots=True, eq=False)  # identity comparison: two identical watches stay distinct
class _Watcher:
    handler: WatchHandler[Any]
    default: ConfigValue
    context: Context | None


class ConfigDirectorClient:
    """The ConfigDirector SDK client.

    Applications should create a single client, call :meth:`initialize` during startup, and
    :meth:`close` during shutdown. The client is safe to share across threads.

    Using it as a context manager initializes it on entry and closes it on exit::

        with ConfigDirectorClient("YOUR-SERVER-SDK-KEY") as client:
            if client.get_value("new-checkout", False, Context(id="user-123")):
                ...

    Args:
        server_sdk_key: Your ConfigDirector server SDK key. This is a secret value — do not
            commit it to source control.
        metadata: Metadata about your application. Supplying ``app_name`` and ``app_version`` is
            recommended so that they can be referenced from targeting rules.
        connection: Connection options such as mode, timeout, and polling interval.
        logger: Any object implementing :class:`~configdirector.types.ConfigDirectorLogger`,
            including a standard library :class:`logging.Logger`. Defaults to the standard
            library logger named ``"configdirector"``, which your application configures like
            any other logger.
        log_level: A level to set on that default logger, as either a :mod:`logging` constant
            or its name. A convenience for applications that do not otherwise configure
            logging; when omitted, the SDK sets no level and the usual ``logging`` rules apply.
            Ignored when ``logger`` is supplied.
        telemetry: Telemetry queue and flush tuning.
        hooks: Event handlers to attach before the client can emit any event.

    Raises:
        ConfigDirectorValidationError: If ``server_sdk_key`` is missing or empty, if
            ``connection.url`` is not a valid URL, or if a ``telemetry`` setting is out of range.
    """

    def __init__(
        self,
        server_sdk_key: str,
        *,
        metadata: Metadata | None = None,
        connection: ConnectionOptions | None = None,
        logger: ConfigDirectorLogger | None = None,
        log_level: int | str | None = None,
        telemetry: TelemetryOptions | None = None,
        hooks: ClientHooks | None = None,
    ) -> None:
        self._logger = logger if logger is not None else get_default_logger(log_level)
        if _is_blank(server_sdk_key):
            raise ConfigDirectorValidationError(
                "No server SDK key was provided, the client cannot be instantiated without a "
                "valid server SDK key"
            )

        self._server_sdk_key = server_sdk_key
        self._sdk_name = _SDK_NAME
        self._sdk_version = __version__
        self._metadata = metadata if metadata is not None else Metadata()
        self._connection = connection if connection is not None else ConnectionOptions()
        self._telemetry_options = _validated_telemetry(
            telemetry if telemetry is not None else TelemetryOptions()
        )
        self._base_url = _validated_url(self._connection.url) or _DEFAULT_BASE_URL

        # One pool for every request/response call this client makes — polling and telemetry
        # both. Owned here so that close() releases the connections it opened, rather than
        # leaving them in a pool shared by every client in the process.
        self._http = HttpClient()
        self._lock = threading.RLock()
        self._ready = False
        self._closed = False
        self._configs: dict[str, Config] | None = None
        self._watchers: dict[str, list[_Watcher]] = {}
        self._event_handlers: dict[str, list[Callable[[Any], None]]] = {name: [] for name in _EVENT_NAMES}
        self._ready_event = threading.Event()
        self._evaluator = ConfigEvaluator(self._logger)
        self._transport = create_transport(
            self._connection.mode,
            TransportOptions(
                server_sdk_key=server_sdk_key,
                base_url=self._base_url,
                meta_context=_meta_context(self._metadata, self._sdk_name, self._sdk_version),
                logger=self._logger,
                on_bundle=self._on_bundle,
                http=self._http,
                polling_interval=self._connection.polling_interval,
            ),
        )

        if hooks is not None:
            for event, handler in (
                ("client_ready", hooks.client_ready),
                ("configs_updated", hooks.configs_updated),
                ("config_evaluated", hooks.config_evaluated),
            ):
                if handler is not None:
                    self.on(event, handler)  # type: ignore[call-overload]

        # Built last, and deliberately so: it starts a background flush thread, which would
        # outlive the client if anything above this line raised.
        self._telemetry = TelemetryCollector(
            TelemetryCollectorOptions(
                server_sdk_key=server_sdk_key,
                base_url=self._base_url,
                logger=self._logger,
                http=self._http,
                event_queue_limit=self._telemetry_options.event_queue_limit,
                flush_interval=self._telemetry_options.flush_interval,
            )
        )

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
        effective_timeout = timeout if timeout is not None else self._connection.timeout
        if effective_timeout <= 0:
            raise ConfigDirectorValidationError(
                f"Invalid timeout '{effective_timeout}'. The timeout must be a positive number of seconds."
            )

        self._raise_if_closed()
        self._logger.debug(
            "Initializing in %r mode against %s with a %ss timeout",
            self._connection.mode,
            self._base_url,
            effective_timeout,
        )

        started = time.monotonic()
        try:
            self._transport.connect(effective_timeout)
        except Exception as error:
            self._logger.error("An error occurred during initialization: %r", error)
            return

        remaining = effective_timeout - (time.monotonic() - started)
        if remaining > 0:
            self._ready_event.wait(remaining)

        if not self.is_ready:
            details = (
                "The client will continue to retry since there were no fatal errors detected. "
                "Configs will return the default value until the connection succeeds."
                if self._connection.mode == "streaming"
                else "Since the client was configured without streaming, configs may not update "
                "and will always return the default value."
            )
            self._logger.warning(
                "Timed out waiting for initialization after %ss. %s", effective_timeout, details
            )

    @property
    def is_ready(self) -> bool:
        """Whether the client is ready following a call to :meth:`initialize`.

        Ready means the connection to the server succeeded and config definitions were received.
        """
        with self._lock:
            return self._ready

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        with self._lock:
            return self._closed

    def close(self) -> None:
        """Close the client.

        Closes all connections, flushes pending telemetry, and cancels every event and config
        key subscription. Intended to be called when your application shuts down. Safe to call
        more than once.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._ready = False
            self._watchers.clear()
            for handlers in self._event_handlers.values():
                handlers.clear()

        self._ready_event.set()  # release anyone still blocked in initialize()
        self._transport.close()
        self._telemetry.close()  # reports whatever was evaluated since the last flush
        # Last: the final telemetry report above is the client's last request, and it needs the
        # pool still open to send it.
        self._http.close()
        self._logger.debug("close() has been called, the client is now closed")

    # -- config state -----------------------------------------------------------------------

    def _on_bundle(self, bundle: ConfigBundle) -> None:
        with self._lock:
            if self._closed:
                return
            if self._configs is None or bundle.kind == "full":
                self._configs = dict(bundle.configs)
            else:
                self._configs.update(bundle.configs)

            first_bundle = not self._ready
            self._ready = True
            # Snapshotted under the lock so that user callbacks, which run outside it, cannot
            # observe the watcher list being edited from under them.
            watchers = {
                key: list(entries)
                for key, entries in self._watchers.items()
                if entries and key in bundle.configs
            }

        keys = sorted(bundle.configs)
        self._logger.debug("Config state updated from the server with %d key(s): %r", len(keys), keys)
        self._emit("configs_updated", ConfigsUpdatedEvent(keys=keys))
        self._notify_watchers(watchers, bundle.configs)

        if first_bundle:
            self._ready_event.set()
            self._emit("client_ready", ClientReadyEvent())
            self._logger.debug("Received the initial payload from the server, the client is ready")

    def _notify_watchers(self, watchers: dict[str, list[_Watcher]], configs: dict[str, Config]) -> None:
        # Evaluated against the bundle rather than the merged state: a watcher only fires for a
        # key the update carried, and for those two are the same definition.
        for config_key, entries in watchers.items():
            definition = configs[config_key]
            for watcher in entries:
                try:
                    value = self._evaluate(config_key, definition, watcher.default, watcher.context)
                    watcher.handler(value)
                except Exception as error:
                    # One faulty watcher must not cost the others their update, and it must not
                    # take down the transport thread this runs on.
                    self._logger.error("A watcher for %r raised an exception: %r", config_key, error)

    def __enter__(self) -> ConfigDirectorClient:
        if not self.is_ready:
            self.initialize()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

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
                client cannot reach the server, or if ``get_value`` is called before
                initialization completes. Its type also determines the type the config is
                parsed as.
            context: The user's context, used for targeting rule evaluation.

        Returns:
            The evaluated config value, or ``default`` if config state was unavailable.

        Raises:
            ConfigDirectorValidationError: If ``config_key`` is empty.
            ConfigDirectorTypeError: If ``default`` is ``None`` or an unsupported type.
        """
        _validate_config_key(config_key)
        _validate_default(default)

        with self._lock:
            definition = self._configs.get(config_key) if self._configs is not None else None

        return self._evaluate(config_key, definition, default, context)

    def _evaluate(
        self,
        config_key: str,
        definition: Config | None,
        default: ConfigValueT,
        context: Context | None,
    ) -> ConfigValueT:
        if definition is None:
            reason: EvaluationReason = "config-state-missing" if self.is_ready else "client-not-ready"
            self._logger.debug(
                "No config state found for %r, returning default value %r", config_key, default
            )
            value_id: str | None = value_id_for(default)
            self._telemetry.record_evaluation(
                key=config_key,
                default=default,
                value=default,
                used_default=True,
                reason=reason,
                context=context,
                value_id=value_id,
            )
            self._emit_evaluation(config_key, default, True, reason, value_id, context)
            return default

        state = self._evaluator.evaluate(
            definition, EvaluationContext(context=context, metadata=self._metadata)
        )
        result = parse_config_value(state, default)
        value_id = result.value_id or value_id_for(result.value, state.type)
        self._logger.debug("Evaluated %r to %r", config_key, result.value)
        self._telemetry.record_evaluation(
            key=config_key,
            default=default,
            value=result.value,
            used_default=result.used_default,
            reason=result.reason,
            context=context,
            config_type=state.type,
            value_id=value_id,
        )
        self._emit_evaluation(config_key, result.value, result.used_default, result.reason, value_id, context)
        return cast(ConfigValueT, result.value)

    def _emit_evaluation(
        self,
        config_key: str,
        value: ConfigValue,
        is_default: bool,
        reason: EvaluationReason,
        value_id: str | None,
        context: Context | None,
    ) -> None:
        self._emit(
            "config_evaluated",
            ConfigEvaluatedEvent(
                evaluation=ConfigEvaluation(
                    key=config_key,
                    value=value,
                    is_default=is_default,
                    reason=reason,
                    value_id=value_id,
                    context=context,
                )
            ),
        )

    def get_all_configs(
        self,
        context: Context | None = None,
        config_keys: Sequence[str] | None = None,
    ) -> dict[str, ConfigState]:
        """Return the evaluated :class:`~configdirector.types.ConfigState` for every known key.

        Intended for server-side rendering hydration. This does **not** record telemetry events,
        and returns an empty mapping when the client is not yet ready.

        Args:
            context: The user's context, used for targeting rule evaluation.
            config_keys: Restrict the result to these keys. When omitted, every known key is
                returned.
        """
        with self._lock:
            if not self._ready or self._configs is None:
                return {}
            if config_keys is None:
                definitions = dict(self._configs)
            else:
                requested = set(config_keys)
                definitions = {key: config for key, config in self._configs.items() if key in requested}

        evaluation_context = EvaluationContext(context=context, metadata=self._metadata)
        return {
            key: self._evaluator.evaluate(config, evaluation_context) for key, config in definitions.items()
        }

    # -- watching ---------------------------------------------------------------------

    def watch(
        self,
        config_key: str,
        default: ConfigValueT,
        callback: WatchHandler[ConfigValueT],
        context: Context | None = None,
    ) -> Subscription:
        """Watch a config for updates to its evaluated value.

        Whenever ConfigDirector sends an update to this config, it is re-evaluated against
        ``context`` and ``callback`` is invoked with the resulting value. Updates originate from
        changes made in the ConfigDirector dashboard.

        The callback runs on the SDK's background connection thread, not the thread that
        registered it, so it should be quick and must be safe to call from another thread. An
        exception raised by a callback is logged and does not affect other watchers.

        Args:
            config_key: The config key to watch.
            default: The value referenced when config state is unavailable.
            callback: Invoked with the newly evaluated value on every update to the config.
            context: The user's context, used for targeting rule evaluation.

        Returns:
            A :class:`~configdirector.types.Subscription`. Call ``close()`` on it to stop
            watching, or use it as a context manager to scope the watch to a block.

        Raises:
            ConfigDirectorValidationError: If ``config_key`` is empty.
            ConfigDirectorTypeError: If ``default`` is ``None`` or an unsupported type, or if
                ``callback`` is not callable.
        """
        _validate_config_key(config_key)
        _validate_default(default)
        if not callable(callback):
            raise ConfigDirectorTypeError(
                "Invalid callback. The watch callback must be a callable accepting the new value."
            )

        watcher = _Watcher(handler=callback, default=default, context=context)
        with self._lock:
            self._watchers.setdefault(config_key, []).append(watcher)

        return Subscription(lambda: self._remove_watcher(config_key, watcher))

    def unwatch(self, config_key: str, callback: WatchHandler[Any] | None = None) -> None:
        """Stop watching ``config_key``.

        Prefer closing the :class:`~configdirector.types.Subscription` returned by
        :meth:`watch`; this is here for code that does not hold on to it.

        Args:
            config_key: The config key to remove watchers from.
            callback: The callback to remove. When omitted, every watcher for ``config_key`` is
                removed.
        """
        with self._lock:
            watchers = self._watchers.get(config_key)
            if not watchers:
                return

            if callback is None:
                watchers.clear()
                return

            for index, watcher in enumerate(watchers):
                if watcher.handler == callback:
                    del watchers[index]
                    return

    def unwatch_all(self) -> None:
        """Stop watching every config key."""
        with self._lock:
            self._watchers.clear()

    def _remove_watcher(self, config_key: str, watcher: _Watcher) -> None:
        with self._lock:
            watchers = self._watchers.get(config_key)
            if watchers is not None and watcher in watchers:
                watchers.remove(watcher)

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
            A :class:`~configdirector.types.Subscription`. Call ``close()`` on it to unregister
            the handler, or use it as a context manager.

        Raises:
            ConfigDirectorValidationError: If ``event`` is not a known event name.
            ConfigDirectorTypeError: If ``handler`` is not callable.
        """
        _validate_event_name(event)
        if not callable(handler):
            raise ConfigDirectorTypeError(
                f"Invalid handler for event '{event}'. Event handlers must be callable."
            )
        with self._lock:
            self._event_handlers[event].append(handler)

        return Subscription(lambda: self._remove_handler(event, handler))

    def _remove_handler(self, event: ClientEvent, handler: Callable[[Any], None]) -> None:
        with self._lock:
            handlers = self._event_handlers[event]
            if handler in handlers:
                handlers.remove(handler)

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
        _validate_event_name(event)
        with self._lock:
            handlers = self._event_handlers[event]
            if handler is None:
                handlers.clear()
            elif handler in handlers:
                handlers.remove(handler)

    def _emit(self, event: ClientEvent, payload: Any) -> None:
        with self._lock:
            handlers = list(self._event_handlers[event])

        for handler in handlers:
            try:
                handler(payload)
            except Exception as error:  # a faulty handler must not break the caller
                self._logger.error("A handler for event %r raised an exception: %r", event, error)

    def _raise_if_closed(self) -> None:
        if self.closed:
            raise ConfigDirectorValidationError(
                "This client has been closed and can no longer be used. Create a new one instead."
            )


def create_client(
    server_sdk_key: str,
    *,
    metadata: Metadata | None = None,
    connection: ConnectionOptions | None = None,
    logger: ConfigDirectorLogger | None = None,
    log_level: int | str | None = None,
    telemetry: TelemetryOptions | None = None,
    hooks: ClientHooks | None = None,
) -> ConfigDirectorClient:
    """Create an uninitialized :class:`ConfigDirectorClient`.

    Equivalent to constructing :class:`ConfigDirectorClient` directly; provided for consistency
    with the other ConfigDirector SDKs. See :class:`ConfigDirectorClient` for the arguments.
    """
    return ConfigDirectorClient(
        server_sdk_key,
        metadata=metadata,
        connection=connection,
        logger=logger,
        log_level=log_level,
        telemetry=telemetry,
        hooks=hooks,
    )


def _meta_context(metadata: Metadata, sdk_name: str, sdk_version: str) -> dict[str, str]:
    # The wire format is camelCase, and the server treats every field but the SDK identity as
    # optional, so absent metadata is left out rather than sent as null.
    context = {"sdkName": sdk_name, "sdkVersion": sdk_version}
    if metadata.app_name is not None:
        context["appName"] = metadata.app_name
    if metadata.app_version is not None:
        context["appVersion"] = metadata.app_version
    return context


def _is_blank(value: object) -> bool:
    """Whether ``value`` is anything other than a string with non-whitespace content.

    Takes ``object`` rather than ``str`` on purpose: callers without a type checker can pass
    anything at all, and the SDK should reject it with a clear error instead of an AttributeError.
    """
    return not isinstance(value, str) or not value.strip()


def _validate_config_key(config_key: str) -> None:
    if _is_blank(config_key):
        raise ConfigDirectorValidationError("Invalid config key. The config key must be a non-empty string.")


def _validate_default(default: ConfigValue) -> None:
    if default is None:
        raise ConfigDirectorTypeError(
            "Invalid default value. The default value for a config must not be None."
        )

    if not isinstance(default, _VALID_VALUE_TYPES):
        raise ConfigDirectorTypeError(
            f"Invalid default value of type '{type(default).__name__}'. The default value for a "
            f"config must be a str, int, float, bool, dict, or list."
        )


def _validate_event_name(event: str) -> None:
    if event not in _EVENT_NAMES:
        raise ConfigDirectorValidationError(
            f"Unknown event '{event}'. Expected one of: {', '.join(sorted(_EVENT_NAMES))}."
        )


def _validated_telemetry(options: TelemetryOptions) -> TelemetryOptions:
    if not MIN_EVENT_QUEUE_LIMIT <= options.event_queue_limit <= MAX_EVENT_QUEUE_LIMIT:
        raise ConfigDirectorValidationError(
            f"Invalid telemetry event queue limit '{options.event_queue_limit}'. It must be "
            f"between {MIN_EVENT_QUEUE_LIMIT} and {MAX_EVENT_QUEUE_LIMIT}."
        )

    if options.flush_interval <= 0:
        raise ConfigDirectorValidationError(
            f"Invalid telemetry flush interval '{options.flush_interval}'. It must be a positive "
            f"number of seconds."
        )
    return options


def _validated_url(url: str | None) -> str | None:
    if url is None:
        return None

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigDirectorValidationError(
            f"Invalid base URL '{url}'. The URL must include a scheme and a host."
        )
    return url
