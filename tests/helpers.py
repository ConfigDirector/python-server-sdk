from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from configdirector._bundle import BundleKind, ConfigBundle
from configdirector._evaluation import (
    Condition,
    ConditionalRule,
    Config,
    Percentage,
    PercentageRule,
    Rule,
    TargetingRules,
)
from configdirector._telemetry import TelemetryCollectorOptions
from configdirector._transport import TransportOptions
from configdirector.types import (
    ConfigDirectorLogger,
    ConfigType,
    ConfigValue,
    Context,
    EvaluationReason,
)

WAIT_TIMEOUT = 5.0


def wait_for(predicate: Callable[[], bool], *, timeout: float = WAIT_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


class StubbedLogger:
    def debug(self, message: str, /, *args: Any) -> None: ...

    def info(self, message: str, /, *args: Any) -> None: ...

    def warning(self, message: str, /, *args: Any) -> None: ...

    def error(self, message: str, /, *args: Any) -> None: ...


def create_stubbed_logger() -> ConfigDirectorLogger:
    return StubbedLogger()


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def debug(self, message: str, /, *args: Any) -> None:
        self._record("debug", message, args)

    def info(self, message: str, /, *args: Any) -> None:
        self._record("info", message, args)

    def warning(self, message: str, /, *args: Any) -> None:
        self._record("warning", message, args)

    def error(self, message: str, /, *args: Any) -> None:
        self._record("error", message, args)

    def _record(self, level: str, message: str, args: tuple[Any, ...]) -> None:
        self.records.append((level, message % args if args else message))

    def messages(self, level: str) -> list[str]:
        return [message for recorded, message in self.records if recorded == level]


class FakeTransport:
    """Stands in for a real transport, delivering bundles on demand instead of over a socket."""

    def __init__(self, mode: str, options: TransportOptions, recorder: TransportRecorder) -> None:
        self.mode = mode
        self.options = options
        self.connect_timeouts: list[float] = []
        self.closed = False
        self._recorder = recorder

    def connect(self, timeout: float) -> None:
        self.connect_timeouts.append(timeout)
        # Read at connect time, not construction time, so a test can set up the response after
        # the client that will receive it has already been built.
        if self._recorder.connect_error is not None:
            raise self._recorder.connect_error
        if self._recorder.initial_bundle is not None:
            self.deliver(self._recorder.initial_bundle)

    def deliver(self, sent: ConfigBundle) -> None:
        self.options.on_bundle(sent)

    @property
    def is_connected(self) -> bool:
        return bool(self.connect_timeouts) and not self.closed

    def close(self) -> None:
        self.closed = True


class TransportRecorder:
    def __init__(self) -> None:
        self.created: list[FakeTransport] = []
        self.initial_bundle: ConfigBundle | None = bundle()
        self.connect_error: BaseException | None = None

    def __call__(self, mode: str, options: TransportOptions) -> FakeTransport:
        transport = FakeTransport(mode, options, self)
        self.created.append(transport)
        return transport

    @property
    def last(self) -> FakeTransport:
        return self.created[-1]


@dataclass(frozen=True)
class RecordedEvaluation:
    key: str
    default: ConfigValue
    value: ConfigValue
    used_default: bool
    reason: EvaluationReason
    context: Context | None
    config_type: ConfigType | None
    value_id: str | None


class FakeTelemetryCollector:
    """Stands in for the real collector, recording evaluations instead of reporting them."""

    def __init__(self, options: TelemetryCollectorOptions) -> None:
        self.options = options
        self.evaluations: list[RecordedEvaluation] = []
        self.closed = False

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
        self.evaluations.append(
            RecordedEvaluation(
                key=key,
                default=default,
                value=value,
                used_default=used_default,
                reason=reason,
                context=context,
                config_type=config_type,
                value_id=value_id,
            )
        )

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class TelemetryRecorder:
    def __init__(self) -> None:
        self.created: list[FakeTelemetryCollector] = []

    def __call__(self, options: TelemetryCollectorOptions) -> FakeTelemetryCollector:
        collector = FakeTelemetryCollector(options)
        self.created.append(collector)
        return collector

    @property
    def last(self) -> FakeTelemetryCollector:
        return self.created[-1]

    @property
    def evaluations(self) -> list[RecordedEvaluation]:
        return self.last.evaluations


def bundle(*configs: Config, kind: BundleKind = "full", timestamp: str | None = None) -> ConfigBundle:
    return ConfigBundle(
        configs={config.key: config for config in configs},
        kind=kind,
        environment_id="10000000-0000-0000-0000-000000000000",
        project_id="20000000-0000-0000-0000-000000000000",
        timestamp=timestamp,
    )


def config(
    key: str,
    default_value: str,
    *,
    type: ConfigType = "string",
    rules: Sequence[Rule] = (),
    id: str | None = None,
    default_value_id: str | None = None,
) -> Config:
    return Config(
        id=id or f"cfg_{key}",
        key=key,
        type=type,
        target=TargetingRules(
            default_value=default_value, rules=list(rules), default_value_id=default_value_id
        ),
    )


def conditional_rule(
    value: str | int | float | bool,
    *conditions: Condition,
    order: int = 0,
    id: str = "rule-1",
    value_id: str | None = None,
) -> ConditionalRule:
    return ConditionalRule(id=id, order=order, value=value, conditions=list(conditions), value_id=value_id)


def percentage_rule(*percentages: Percentage, order: int = 0, id: str = "rule-1") -> PercentageRule:
    return PercentageRule(id=id, order=order, percentages=list(percentages))


def condition(
    attribute: str,
    operator: str,
    *target_values: str,
    target_type: str = "text",
    trait: str | None = None,
    id: str = "condition-1",
) -> Condition:
    return Condition(
        id=id,
        attribute=attribute,
        operator=operator,
        target_type=target_type,
        target_values=list(target_values),
        trait=trait,
    )
