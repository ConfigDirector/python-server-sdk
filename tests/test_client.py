from __future__ import annotations

import contextlib
from typing import Any

import pytest

from configdirector import (
    ClientHooks,
    ConfigDirectorClient,
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
    ConfigEvaluatedEvent,
    ConfigsUpdatedEvent,
    ConnectionOptions,
    Context,
    Subscription,
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
    def test_marks_the_client_ready(self, client: ConfigDirectorClient) -> None:
        assert client.is_ready is False

        client.initialize()

        assert client.is_ready is True

    def test_accepts_a_per_call_timeout(self, client: ConfigDirectorClient) -> None:
        client.initialize(timeout=0.5)

        assert client.is_ready is True

    @pytest.mark.parametrize("timeout", [0, -1])
    def test_rejects_a_non_positive_timeout(self, client: ConfigDirectorClient, timeout: float) -> None:
        with pytest.raises(ConfigDirectorValidationError, match="timeout"):
            client.initialize(timeout=timeout)

    def test_rejects_use_after_close(self, client: ConfigDirectorClient) -> None:
        client.close()

        with pytest.raises(ConfigDirectorValidationError, match="closed"):
            client.initialize()

    def test_emits_client_ready_and_configs_updated(self, client: ConfigDirectorClient) -> None:
        events: list[str] = []
        client.on("client_ready", lambda _event: events.append("client_ready"))
        client.on("configs_updated", lambda _event: events.append("configs_updated"))

        client.initialize()

        assert events == ["client_ready", "configs_updated"]


class TestGetValue:
    @pytest.mark.parametrize(
        "default",
        [True, False, "fallback", 42, 3.14, {"a": 1}, [1, 2, 3]],
    )
    def test_returns_the_default_for_every_supported_type(
        self, ready_client: ConfigDirectorClient, default: Any
    ) -> None:
        assert ready_client.get_value("any-key", default) == default

    def test_returns_the_default_before_initialization(self, client: ConfigDirectorClient) -> None:
        assert client.get_value("any-key", "fallback") == "fallback"

    def test_accepts_a_context(self, ready_client: ConfigDirectorClient) -> None:
        context = Context(id="user-123", name="Ada", traits={"plan": "pro"}, anonymous=False)

        assert ready_client.get_value("any-key", False, context) is False

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

    def test_reports_client_not_ready_before_initialization(self, client: ConfigDirectorClient) -> None:
        events: list[ConfigEvaluatedEvent] = []
        client.on("config_evaluated", events.append)

        client.get_value("any-key", "fallback")

        assert events[0].evaluation.reason == "client-not-ready"


class TestGetAllConfigs:
    def test_returns_nothing_before_initialization(self, client: ConfigDirectorClient) -> None:
        assert client.get_all_configs() == {}

    def test_returns_every_known_config(self, ready_client: ConfigDirectorClient) -> None:
        configs = ready_client.get_all_configs()

        assert set(configs) == {"example-boolean-config", "example-string-config"}
        assert configs["example-boolean-config"].key == "example-boolean-config"
        assert configs["example-boolean-config"].type == "boolean"

    def test_filters_by_config_keys(self, ready_client: ConfigDirectorClient) -> None:
        configs = ready_client.get_all_configs(config_keys=["example-string-config", "unknown"])

        assert set(configs) == {"example-string-config"}

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

    def test_hooks_receive_events_emitted_during_initialization(self) -> None:
        events: list[ConfigsUpdatedEvent] = []
        client = ConfigDirectorClient(SDK_KEY, hooks=ClientHooks(configs_updated=events.append))

        client.initialize()

        assert len(events) == 1
        assert events[0].keys == ["example-boolean-config", "example-string-config"]


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
    def test_supports_every_connection_mode(self, mode: Any) -> None:
        client = ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(mode=mode))
        client.initialize()

        assert client.is_ready is True

    def test_defaults_match_the_documented_values(self) -> None:
        options = ConnectionOptions()

        assert options.mode == "streaming"
        assert options.polling_interval == 60.0
        assert options.timeout == 3.0
        assert options.url is None


def _watchers(client: ConfigDirectorClient, config_key: str) -> list[Any]:
    return client._watchers.get(config_key, [])
