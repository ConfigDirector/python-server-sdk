from __future__ import annotations

import contextlib
import threading
from typing import Any

import pytest

import configdirector.client
from configdirector import (
    ClientHooks,
    ConfigDirectorClient,
    ConfigDirectorConnectionError,
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
    ConfigEvaluatedEvent,
    ConfigsUpdatedEvent,
    ConnectionOptions,
    Context,
    Metadata,
    Subscription,
    TelemetryOptions,
)
from configdirector._telemetry import TelemetryCollector
from configdirector._telemetry.value_id import VALUE_ID_LENGTH, generate_value_id
from tests.helpers import (
    RecordedEvaluation,
    RecordingLogger,
    TelemetryRecorder,
    TransportRecorder,
    bundle,
    condition,
    conditional_rule,
    config,
)

SDK_KEY = "test-server-sdk-key"


@pytest.fixture
def client() -> ConfigDirectorClient:
    return ConfigDirectorClient(SDK_KEY)


@pytest.fixture
def ready_client(client: ConfigDirectorClient) -> ConfigDirectorClient:
    client.initialize()
    return client


class TestInitialize:
    def test_marks_the_client_ready_once_config_state_arrives(self, client: ConfigDirectorClient) -> None:
        assert client.is_ready is False

        client.initialize()

        assert client.is_ready is True

    def test_passes_the_timeout_to_the_transport(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize(timeout=0.5)

        assert transports.last.connect_timeouts == [0.5]

    def test_falls_back_to_the_configured_timeout(self, transports: TransportRecorder) -> None:
        client = ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(timeout=7.5))

        client.initialize()

        assert transports.last.connect_timeouts == [7.5]

    @pytest.mark.parametrize("timeout", [0, -1])
    def test_rejects_a_non_positive_timeout(self, client: ConfigDirectorClient, timeout: float) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="timeout"):
            client.initialize(timeout=timeout)

    def test_rejects_use_after_close(self, client: ConfigDirectorClient) -> None:
        client.close()

        with pytest.raises(ConfigDirectorValidationError, match="closed"):
            client.initialize()

    def test_emits_configs_updated_before_client_ready(self, client: ConfigDirectorClient) -> None:
        events: list[str] = []
        client.on("client_ready", lambda _event: events.append("client_ready"))
        client.on("configs_updated", lambda _event: events.append("configs_updated"))

        client.initialize()

        assert events == ["configs_updated", "client_ready"]

    def test_stays_unready_when_no_config_state_arrives(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = None

        client.initialize(timeout=0.05)

        assert client.is_ready is False

    def test_warns_when_initialization_times_out(self, transports: TransportRecorder) -> None:
        transports.initial_bundle = None
        logger = RecordingLogger()
        client = ConfigDirectorClient(SDK_KEY, logger=logger)

        client.initialize(timeout=0.05)

        assert any("Timed out waiting for initialization" in m for m in logger.messages("warning"))

    def test_an_unrecoverable_connection_error_is_logged_not_raised(
        self, transports: TransportRecorder
    ) -> None:
        transports.connect_error = ConfigDirectorConnectionError("Unauthorized", 401)
        logger = RecordingLogger()
        client = ConfigDirectorClient(SDK_KEY, logger=logger)

        client.initialize()

        assert client.is_ready is False
        assert any("error occurred during initialization" in m for m in logger.messages("error"))

    def test_sends_the_sdk_identity_and_metadata_to_the_transport(
        self, transports: TransportRecorder
    ) -> None:
        ConfigDirectorClient(SDK_KEY, metadata=Metadata(app_name="checkout", app_version="2.1.0"))

        meta_context = transports.last.options.meta_context
        assert meta_context["sdkName"] == "python-server-sdk"
        assert meta_context["appName"] == "checkout"
        assert meta_context["appVersion"] == "2.1.0"

    def test_omits_metadata_that_was_not_supplied(self, transports: TransportRecorder) -> None:
        ConfigDirectorClient(SDK_KEY)

        assert set(transports.last.options.meta_context) == {"sdkName", "sdkVersion"}


class TestGetValue:
    @pytest.mark.parametrize(
        "default",
        [True, False, "fallback", 42, 3.14, {"a": 1}, [1, 2, 3]],
    )
    def test_returns_the_default_when_the_key_is_unknown(
        self, ready_client: ConfigDirectorClient, default: Any
    ) -> None:
        assert ready_client.get_value("any-key", default) == default

    def test_returns_the_default_before_initialization(self, client: ConfigDirectorClient) -> None:
        assert client.get_value("any-key", "fallback") == "fallback"

    def test_returns_the_evaluated_value(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))

        client.initialize()

        assert client.get_value("greeting", "fallback") == "hello"

    @pytest.mark.parametrize(
        ("config_type", "stored", "default", "expected"),
        [
            ("boolean", "true", False, True),
            ("boolean", "false", True, False),
            ("integer", "26", 0, 26),
            ("float", "3.5", 0.0, 3.5),
            ("string", "hello", "", "hello"),
            ("json", '{"a":1}', {}, {"a": 1}),
            ("json", "[1,2]", [], [1, 2]),
        ],
    )
    def test_coerces_the_value_to_the_type_of_the_default(
        self,
        client: ConfigDirectorClient,
        transports: TransportRecorder,
        config_type: Any,
        stored: str,
        default: Any,
        expected: Any,
    ) -> None:
        transports.initial_bundle = bundle(config("value", stored, type=config_type))

        client.initialize()

        assert client.get_value("value", default) == expected

    def test_falls_back_when_the_value_cannot_be_read_as_the_requested_type(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        client.initialize()

        assert client.get_value("greeting", 42) == 42
        assert events[-1].evaluation.reason == "invalid-number"
        assert events[-1].evaluation.is_default is True

    def test_applies_targeting_rules_to_the_context(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(
            config(
                "greeting",
                "hello",
                rules=[conditional_rule("bonjour", condition("name", "equals", "Ada"))],
            )
        )

        client.initialize()

        assert client.get_value("greeting", "fallback", Context(name="Ada")) == "bonjour"
        assert client.get_value("greeting", "fallback", Context(name="Bob")) == "hello"

    def test_evaluates_against_the_client_metadata(self, transports: TransportRecorder) -> None:
        transports.initial_bundle = bundle(
            config(
                "greeting",
                "hello",
                rules=[conditional_rule("beta", condition("appName", "equals", "checkout"))],
            )
        )
        client = ConfigDirectorClient(SDK_KEY, metadata=Metadata(app_name="checkout"))

        client.initialize()

        assert client.get_value("greeting", "fallback") == "beta"

    @pytest.mark.parametrize("config_key", ["", "   "])
    def test_rejects_a_blank_config_key(self, ready_client: ConfigDirectorClient, config_key: str) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="config key"):
            ready_client.get_value(config_key, "fallback")

    def test_rejects_a_none_default(self, ready_client: ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="must not be None"):
            ready_client.get_value("any-key", None)  # type: ignore[type-var]

    @pytest.mark.parametrize("default", [lambda: True, {1, 2}, object()])
    def test_rejects_an_unsupported_default_type(
        self, ready_client: ConfigDirectorClient, default: Any
    ) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="Invalid default value of type"):
            ready_client.get_value("any-key", default)

    def test_type_errors_are_also_builtin_type_errors(self, ready_client: ConfigDirectorClient) -> None:
        with pytest.raises(TypeError, match="Invalid default value of type"):
            ready_client.get_value("any-key", {1, 2})  # type: ignore[type-var]

    def test_emits_a_config_evaluated_event(self, ready_client: ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        ready_client.on("config_evaluated", events.append)
        context = Context(id="user-123")

        ready_client.get_value("any-key", "fallback", context)

        assert len(events) == 1
        evaluation = events[0].evaluation
        assert evaluation.key == "any-key"
        assert evaluation.value == "fallback"
        assert evaluation.is_default is True
        assert evaluation.reason == "config-state-missing"
        assert evaluation.context == context

    def test_reports_a_found_match_for_a_known_config(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        client.initialize()
        client.get_value("greeting", "fallback")

        assert events[-1].evaluation.reason == "found-match"
        assert events[-1].evaluation.is_default is False

    def test_reports_client_not_ready_before_initialization(self, client: ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        client.get_value("any-key", "fallback")

        assert events[0].evaluation.reason == "client-not-ready"


class TestConfigUpdates:
    def test_a_full_bundle_replaces_the_previous_state(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("first", "one"), config("second", "two"))
        client.initialize()

        transports.last.deliver(bundle(config("third", "three")))

        assert client.get_value("first", "gone") == "gone"
        assert client.get_value("third", "gone") == "three"

    def test_a_delta_bundle_merges_into_the_previous_state(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("first", "one"))
        client.initialize()

        transports.last.deliver(bundle(config("second", "two"), kind="delta"))

        assert client.get_value("first", "gone") == "one"
        assert client.get_value("second", "gone") == "two"

    def test_the_first_delta_bundle_is_taken_as_the_full_state(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("only", "value"), kind="delta")

        client.initialize()

        assert client.is_ready is True
        assert client.get_value("only", "gone") == "value"

    def test_client_ready_is_emitted_only_once(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        calls: list[str] = []
        client.on("client_ready", lambda _event: calls.append("ready"))

        client.initialize()
        transports.last.deliver(bundle(config("later", "value")))

        assert calls == ["ready"]

    def test_configs_updated_reports_the_keys_in_the_update(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        events: list[ConfigsUpdatedEvent] = []
        client.on("configs_updated", events.append)
        transports.initial_bundle = bundle(config("b", "1"), config("a", "2"))

        client.initialize()

        assert events[0].keys == ["a", "b"]

    def test_an_update_after_close_is_ignored(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize()
        transport = transports.last
        client.close()

        transport.deliver(bundle(config("late", "value")))

        assert client.is_ready is False


class TestGetAllConfigs:
    def test_returns_nothing_before_initialization(self, client: ConfigDirectorClient) -> None:
        assert client.get_all_configs() == {}

    def test_returns_every_known_config(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(
            config("greeting", "hello"), config("enabled", "true", type="boolean")
        )
        client.initialize()

        configs = client.get_all_configs()

        assert set(configs) == {"greeting", "enabled"}
        assert configs["greeting"].value == "hello"
        assert configs["enabled"].type == "boolean"

    def test_filters_by_config_keys(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"), config("enabled", "true"))
        client.initialize()

        configs = client.get_all_configs(config_keys=["greeting", "unknown"])

        assert set(configs) == {"greeting"}

    def test_evaluates_against_the_given_context(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(
            config(
                "greeting",
                "hello",
                rules=[conditional_rule("bonjour", condition("name", "equals", "Ada"))],
            )
        )
        client.initialize()

        configs = client.get_all_configs(context=Context(name="Ada"))

        assert configs["greeting"].value == "bonjour"

    def test_does_not_emit_evaluation_events(self, ready_client: ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        ready_client.on("config_evaluated", events.append)

        ready_client.get_all_configs(context=Context(id="user-123"))

        assert events == []


class TestWatch:
    def test_returns_a_subscription(self, ready_client: ConfigDirectorClient) -> None:
        subscription = ready_client.watch("any-key", False, lambda _value: None)

        assert isinstance(subscription, Subscription)
        assert subscription.closed is False
        assert len(_watchers(ready_client, "any-key")) == 1

    def test_fires_when_the_watched_config_is_updated(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize()
        values: list[str] = []
        client.watch("greeting", "fallback", values.append)

        transports.last.deliver(bundle(config("greeting", "hello")))

        assert values == ["hello"]

    def test_re_evaluates_against_the_watch_context(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize()
        values: list[str] = []
        client.watch("greeting", "fallback", values.append, Context(name="Ada"))

        transports.last.deliver(
            bundle(
                config(
                    "greeting",
                    "hello",
                    rules=[conditional_rule("bonjour", condition("name", "equals", "Ada"))],
                )
            )
        )

        assert values == ["bonjour"]

    def test_does_not_fire_for_a_config_outside_the_update(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize()
        values: list[str] = []
        client.watch("greeting", "fallback", values.append)

        transports.last.deliver(bundle(config("unrelated", "value"), kind="delta"))

        assert values == []

    def test_a_closed_subscription_stops_receiving_updates(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        client.initialize()
        values: list[str] = []
        subscription = client.watch("greeting", "fallback", values.append)

        subscription.close()
        transports.last.deliver(bundle(config("greeting", "hello")))

        assert values == []

    def test_a_raising_watcher_does_not_stop_the_others(self, transports: TransportRecorder) -> None:
        logger = RecordingLogger()
        client = ConfigDirectorClient(SDK_KEY, logger=logger)
        client.initialize()
        values: list[str] = []

        def explode(_value: str) -> None:
            raise RuntimeError("boom")

        client.watch("greeting", "fallback", explode)
        client.watch("greeting", "fallback", values.append)

        transports.last.deliver(bundle(config("greeting", "hello")))

        assert values == ["hello"]
        assert any("raised an exception" in message for message in logger.messages("error"))

    def test_closing_the_subscription_stops_the_watch(self, ready_client: ConfigDirectorClient) -> None:
        subscription = ready_client.watch("any-key", False, lambda _value: None)

        subscription.close()

        assert subscription.closed is True
        assert _watchers(ready_client, "any-key") == []

    def test_closing_is_idempotent(self, ready_client: ConfigDirectorClient) -> None:
        subscription = ready_client.watch("any-key", False, lambda _value: None)

        subscription.close()
        subscription.close()

        assert _watchers(ready_client, "any-key") == []

    def test_the_subscription_is_a_context_manager(self, ready_client: ConfigDirectorClient) -> None:
        with ready_client.watch("any-key", False, lambda _value: None):
            assert len(_watchers(ready_client, "any-key")) == 1

        assert _watchers(ready_client, "any-key") == []

    def test_closing_one_subscription_leaves_an_identical_one(
        self, ready_client: ConfigDirectorClient
    ) -> None:
        def callback(_value: bool) -> None: ...

        first = ready_client.watch("any-key", False, callback)
        ready_client.watch("any-key", False, callback)

        first.close()

        assert len(_watchers(ready_client, "any-key")) == 1

    def test_subscriptions_compose_with_exit_stack(self, ready_client: ConfigDirectorClient) -> None:
        with contextlib.ExitStack() as stack:
            stack.enter_context(ready_client.watch("key-a", False, lambda _value: None))
            stack.enter_context(ready_client.watch("key-b", False, lambda _value: None))

            assert len(_watchers(ready_client, "key-a")) == 1

        assert _watchers(ready_client, "key-a") == []
        assert _watchers(ready_client, "key-b") == []

    def test_rejects_a_non_callable_callback(self, ready_client: ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="callback"):
            ready_client.watch("any-key", False, "not-callable")  # type: ignore[arg-type]

    def test_rejects_an_invalid_default(self, ready_client: ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="must not be None"):
            ready_client.watch("any-key", None, lambda _value: None)  # type: ignore[type-var]

    def test_unwatch_removes_a_single_callback(self, ready_client: ConfigDirectorClient) -> None:
        def first(_value: bool) -> None: ...

        def second(_value: bool) -> None: ...

        ready_client.watch("any-key", False, first)
        ready_client.watch("any-key", False, second)

        ready_client.unwatch("any-key", first)

        assert [watcher.handler for watcher in _watchers(ready_client, "any-key")] == [second]

    def test_unwatch_without_a_callback_removes_every_watcher(
        self, ready_client: ConfigDirectorClient
    ) -> None:
        ready_client.watch("any-key", False, lambda _value: None)
        ready_client.watch("any-key", False, lambda _value: None)

        ready_client.unwatch("any-key")

        assert _watchers(ready_client, "any-key") == []

    def test_unwatch_is_a_no_op_for_an_unknown_key(self, ready_client: ConfigDirectorClient) -> None:
        ready_client.unwatch("never-watched")

    def test_unwatch_all_removes_every_watcher(self, ready_client: ConfigDirectorClient) -> None:
        ready_client.watch("key-a", False, lambda _value: None)
        ready_client.watch("key-b", False, lambda _value: None)

        ready_client.unwatch_all()

        assert _watchers(ready_client, "key-a") == []
        assert _watchers(ready_client, "key-b") == []


class TestEvents:
    def test_on_returns_a_closable_subscription(self, client: ConfigDirectorClient) -> None:
        calls: list[str] = []
        subscription = client.on("client_ready", lambda _event: calls.append("called"))

        subscription.close()
        client.initialize()

        assert calls == []

    def test_the_event_subscription_is_a_context_manager(self, client: ConfigDirectorClient) -> None:
        calls: list[str] = []

        with client.on("client_ready", lambda _event: calls.append("called")):
            pass

        client.initialize()

        assert calls == []

    def test_off_removes_a_single_handler(self, client: ConfigDirectorClient) -> None:
        calls: list[str] = []

        def first(_event: Any) -> None:
            calls.append("first")

        def second(_event: Any) -> None:
            calls.append("second")

        client.on("client_ready", first)
        client.on("client_ready", second)

        client.off("client_ready", first)
        client.initialize()

        assert calls == ["second"]

    def test_off_without_a_handler_removes_every_handler(self, client: ConfigDirectorClient) -> None:
        calls: list[str] = []
        client.on("client_ready", lambda _event: calls.append("first"))
        client.on("client_ready", lambda _event: calls.append("second"))

        client.off("client_ready")
        client.initialize()

        assert calls == []

    @pytest.mark.parametrize("method", ["on", "off"])
    def test_rejects_an_unknown_event_name(self, client: ConfigDirectorClient, method: str) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="Unknown event"):
            getattr(client, method)("not-an-event", lambda _event: None)

    def test_rejects_a_non_callable_handler(self, client: ConfigDirectorClient) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="callable"):
            client.on("client_ready", "not-callable")  # type: ignore[call-overload]

    def test_a_raising_handler_does_not_break_the_caller(self, client: ConfigDirectorClient) -> None:
        def explode(_event: Any) -> None:
            raise RuntimeError("boom")

        calls: list[str] = []
        client.on("client_ready", explode)
        client.on("client_ready", lambda _event: calls.append("second"))

        client.initialize()

        assert client.is_ready is True
        assert calls == ["second"]

    def test_hooks_receive_events_emitted_during_initialization(self, transports: TransportRecorder) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        events: list[ConfigsUpdatedEvent] = []
        client = ConfigDirectorClient(SDK_KEY, hooks=ClientHooks(configs_updated=events.append))

        client.initialize()

        assert len(events) == 1
        assert events[0].keys == ["greeting"]


class TestClose:
    def test_clears_readiness_and_subscribers(self, ready_client: ConfigDirectorClient) -> None:
        calls: list[str] = []
        ready_client.watch("any-key", False, lambda _value: None)
        ready_client.on("client_ready", lambda _event: calls.append("ready"))

        ready_client.close()

        assert ready_client.is_ready is False
        assert ready_client.closed is True
        assert _watchers(ready_client, "any-key") == []
        assert calls == []

    def test_closes_the_transport(
        self, ready_client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        ready_client.close()

        assert transports.last.closed is True

    def test_each_client_owns_its_connection_pool(self) -> None:
        # A pool shared across clients would let one client's close() drop connections another
        # is still using.
        assert ConfigDirectorClient(SDK_KEY)._http is not ConfigDirectorClient(SDK_KEY)._http

    def test_close_releases_the_connection_pool(self, ready_client: ConfigDirectorClient) -> None:
        pool = ready_client._http._pool
        pool.connection_from_url("http://127.0.0.1:1")
        assert len(pool.pools) == 1

        ready_client.close()

        assert len(pool.pools) == 0

    def test_is_idempotent(self, ready_client: ConfigDirectorClient) -> None:
        ready_client.close()
        ready_client.close()

        assert ready_client.is_ready is False

    def test_the_client_initializes_on_enter_and_closes_on_exit(self) -> None:
        with ConfigDirectorClient(SDK_KEY) as client:
            ready_inside_the_block = client.is_ready

        assert ready_inside_the_block is True
        assert client.is_ready is False
        assert client.closed is True

    def test_entering_an_initialized_client_does_not_re_initialize(self) -> None:
        client = ConfigDirectorClient(SDK_KEY)
        calls: list[str] = []
        client.on("client_ready", lambda _event: calls.append("ready"))
        client.initialize()

        with client:
            pass

        assert calls == ["ready"]

    def test_closes_even_when_the_block_raises(self) -> None:
        client = ConfigDirectorClient(SDK_KEY)

        try:
            with client:
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert client.closed is True


class TestConnectionOptions:
    @pytest.mark.parametrize("mode", ["streaming", "polling", "one-time"])
    def test_supports_every_connection_mode(self, mode: Any, transports: TransportRecorder) -> None:
        client = ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(mode=mode))
        client.initialize()

        assert client.is_ready is True
        assert transports.last.mode == mode

    def test_passes_the_polling_interval_to_the_transport(self, transports: TransportRecorder) -> None:
        ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(mode="polling", polling_interval=15))

        assert transports.last.options.polling_interval == 15

    def test_defaults_match_the_documented_values(self) -> None:
        options = ConnectionOptions()

        assert options.mode == "streaming"
        assert options.polling_interval == 60.0
        assert options.timeout == 3.0
        assert options.url is None


class TestTelemetry:
    def test_records_every_evaluation(
        self, client: ConfigDirectorClient, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello", default_value_id="id-1"))
        client.initialize()
        context = Context(id="user-123")

        client.get_value("greeting", "fallback", context)

        assert telemetry.evaluations == [
            RecordedEvaluation(
                key="greeting",
                default="fallback",
                value="hello",
                used_default=False,
                reason="found-match",
                context=context,
                config_type="string",
                value_id="id-1",
            )
        ]

    def test_records_an_evaluation_that_found_no_config_state(
        self, ready_client: ConfigDirectorClient, telemetry: TelemetryRecorder
    ) -> None:
        ready_client.get_value("unknown-key", "fallback")

        recorded = telemetry.evaluations[0]
        assert recorded.key == "unknown-key"
        assert recorded.value == "fallback"
        assert recorded.used_default is True
        assert recorded.reason == "config-state-missing"
        assert recorded.config_type is None

    def test_records_an_evaluation_that_fell_back_to_the_default(
        self, client: ConfigDirectorClient, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("threshold", "not-a-number", type="integer"))
        client.initialize()

        client.get_value("threshold", 10)

        recorded = telemetry.evaluations[0]
        assert recorded.value == 10
        assert recorded.used_default is True
        assert recorded.reason == "invalid-number"

    def test_records_an_evaluation_made_by_a_watcher(
        self, client: ConfigDirectorClient, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        client.initialize()
        client.watch("greeting", "fallback", lambda _value: None)

        transports.last.deliver(bundle(config("greeting", "bonjour")))

        assert [e.value for e in telemetry.evaluations] == ["bonjour"]

    def test_get_all_configs_does_not_record_anything(
        self, client: ConfigDirectorClient, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        client.initialize()

        client.get_all_configs(context=Context(id="user-123"))

        assert telemetry.evaluations == []

    def test_the_collector_is_built_from_the_client_configuration(self, telemetry: TelemetryRecorder) -> None:
        ConfigDirectorClient(
            SDK_KEY,
            connection=ConnectionOptions(url="https://proxy.example.com"),
            telemetry=TelemetryOptions(event_queue_limit=250, flush_interval=10.0),
        )

        options = telemetry.last.options
        assert options.server_sdk_key == SDK_KEY
        assert options.base_url == "https://proxy.example.com"
        assert options.event_queue_limit == 250
        assert options.flush_interval == 10.0

    def test_closing_the_client_closes_the_collector(
        self, ready_client: ConfigDirectorClient, telemetry: TelemetryRecorder
    ) -> None:
        # This is what reports whatever was evaluated since the last flush.
        ready_client.close()

        assert telemetry.last.closed is True

    @pytest.mark.parametrize("limit", [0, 99, 100_001])
    def test_rejects_an_event_queue_limit_outside_the_documented_range(self, limit: int) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="event queue limit"):
            ConfigDirectorClient(SDK_KEY, telemetry=TelemetryOptions(event_queue_limit=limit))

    @pytest.mark.parametrize("limit", [100, 5_000, 100_000])
    def test_accepts_an_event_queue_limit_within_the_documented_range(self, limit: int) -> None:
        ConfigDirectorClient(SDK_KEY, telemetry=TelemetryOptions(event_queue_limit=limit))

    @pytest.mark.parametrize("interval", [0, -1.0])
    def test_rejects_a_non_positive_flush_interval(self, interval: float) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="flush interval"):
            ConfigDirectorClient(SDK_KEY, telemetry=TelemetryOptions(flush_interval=interval))

    def test_defaults_match_the_documented_values(self) -> None:
        options = TelemetryOptions()

        assert options.event_queue_limit == 5_000
        assert options.flush_interval == 30.0

    def test_a_construction_that_fails_leaves_no_flush_thread_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The collector starts a background thread, so it must not be built until nothing else
        # in the constructor can still raise.
        monkeypatch.setattr(configdirector.client, "TelemetryCollector", TelemetryCollector)

        with pytest.raises(ConfigDirectorTypeError):
            ConfigDirectorClient(SDK_KEY, hooks=ClientHooks(client_ready="not callable"))  # type: ignore[arg-type]

        assert not any(t.name == "configdirector-telemetry" for t in threading.enumerate())


def _watchers(client: ConfigDirectorClient, config_key: str) -> list[Any]:
    return client._watchers.get(config_key, [])


class TestValueIds:
    """Server-selected values carry the server's ID; a default from code gets one computed."""

    def _evaluations(self, client: ConfigDirectorClient) -> list[ConfigEvaluatedEvent]:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)
        return events

    def test_a_server_selected_value_carries_the_server_id(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello", default_value_id="id-from-server"))
        client.initialize()
        events = self._evaluations(client)

        assert client.get_value("greeting", "fallback") == "hello"
        assert events[-1].evaluation.value_id == "id-from-server"

    def test_a_missing_config_gets_a_computed_id(self, ready_client: ConfigDirectorClient) -> None:
        events = self._evaluations(ready_client)

        ready_client.get_value("unknown-key", "fallback")

        value_id = events[-1].evaluation.value_id
        assert value_id == generate_value_id("fallback")
        assert len(value_id or "") == VALUE_ID_LENGTH

    def test_a_default_used_after_a_type_mismatch_gets_a_computed_id(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        client.initialize()
        events = self._evaluations(client)

        assert client.get_value("greeting", 42) == 42
        assert events[-1].evaluation.is_default is True
        assert events[-1].evaluation.value_id == generate_value_id("42")

    def test_a_json_default_is_digested_the_way_telemetry_reports_it(
        self, ready_client: ConfigDirectorClient
    ) -> None:
        # The same document must not be counted under two IDs depending on which side hashed it.
        events = self._evaluations(ready_client)

        ready_client.get_value("unknown-key", {"b": 2, "a": [1, True, None]})

        assert events[-1].evaluation.value_id == generate_value_id('{"b":2,"a":[1,true,null]}')

    def test_the_computed_id_reaches_telemetry(
        self, ready_client: ConfigDirectorClient, telemetry: TelemetryRecorder
    ) -> None:
        ready_client.get_value("unknown-key", "fallback")

        assert telemetry.evaluations[-1].value_id == generate_value_id("fallback")

    def test_a_value_the_server_did_not_identify_gets_a_computed_id(
        self, client: ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        # The server IDs everything it sends, so this only arises on a payload that predates
        # value IDs. The ID is derived from the value actually returned, not from the default.
        transports.initial_bundle = bundle(config("greeting", "hello"))
        client.initialize()
        events = self._evaluations(client)

        assert client.get_value("greeting", "fallback") == "hello"
        assert events[-1].evaluation.value_id == generate_value_id("hello")
