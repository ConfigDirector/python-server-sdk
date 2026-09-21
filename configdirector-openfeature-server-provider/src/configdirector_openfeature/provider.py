from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from typing import TypeVar

from configdirector import (
    ClientHooks,
    ClientReadyEvent,
    ConfigDirectorLogger,
    ConfigEvaluatedEvent,
    ConfigEvaluation,
    ConfigsUpdatedEvent,
    ConfigValue,
    ConnectionOptions,
    Metadata,
    TelemetryOptions,
)
from configdirector._wrappers import Wrapper, create_wrapped_client
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEventDetails
from openfeature.flag_evaluation import FlagResolutionDetails, FlagValueType
from openfeature.provider import AbstractProvider
from openfeature.provider import Metadata as ProviderMetadata

from ._context import to_context
from ._resolution import to_resolution_details
from ._values import to_plain

__all__ = ["ConfigDirectorProvider"]

_NAME = "ConfigDirectorProvider"

_ValueT = TypeVar("_ValueT", bound=ConfigValue)

_evaluated: ContextVar[ConfigEvaluation | None] = ContextVar("configdirector_evaluated", default=None)


class ConfigDirectorProvider(AbstractProvider):
    """An OpenFeature provider backed by the ConfigDirector Python server SDK.

    Register it with the OpenFeature API and read values through an OpenFeature client. The
    provider owns a ConfigDirector client: it connects when OpenFeature initializes the provider,
    and closes when OpenFeature shuts it down. Targeting rules are evaluated locally, so an
    evaluation makes no network calls.

    Example::

        from configdirector_openfeature import ConfigDirectorProvider
        from openfeature import api

        api.set_provider_and_wait(ConfigDirectorProvider("YOUR-SERVER-SDK-KEY"))

        enabled = api.get_client().get_boolean_value("new-checkout", False)

    The OpenFeature evaluation context maps onto the ConfigDirector
    :class:`~configdirector.Context`: the targeting key, or failing that an ``id`` attribute,
    becomes the context's id, ``name`` its name, a ``traits`` mapping its traits, and a boolean
    ``anonymous`` its anonymous flag.

    If the first config state does not arrive within the configured timeout, initialization
    still completes and evaluations return their defaults with the error code
    ``PROVIDER_NOT_READY``. The provider keeps connecting, and emits ``PROVIDER_READY`` once
    config state arrives.

    Args:
        server_sdk_key: Your ConfigDirector server SDK key. This is a secret value — do not
            commit it to source control.
        metadata: Metadata about your application. Supplying ``app_name`` and ``app_version`` is
            recommended so that they can be referenced from targeting rules.
        connection: Connection options such as mode, timeout, and polling interval.
        logger: Any object implementing :class:`~configdirector.ConfigDirectorLogger`, including
            a standard library :class:`logging.Logger`. Defaults to the standard library logger
            named ``"configdirector"``.
        log_level: A level to set on that default logger, as either a :mod:`logging` constant or
            its name. Ignored when ``logger`` is supplied.
        telemetry: Telemetry queue and flush tuning.

    Raises:
        configdirector.ConfigDirectorValidationError: If ``server_sdk_key`` is missing or empty,
            or if a ``connection`` or ``telemetry`` setting is invalid.
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
    ) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._initialized = False
        self._client = create_wrapped_client(
            Wrapper.OPENFEATURE_SERVER_PROVIDER,
            server_sdk_key,
            metadata=metadata,
            connection=connection,
            logger=logger,
            log_level=log_level,
            telemetry=telemetry,
            hooks=ClientHooks(
                client_ready=self._on_client_ready,
                configs_updated=self._on_configs_updated,
                config_evaluated=self._on_config_evaluated,
            ),
        )

    def get_metadata(self) -> ProviderMetadata:
        """The name this provider is registered under with OpenFeature."""
        return ProviderMetadata(name=_NAME)

    def initialize(self, evaluation_context: EvaluationContext) -> None:
        """Connects to ConfigDirector, waiting up to the configured timeout for config state."""
        self._client.initialize()
        with self._lock:
            self._initialized = True

    def shutdown(self) -> None:
        """Closes the connection to ConfigDirector and flushes pending telemetry."""
        self._client.close()

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        """Evaluates ``flag_key`` as a boolean."""
        return self._resolve(flag_key, default_value, evaluation_context)

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        """Evaluates ``flag_key`` as a string."""
        return self._resolve(flag_key, default_value, evaluation_context)

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[int]:
        """Evaluates ``flag_key`` as an integer."""
        return self._resolve(flag_key, default_value, evaluation_context)

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[float]:
        """Evaluates ``flag_key`` as a float."""
        return self._resolve(flag_key, float(default_value), evaluation_context)

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Sequence[FlagValueType] | Mapping[str, FlagValueType],
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[Sequence[FlagValueType] | Mapping[str, FlagValueType]]:
        """Evaluates ``flag_key`` as a JSON object or array."""
        default: dict[str, FlagValueType] | list[FlagValueType] = to_plain(default_value)
        return self._resolve(flag_key, default, evaluation_context)

    def _resolve(
        self, flag_key: str, default_value: _ValueT, evaluation_context: EvaluationContext | None
    ) -> FlagResolutionDetails[_ValueT]:
        _evaluated.set(None)
        value = self._client.get_value(flag_key, default_value, to_context(evaluation_context))
        return to_resolution_details(value, _evaluated.get())

    def _on_config_evaluated(self, event: ConfigEvaluatedEvent) -> None:
        _evaluated.set(event.evaluation)

    def _on_configs_updated(self, event: ConfigsUpdatedEvent) -> None:
        self.emit_provider_configuration_changed(ProviderEventDetails(flags_changed=list(event.keys)))

    def _on_client_ready(self, _event: ClientReadyEvent) -> None:
        with self._lock:
            initialized = self._initialized
        if initialized:
            self.emit_provider_ready(ProviderEventDetails())
