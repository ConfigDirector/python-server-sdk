from __future__ import annotations

import json
import math
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from ._bundle import BundleKind, ConfigBundle
from ._evaluation import Config, TargetingRules, Variation
from ._logger import get_default_logger
from ._telemetry import TelemetryCollectorOptions
from ._transport import TransportOptions
from ._transport.base import fatal_status_error
from .client import _ConfigDirectorClient, _validate_config_key
from .errors import ConfigDirectorTypeError, ConfigDirectorValidationError
from .types import (
    ConfigDirectorClient,
    ConfigDirectorLogger,
    ConfigType,
    ConfigValue,
    ConnectionOptions,
    Context,
    EvaluationReason,
)

__all__ = ["InMemoryConnection"]

_TEST_CLIENT_SDK_KEY = "test-client"
_ENVIRONMENT_ID = "test-environment"
_PROJECT_ID = "test-project"
_FAILED_STATUS = 401

_Armed = Literal["hold", "failure"]
_Outcome = Literal["completed", "failed", "ended"]


@dataclass(eq=False)
class _HeldAttempt:
    settled: threading.Event = field(default_factory=threading.Event)
    outcome: _Outcome = "ended"

    def settle(self, outcome: _Outcome) -> None:
        if not self.settled.is_set():
            self.outcome = outcome
            self.settled.set()


class _DiscardingTelemetry:
    def record_evaluation(
        self,
        *,
        key: str,
        default: ConfigValue,
        value: ConfigValue,
        used_default: bool,
        reason: EvaluationReason,
        context: Context | None = None,
        config_type: ConfigType | None = None,
        value_id: str | None = None,
    ) -> None:
        return None

    def close(self) -> None:
        return None


class InMemoryConnection:
    def __init__(
        self,
        values: Mapping[str, ConfigValue] | None,
        timeout: float | None,
        logger: ConfigDirectorLogger | None,
    ) -> None:
        self._logger = logger if logger is not None else get_default_logger()
        self._state_lock = threading.Lock()
        self._configs = _encode_all(values)
        self._armed: _Armed | None = None
        self._held: _HeldAttempt | None = None
        self._connected = False
        self._on_bundle: Callable[[ConfigBundle], None] | None = None
        self._delivery_lock = threading.Lock()
        self._pending: deque[ConfigBundle] = deque()
        self._delivering = False
        connection = ConnectionOptions() if timeout is None else ConnectionOptions(timeout=timeout)
        self.client: ConfigDirectorClient = _ConfigDirectorClient(
            _TEST_CLIENT_SDK_KEY,
            connection=connection,
            logger=self._logger,
            transport_factory=self._create_transport,
            telemetry_factory=_discarding_telemetry,
        )

    @property
    def is_holding_an_attempt(self) -> bool:
        with self._state_lock:
            return self._held is not None

    def set_value(self, key: str, value: ConfigValue) -> None:
        definition = _encode(key, value)
        with self._state_lock:
            self._configs[key] = definition
            update = self._delta_update(key, definition) if self._connected else None
        self._deliver_if_any(update)

    def remove_value(self, key: str) -> None:
        _validate_config_key(key)
        with self._state_lock:
            self._configs.pop(key, None)
            update = self._full_update() if self._connected else None
        self._deliver_if_any(update)

    def replace_values(self, values: Mapping[str, ConfigValue]) -> None:
        encoded = _encode_all(values)
        with self._state_lock:
            self._configs = encoded
            self._armed = None
            update = self._full_update() if self._connected else None
        self._deliver_if_any(update)

    def hold_initialization(self) -> None:
        with self._state_lock:
            self._armed = "hold"

    def complete_initialization(self) -> None:
        update: ConfigBundle | None = None
        with self._state_lock:
            attempt, self._held = self._held, None
            if attempt is not None:
                self._connected = True
                update = self._full_update()
            elif self._armed == "hold":
                self._armed = None
        if attempt is not None and update is not None:
            self._deliver(update)
            attempt.settle("completed")

    def fail_initialization(self) -> None:
        with self._state_lock:
            attempt, self._held = self._held, None
            if attempt is None:
                self._armed = "failure"
        if attempt is not None:
            attempt.settle("failed")

    def _create_transport(self, options: TransportOptions) -> _Attempts:
        self._on_bundle = options.on_bundle
        return _Attempts(self)

    def _connect(self, timeout: float) -> None:
        attempt: _HeldAttempt | None = None
        with self._state_lock:
            self._connected = False
            previous, self._held = self._held, None
            picked_up, self._armed = self._armed, None
            if picked_up == "hold":
                attempt = _HeldAttempt()
                self._held = attempt
        if previous is not None:
            previous.settle("ended")
        if picked_up == "failure":
            raise self._fatal_error()
        if attempt is not None:
            self._await_held(attempt, timeout)
            return
        with self._state_lock:
            self._connected = True
            update = self._full_update()
        self._deliver(update)

    def _await_held(self, attempt: _HeldAttempt, timeout: float) -> None:
        if not attempt.settled.wait(timeout):
            self._end(attempt)
        if attempt.outcome == "failed":
            raise self._fatal_error()

    def _end(self, attempt: _HeldAttempt) -> None:
        with self._state_lock:
            if self._held is not attempt:
                return
            self._held = None
        attempt.settle("ended")

    def _close_transport(self) -> None:
        with self._state_lock:
            self._connected = False
            attempt, self._held = self._held, None
        if attempt is not None:
            attempt.settle("ended")

    def _fatal_error(self) -> Exception:
        error = fatal_status_error(_FAILED_STATUS, "the test client failed this initialization")
        self._logger.error("[InMemoryConnection] %s", error)
        return error

    def _full_update(self) -> ConfigBundle:
        return _bundle(dict(self._configs), "full")

    @staticmethod
    def _delta_update(key: str, definition: Config) -> ConfigBundle:
        return _bundle({key: definition}, "delta")

    def _deliver_if_any(self, update: ConfigBundle | None) -> None:
        if update is not None:
            self._deliver(update)

    def _deliver(self, update: ConfigBundle) -> None:
        with self._delivery_lock:
            self._pending.append(update)
            if self._delivering:
                return
            self._delivering = True
        while True:
            with self._delivery_lock:
                if not self._pending:
                    self._delivering = False
                    return
                next_update = self._pending.popleft()
            if self._on_bundle is not None:
                self._on_bundle(next_update)


class _Attempts:
    def __init__(self, connection: InMemoryConnection) -> None:
        self._connection = connection
        self._connected = False

    def connect(self, timeout: float) -> None:
        self._connection._connect(timeout)
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self._connected = False
        self._connection._close_transport()


def _discarding_telemetry(options: TelemetryCollectorOptions) -> _DiscardingTelemetry:
    return _DiscardingTelemetry()


def _bundle(configs: dict[str, Config], kind: BundleKind) -> ConfigBundle:
    return ConfigBundle(configs=configs, kind=kind, environment_id=_ENVIRONMENT_ID, project_id=_PROJECT_ID)


def _encode_all(values: Mapping[str, ConfigValue] | None) -> dict[str, Config]:
    if values is None:
        return {}
    return {key: _encode(key, value) for key, value in values.items()}


def _encode(key: str, value: ConfigValue) -> Config:
    _validate_config_key(key)
    if value is None:
        raise ConfigDirectorTypeError(
            f"Invalid test value for {key!r}: None is not a value. Use remove_value to remove a value."
        )
    if isinstance(value, bool):
        return _definition(key, "boolean", "true" if value else "false")
    if isinstance(value, int):
        return _definition(key, "integer", _integer_text(key, value))
    if isinstance(value, float):
        return _definition(key, "float", _plain_decimal(key, value))
    if isinstance(value, str):
        return _definition(key, "string", value)
    if isinstance(value, (dict, list)):
        return _definition(key, "json", _json_text(key, value))
    raise ConfigDirectorTypeError(
        f"Invalid test value for {key!r} of type {type(value).__name__!r}. A test value must be a bool, "
        f"an int, a float, a str, a dict with str keys, or a list."
    )


def _definition(key: str, config_type: ConfigType, text: str) -> Config:
    return Config(
        id=f"test-config:{key}",
        key=key,
        type=config_type,
        target=TargetingRules(default_value=text, default_value_id=f"test-value:{key}"),
        variations=[Variation(value=text)],
    )


def _integer_text(key: str, value: int) -> str:
    try:
        return str(value)
    except ValueError as error:
        raise ConfigDirectorValidationError(
            f"Invalid test value for {key!r}: the integer has too many digits to be written out ({error})."
        ) from error


def _plain_decimal(key: str, value: float) -> str:
    if not math.isfinite(value):
        raise ConfigDirectorValidationError(
            f"Invalid test value for {key!r}: {value!r} is not a finite number."
        )
    return format(Decimal(repr(value)).normalize(), "f")


def _json_text(key: str, value: dict[str, Any] | list[Any]) -> str:
    _validate_json_contents(key, value, "")
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError as error:
        raise ConfigDirectorValidationError(f"Invalid test value for {key!r}: {error}.") from error


def _validate_json_contents(key: str, value: object, path: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigDirectorValidationError(
                f"Invalid test value for {key!r}{_at(path)}: {value!r} is not a finite number."
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_contents(key, item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for member_key, member in value.items():
            if not isinstance(member_key, str):
                raise ConfigDirectorTypeError(
                    f"Invalid test value for {key!r}{_at(path)}: the key {member_key!r} is not a str."
                )
            _validate_json_contents(key, member, f"{path}.{member_key}" if path else member_key)
        return
    raise ConfigDirectorTypeError(
        f"Invalid test value for {key!r}{_at(path)}: a value of type {type(value).__name__!r} cannot be "
        f"encoded as JSON. JSON contents can hold bools, ints, finite floats, strs, None, lists, and dicts "
        f"with str keys."
    )


def _at(path: str) -> str:
    return f" at {path!r}" if path else ""
