from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import urllib3.connectionpool

from configdirector import (
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
    ConfigEvaluatedEvent,
    ConfigsUpdatedEvent,
    Context,
)
from configdirector.testing import TestClient, create_test_client
from tests.helpers import RecordingLogger, wait_for

PROMPTLY = 5.0
LONGER_THAN_THE_TEST_WAITS = 30.0


class ThreadWatch:
    def __init__(self) -> None:
        self._before = set(threading.enumerate())

    def new_sdk_threads(self) -> set[str]:
        return {
            thread.name
            for thread in threading.enumerate()
            if thread not in self._before and thread.name.startswith("configdirector-")
        }


def start_initialize(client: Any) -> threading.Thread:
    thread = threading.Thread(target=client.initialize, name="test-initialize")
    thread.start()
    assert wait_for(lambda: thread.is_alive() and not client.is_ready)
    time.sleep(0.05)
    return thread


def join(thread: threading.Thread) -> None:
    thread.join(PROMPTLY)
    assert not thread.is_alive()


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


@pytest.fixture
def threads() -> ThreadWatch:
    return ThreadWatch()


@pytest.fixture
def create(logger: RecordingLogger) -> Iterator[Callable[..., TestClient]]:
    test_clients: list[TestClient] = []

    def factory(values: dict[str, Any] | None = None, *, timeout: float | None = None) -> TestClient:
        test_client = create_test_client(values, timeout=timeout, logger=logger)
        test_clients.append(test_client)
        return test_client

    yield factory
    for test_client in test_clients:
        test_client.close()


def updates_of(client: Any) -> list[ConfigsUpdatedEvent]:
    updates: list[ConfigsUpdatedEvent] = []
    client.on("configs_updated", updates.append)
    return updates


def evaluations_of(client: Any) -> list[ConfigEvaluatedEvent]:
    evaluations: list[ConfigEvaluatedEvent] = []
    client.on("config_evaluated", evaluations.append)
    return evaluations


def ready_count_of(client: Any) -> Callable[[], int]:
    count = [0]

    def increment(_event: object) -> None:
        count[0] += 1

    client.on("client_ready", increment)
    return lambda: count[0]


class TestConformance:
    def test_s1_reads_every_seeded_value_type_after_initialize(
        self, create: Callable[..., TestClient]
    ) -> None:
        client = create(
            {
                "flag": True,
                "count": 20,
                "ratio": 2.5,
                "greeting": "hello",
                "theme": {"color": "blue", "sizes": [1, 2]},
                "tags": ["a", "b"],
            }
        ).client

        client.initialize()

        assert client.is_ready is True
        assert client.get_value("flag", False) is True
        assert client.get_value("count", 0) == 20
        assert client.get_value("ratio", 0.0) == 2.5
        assert client.get_value("greeting", "x") == "hello"
        assert client.get_value("theme", {}) == {"color": "blue", "sizes": [1, 2]}
        assert client.get_value("tags", []) == ["a", "b"]
        assert sorted(client.get_all_configs()) == ["count", "flag", "greeting", "ratio", "tags", "theme"]

    def test_serves_the_same_value_to_every_context(self, create: Callable[..., TestClient]) -> None:
        client = create({"flag": True}).client
        client.initialize()

        assert client.get_value("flag", False, Context(id="user-a")) is True
        assert client.get_value("flag", False, Context(id="user-b", traits={"plan": "pro"})) is True

    def test_s2_reading_a_boolean_as_a_string_returns_the_in_code_default_with_type_mismatch(
        self, create: Callable[..., TestClient]
    ) -> None:
        client = create({"flag": True}).client
        evaluations = evaluations_of(client)
        client.initialize()

        assert client.get_value("flag", "fallback") == "fallback"

        assert evaluations[-1].evaluation.reason == "type-mismatch"

    def test_s3_set_value_on_a_connected_client_changes_the_next_read(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"count": 20})
        test_client.client.initialize()

        test_client.set_value("count", 25)

        assert test_client.client.get_value("count", 0) == 25

    def test_s4_set_value_fires_the_keys_watch_and_lists_the_key_in_configs_updated(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"count": 20})
        client = test_client.client
        watched: list[int] = []
        client.watch("count", 0, watched.append)
        updates = updates_of(client)
        client.initialize()

        test_client.set_value("count", 25)

        assert watched == [20, 25]
        assert updates[-1].keys == ["count"]
        assert updates[-1].removed_keys == []

    def test_s5_set_value_of_another_key_does_not_fire_an_unrelated_watch(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"a": 1, "b": 1})
        watched_a: list[int] = []
        test_client.client.watch("a", 0, watched_a.append)
        test_client.client.initialize()

        test_client.set_value("b", 2)

        assert watched_a == [1]

    def test_s6_remove_value_makes_reads_return_the_in_code_default_with_config_state_missing(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True})
        evaluations = evaluations_of(test_client.client)
        test_client.client.initialize()

        test_client.remove_value("flag")

        assert test_client.client.get_value("flag", False) is False
        assert evaluations[-1].evaluation.reason == "config-state-missing"

    def test_s7_remove_value_fires_the_watch_with_the_default_and_lists_the_key_in_removed_keys(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True, "count": 20})
        client = test_client.client
        watched: list[bool] = []
        client.watch("flag", False, watched.append)
        updates = updates_of(client)
        client.initialize()

        test_client.remove_value("flag")

        assert watched == [True, False]
        assert updates[-1].keys == ["count"]
        assert updates[-1].removed_keys == ["flag"]

    def test_s8_a_value_set_before_initialize_is_delivered_by_the_first_attempt(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True})
        updates = updates_of(test_client.client)

        test_client.set_value("greeting", "hello")
        test_client.client.initialize()

        assert len(updates) == 1
        assert updates[0].keys == ["flag", "greeting"]
        assert test_client.client.get_value("greeting", "x") == "hello"

    def test_s9_a_held_initialize_completes_ready_when_completed(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        client = test_client.client
        ready = ready_count_of(client)
        test_client.hold_initialization()

        initializing = start_initialize(client)
        ready_while_held = client.is_ready
        assert ready_while_held is False
        assert ready() == 0

        test_client.complete_initialization()

        ready_after_completion = client.is_ready
        assert ready_after_completion is True
        assert ready() == 1
        assert client.get_value("flag", False) is True
        join(initializing)

        test_client.set_value("flag", False)

        assert client.get_value("flag", True) is False

    def test_a_new_attempt_ends_a_held_one(self, create: Callable[..., TestClient]) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        client = test_client.client
        test_client.hold_initialization()
        held = start_initialize(client)

        client.initialize()

        assert client.is_ready is True
        join(held)
        holding_after_the_new_attempt = test_client._connection.is_holding_an_attempt
        assert holding_after_the_new_attempt is False

    def test_s10_a_value_set_while_held_is_delivered_on_completion(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        client = test_client.client
        test_client.hold_initialization()
        initializing = start_initialize(client)

        test_client.set_value("flag", False)
        assert client.is_ready is False
        test_client.complete_initialization()

        assert client.get_value("flag", True) is False
        join(initializing)

    def test_s11_a_held_initialize_that_times_out_completes_not_ready_and_the_next_one_is_ready(
        self, create: Callable[..., TestClient], logger: RecordingLogger
    ) -> None:
        test_client = create({"flag": True}, timeout=0.2)
        client = test_client.client
        ready = ready_count_of(client)
        test_client.hold_initialization()

        client.initialize()

        ready_after_the_timeout = client.is_ready
        assert ready_after_the_timeout is False
        assert any("Timed out waiting for initialization" in m for m in logger.messages("warning"))
        test_client.complete_initialization()
        ready_after_completing_a_used_up_hold = client.is_ready
        assert ready_after_completing_a_used_up_hold is False
        assert ready() == 0

        client.initialize()

        ready_after_the_second_attempt = client.is_ready
        assert ready_after_the_second_attempt is True
        assert ready() == 1
        assert client.get_value("flag", False) is True

    def test_s12_a_failed_initialize_completes_promptly_not_ready_without_client_ready_and_logs_the_error(
        self, create: Callable[..., TestClient], logger: RecordingLogger
    ) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        client = test_client.client
        ready = ready_count_of(client)
        test_client.fail_initialization()

        started = time.monotonic()
        client.initialize()

        assert time.monotonic() - started < 2.0
        assert client.is_ready is False
        assert ready() == 0
        assert any(
            m.startswith("[InMemoryConnection] Connection failed with status: 401")
            for m in logger.messages("error")
        )
        assert any("error occurred during initialization" in m for m in logger.messages("error"))

    def test_s14_after_close_the_controls_are_silent_no_ops(self, create: Callable[..., TestClient]) -> None:
        test_client = create({"flag": True})
        client = test_client.client
        watched: list[bool] = []
        client.watch("flag", False, watched.append)
        client.initialize()

        test_client.close()

        assert client.closed is True
        test_client.set_value("flag", False)
        test_client.remove_value("flag")
        test_client.replace_values({"flag": False})
        test_client.hold_initialization()
        test_client.complete_initialization()
        test_client.fail_initialization()
        test_client.close()
        assert watched == [True]

    def test_s15_two_test_clients_in_one_test_never_share_values(
        self, create: Callable[..., TestClient]
    ) -> None:
        first = create({"flag": True})
        second = create({"flag": False})
        first.client.initialize()
        second.client.initialize()

        second.set_value("flag", True)
        second.set_value("count", 1)

        assert first.client.get_value("flag", False) is True
        assert first.client.get_value("count", 0) == 0
        assert second.client.get_value("count", 0) == 1

    def test_s17_after_close_no_sdk_thread_is_left_running(
        self, create: Callable[..., TestClient], threads: ThreadWatch
    ) -> None:
        test_client = create({"flag": True})
        test_client.client.initialize()
        test_client.set_value("flag", False)

        test_client.close()

        assert threads.new_sdk_threads() == set()

    def test_s23_a_full_scenario_makes_no_http_request_and_starts_no_sdk_thread(
        self, create: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch, threads: ThreadWatch
    ) -> None:
        requests: list[str] = []

        def refuse(self: object, method: str, url: str, *args: object, **kwargs: object) -> None:
            requests.append(f"{method} {url}")
            raise AssertionError("the test client must not make requests")

        monkeypatch.setattr(urllib3.connectionpool.HTTPConnectionPool, "urlopen", refuse)
        test_client = create({"flag": True, "count": 20, "greeting": "hello"})
        client = test_client.client

        client.initialize()
        assert client.get_value("flag", False) is True
        assert client.get_value("count", 0) == 20
        assert client.get_value("greeting", "x") == "hello"
        test_client.set_value("flag", False)
        assert client.get_value("flag", True) is False
        assert threads.new_sdk_threads() == set()
        test_client.close()

        assert requests == []

    def test_s24_a_value_removed_before_initialize_reads_as_the_in_code_default_with_config_state_missing(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True, "count": 20})
        evaluations = evaluations_of(test_client.client)

        test_client.remove_value("flag")
        test_client.client.initialize()

        assert test_client.client.is_ready is True
        assert test_client.client.get_value("flag", False) is False
        assert evaluations[-1].evaluation.reason == "config-state-missing"

    def test_s25_the_attempt_after_a_failure_succeeds_with_the_values_stored_in_the_meantime(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True})
        client = test_client.client
        test_client.fail_initialization()
        client.initialize()
        ready_after_the_failure = client.is_ready
        assert ready_after_the_failure is False

        test_client.set_value("count", 4)
        client.initialize()

        ready_after_the_second_attempt = client.is_ready
        assert ready_after_the_second_attempt is True
        assert client.get_value("count", 0) == 4
        assert client.get_value("flag", False) is True

    def test_s32_replace_values_serves_exactly_the_new_values_and_fires_the_watch_of_a_dropped_key(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"a": 1, "b": 2})
        client = test_client.client
        watched_b: list[int] = []
        client.watch("b", 0, watched_b.append)
        evaluations = evaluations_of(client)
        client.initialize()

        test_client.replace_values({"a": 10, "c": 3})

        assert client.get_value("a", 0) == 10
        assert client.get_value("c", 0) == 3
        assert client.get_value("b", 0) == 0
        assert evaluations[-1].evaluation.reason == "config-state-missing"
        assert watched_b == [2, 0]

    def test_s33_closing_the_client_ends_a_held_initialize_promptly_not_ready(
        self, create: Callable[..., TestClient], threads: ThreadWatch
    ) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        client = test_client.client
        test_client.hold_initialization()
        initializing = start_initialize(client)
        holding_while_held = test_client._connection.is_holding_an_attempt
        assert holding_while_held is True

        test_client.close()

        join(initializing)
        assert client.is_ready is False
        holding_after_close = test_client._connection.is_holding_an_attempt
        assert holding_after_close is False
        assert threads.new_sdk_threads() == set()

    def test_s38_completing_before_initialize_picks_the_hold_up_lets_it_proceed_at_once(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        test_client.hold_initialization()
        test_client.complete_initialization()

        started = time.monotonic()
        test_client.client.initialize()

        assert time.monotonic() - started < 2.0
        assert test_client.client.is_ready is True
        assert test_client.client.get_value("flag", False) is True

    def test_s40_replace_values_disarms_an_armed_hold(self, create: Callable[..., TestClient]) -> None:
        test_client = create({"flag": True}, timeout=LONGER_THAN_THE_TEST_WAITS)
        test_client.hold_initialization()

        test_client.replace_values({"count": 5})
        started = time.monotonic()
        test_client.client.initialize()

        assert time.monotonic() - started < 2.0
        assert test_client.client.is_ready is True
        assert test_client.client.get_value("count", 0) == 5
        assert test_client.client.get_value("flag", False) is False

    def test_s41_a_set_value_from_a_watch_is_delivered_after_the_outer_delivery(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"a": 1, "b": 1})
        client = test_client.client
        ready = ready_count_of(client)
        order: list[str] = []

        def on_a(value: int) -> None:
            if value == 2:
                test_client.set_value("b", 2)
                order.append("a-watch-returned")

        client.watch("a", 0, on_a)
        client.watch("b", 0, lambda value: order.append(f"b={value}"))
        client.initialize()
        order.clear()

        test_client.set_value("a", 2)

        assert order == ["a-watch-returned", "b=2"]
        assert ready() == 1
        assert client.get_value("a", 0) == 2
        assert client.get_value("b", 0) == 2

    def test_a_delivery_requested_while_another_thread_delivers_is_made_by_that_thread(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"a": 1, "b": 1})
        client = test_client.client
        watch_entered = threading.Event()
        release_watch = threading.Event()
        events: list[str] = []

        def on_a(value: int) -> None:
            if value == 2:
                watch_entered.set()
                release_watch.wait(PROMPTLY)
                events.append(f"a=2 on {threading.current_thread().name}")

        client.watch("a", 0, on_a)
        client.watch("b", 0, lambda value: events.append(f"b={value} on {threading.current_thread().name}"))
        client.initialize()
        events.clear()
        outer = threading.Thread(target=lambda: test_client.set_value("a", 2), name="outer-delivery")
        outer.start()
        assert watch_entered.wait(PROMPTLY)

        test_client.set_value("b", 2)

        assert events == []
        release_watch.set()
        join(outer)
        assert events == ["a=2 on outer-delivery", "b=2 on outer-delivery"]
        assert client.get_value("b", 0) == 2


class TestValues:
    def test_a_string_is_always_a_string_config_and_a_dict_or_list_is_a_json_config(
        self, create: Callable[..., TestClient]
    ) -> None:
        client = create({"text": '{"a":1}', "document": {"a": 1}, "items": [1]}).client
        client.initialize()

        configs = client.get_all_configs()
        assert configs["text"].type == "string"
        assert configs["document"].type == "json"
        assert configs["items"].type == "json"
        assert client.get_value("text", "x") == '{"a":1}'
        assert client.get_value("document", {}) == {"a": 1}

    def test_encodes_each_native_type_the_way_the_backend_does(
        self, create: Callable[..., TestClient]
    ) -> None:
        client = create(
            {
                "flag": False,
                "count": 20,
                "big": 3_000_000_000,
                "ratio": 2.5,
                "whole": 2.0,
                "tiny": 1e-7,
                "huge": 1e21,
                "document": {"z": 1, "a": [1, 2.5, "x", None, True]},
                "unicode": {"name": "café"},
                "text": '<a>&"',
            }
        ).client
        client.initialize()

        configs = client.get_all_configs()
        assert (configs["flag"].type, configs["flag"].value) == ("boolean", "false")
        assert (configs["count"].type, configs["count"].value) == ("integer", "20")
        assert configs["big"].value == "3000000000"
        assert (configs["ratio"].type, configs["ratio"].value) == ("float", "2.5")
        assert configs["whole"].value == "2"
        assert configs["tiny"].value == "0.0000001"
        assert configs["huge"].value == "1000000000000000000000"
        assert configs["document"].value == '{"z":1,"a":[1,2.5,"x",null,true]}'
        assert configs["unicode"].value == '{"name":"café"}'
        assert configs["text"].value == '<a>&"'
        assert client.get_value("tiny", 0.0) == 1e-7
        assert client.get_value("huge", 0.0) == 1e21

    def test_rejected_values_raise_the_sdks_errors_and_change_nothing(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True})
        test_client.client.initialize()

        with pytest.raises(ConfigDirectorTypeError):
            test_client.set_value("flag", None)  # type: ignore[arg-type]
        with pytest.raises(ConfigDirectorTypeError):
            test_client.set_value("flag", object())  # type: ignore[arg-type]
        with pytest.raises(ConfigDirectorTypeError):
            test_client.set_value("flag", {1: "one"})  # type: ignore[dict-item]
        with pytest.raises(ConfigDirectorTypeError):
            test_client.set_value("flag", {"a": object()})
        with pytest.raises(ConfigDirectorTypeError):
            test_client.set_value("flag", (1, 2))  # type: ignore[arg-type]
        with pytest.raises(ConfigDirectorValidationError):
            test_client.set_value("flag", float("nan"))
        with pytest.raises(ConfigDirectorValidationError):
            test_client.set_value("flag", [1, float("inf")])
        with pytest.raises(ConfigDirectorValidationError):
            test_client.set_value(" ", True)
        with pytest.raises(ConfigDirectorValidationError):
            test_client.set_value("flag", 10**5000)
        with pytest.raises(ConfigDirectorTypeError):
            test_client.replace_values({"flag": None})  # type: ignore[dict-item]
        with pytest.raises(ConfigDirectorTypeError):
            create_test_client({"flag": None})  # type: ignore[dict-item]

        assert test_client.client.get_value("flag", False) is True

    def test_an_empty_string_serves_the_in_code_default_with_value_missing(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"greeting": ""})
        evaluations = evaluations_of(test_client.client)
        test_client.client.initialize()

        assert test_client.client.get_value("greeting", "fallback") == "fallback"

        assert evaluations[-1].evaluation.reason == "value-missing"

    def test_a_float_read_with_an_integer_default_returns_the_default_with_invalid_number(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"ratio": 2.5})
        evaluations = evaluations_of(test_client.client)
        test_client.client.initialize()

        assert test_client.client.get_value("ratio", 0) == 0

        assert evaluations[-1].evaluation.reason == "invalid-number"


class TestFactory:
    def test_creates_an_empty_uninitialized_test_client_by_default(self) -> None:
        with create_test_client() as test_client:
            ready_before_initialize = test_client.client.is_ready
            closed_inside_the_block = test_client.client.closed
            test_client.client.initialize()
            ready_after_initialize = test_client.client.is_ready
            assert ready_before_initialize is False
            assert closed_inside_the_block is False
            assert ready_after_initialize is True
            assert test_client.client.get_all_configs() == {}

        closed_after_the_block = test_client.client.closed
        assert closed_after_the_block is True

    def test_the_default_logger_is_the_sdks_logger(self, caplog: pytest.LogCaptureFixture) -> None:
        with (
            create_test_client(timeout=0.2) as test_client,
            caplog.at_level(logging.WARNING, logger="configdirector"),
        ):
            test_client.hold_initialization()
            test_client.client.initialize()

        assert any("Timed out waiting for initialization" in record.message for record in caplog.records)
        assert {record.name for record in caplog.records} == {"configdirector"}

    def test_the_timeout_bounds_a_held_initialize(self, create: Callable[..., TestClient]) -> None:
        test_client = create(timeout=0.2)
        test_client.hold_initialization()

        started = time.monotonic()
        test_client.client.initialize()

        assert 0.2 <= time.monotonic() - started < 2.0
        assert test_client.client.is_ready is False

    def test_the_timeout_given_to_initialize_bounds_the_hold_instead(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create(timeout=LONGER_THAN_THE_TEST_WAITS)
        test_client.hold_initialization()

        started = time.monotonic()
        test_client.client.initialize(timeout=0.2)

        assert 0.2 <= time.monotonic() - started < 2.0
        assert test_client.client.is_ready is False

    def test_the_first_update_fires_configs_updated_before_client_ready(
        self, create: Callable[..., TestClient]
    ) -> None:
        client = create({"flag": True}).client
        order: list[str] = []
        watched: list[bool] = []
        client.watch("flag", False, watched.append)
        client.on("configs_updated", lambda _event: order.append("configs_updated"))
        client.on("client_ready", lambda _event: order.append("client_ready"))

        client.initialize()

        assert order == ["configs_updated", "client_ready"]
        assert watched == [True]

    def test_a_raising_watch_is_logged_and_does_not_propagate(
        self, create: Callable[..., TestClient], logger: RecordingLogger
    ) -> None:
        test_client = create({"flag": True})
        client = test_client.client
        client.initialize()

        def explode(_value: bool) -> None:
            raise RuntimeError("from the watch")

        client.watch("flag", False, explode)

        test_client.set_value("flag", False)

        assert client.get_value("flag", True) is False
        assert any("from the watch" in m for m in logger.messages("error"))

    def test_after_close_reads_serve_the_last_values_and_initialize_raises(
        self, create: Callable[..., TestClient]
    ) -> None:
        test_client = create({"flag": True})
        client = test_client.client
        evaluations = evaluations_of(client)
        client.initialize()

        test_client.close()

        assert client.is_ready is False
        assert client.get_value("flag", False) is True
        assert evaluations == []
        assert client.get_all_configs() == {}
        with pytest.raises(ConfigDirectorValidationError, match="closed"):
            client.initialize()

    def test_readiness_is_sticky_across_a_later_held_attempt(self, create: Callable[..., TestClient]) -> None:
        test_client = create({"flag": True}, timeout=0.2)
        client = test_client.client
        ready = ready_count_of(client)
        client.initialize()
        test_client.hold_initialization()

        client.initialize()

        assert client.is_ready is True
        assert client.get_value("flag", False) is True
        assert ready() == 1
