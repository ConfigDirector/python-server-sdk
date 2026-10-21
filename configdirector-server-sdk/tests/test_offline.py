from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import urllib3.connectionpool

from configdirector import (
    ClientReadyEvent,
    ConfigDirectorClient,
    ConfigDirectorInitializationError,
    ConfigEvaluatedEvent,
    ConnectionOptions,
    Context,
    create_client,
)
from tests.helpers import RecordingLogger, ThreadWatch

SDK_KEY = "test-server-sdk-key"

ClientFactory = Callable[..., ConfigDirectorClient]


@pytest.fixture(autouse=True)
def http_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requests: list[str] = []

    def refuse(self: object, method: str, url: str, *args: object, **kwargs: object) -> None:
        requests.append(f"{method} {url}")
        raise AssertionError("an offline client must not make requests")

    monkeypatch.setattr(urllib3.connectionpool.HTTPConnectionPool, "urlopen", refuse)
    return requests


@pytest.fixture
def create() -> Iterator[ClientFactory]:
    clients: list[ConfigDirectorClient] = []

    def factory(*server_sdk_key_if_given: str, **options: Any) -> ConfigDirectorClient:
        client = create_client(*server_sdk_key_if_given, **options)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


def test_a_missing_sdk_key_is_accepted_in_offline_mode(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline"))

    client.initialize()

    assert client.is_ready is True


def test_an_empty_sdk_key_is_accepted_in_offline_mode(create: ClientFactory) -> None:
    client = create("", connection=ConnectionOptions(mode="offline"))

    client.initialize()

    assert client.is_ready is True


def test_a_blank_sdk_key_is_accepted_in_offline_mode(create: ClientFactory) -> None:
    client = create("   ", connection=ConnectionOptions(mode="offline"))

    client.initialize()

    assert client.is_ready is True


def test_inline_values_serve_each_value_with_its_type(create: ClientFactory) -> None:
    client = create(
        connection=ConnectionOptions(
            mode="offline",
            values={
                "new-checkout": True,
                "max-items": 20,
                "ratio": 2.5,
                "greeting": "hello",
                "theme": {"color": "blue"},
                "tags": ["a", "b"],
            },
        )
    )

    client.initialize()

    assert client.get_value("new-checkout", False) is True
    assert client.get_value("max-items", 0) == 20
    assert client.get_value("ratio", 0.0) == 2.5
    assert client.get_value("greeting", "fallback") == "hello"
    assert client.get_value("theme", {}) == {"color": "blue"}
    assert client.get_value("tags", []) == ["a", "b"]


def test_a_file_serves_each_value_with_its_type(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "new-checkout-on.json"
    file.write_text(
        '{"new-checkout": true, "max-items": 20, "ratio": 2.5, "greeting": "hello", '
        '"theme": {"color": "blue"}, "tags": ["a", "b"]}'
    )
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))

    client.initialize()

    assert client.get_value("new-checkout", False) is True
    assert client.get_value("max-items", 0) == 20
    assert client.get_value("ratio", 0.0) == 2.5
    assert client.get_value("greeting", "fallback") == "hello"
    assert client.get_value("theme", {}) == {"color": "blue"}
    assert client.get_value("tags", []) == ["a", "b"]


def test_no_source_serves_every_in_code_default_value_with_config_state_missing(
    create: ClientFactory,
) -> None:
    client = create(connection=ConnectionOptions(mode="offline"))
    evaluations: list[ConfigEvaluatedEvent] = []
    client.on("config_evaluated", evaluations.append)
    client.initialize()

    value = client.get_value("new-checkout", True)

    assert value is True
    assert evaluations[-1].evaluation.reason == "config-state-missing"


def test_a_file_given_as_a_path_serves_its_values(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"new-checkout": true}')
    client = create(connection=ConnectionOptions(mode="offline", file=file))

    client.initialize()

    assert client.get_value("new-checkout", False) is True


def test_a_served_value_is_a_found_match(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))
    evaluations: list[ConfigEvaluatedEvent] = []
    client.on("config_evaluated", evaluations.append)
    client.initialize()

    client.get_value("new-checkout", False)

    assert evaluations[-1].evaluation.reason == "found-match"
    assert evaluations[-1].evaluation.is_default is False


def test_every_context_receives_the_same_value(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"max-items": 20}))
    client.initialize()

    for_no_context = client.get_value("max-items", 0)
    for_a_user = client.get_value("max-items", 0, Context(id="user-a"))
    for_a_device = client.get_value("max-items", 0, Context(id="42", traits={"plan": "pro"}, kind="device"))

    assert (for_no_context, for_a_user, for_a_device) == (20, 20, 20)


def test_a_value_read_as_another_type_serves_the_in_code_default_with_type_mismatch(
    create: ClientFactory,
) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))
    evaluations: list[ConfigEvaluatedEvent] = []
    client.on("config_evaluated", evaluations.append)
    client.initialize()

    value = client.get_value("new-checkout", "fallback")

    assert value == "fallback"
    assert evaluations[-1].evaluation.reason == "type-mismatch"


def test_get_all_configs_returns_the_offline_values(create: ClientFactory) -> None:
    client = create(
        connection=ConnectionOptions(mode="offline", values={"new-checkout": True, "max-items": 20})
    )
    client.initialize()

    configs = client.get_all_configs()

    assert {key: (state.type, state.value) for key, state in configs.items()} == {
        "new-checkout": ("boolean", "true"),
        "max-items": ("integer", "20"),
    }


def test_initialize_makes_the_client_ready_at_once_and_fires_client_ready_once(
    create: ClientFactory,
) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}, timeout=30))
    ready_events: list[ClientReadyEvent] = []
    client.on("client_ready", ready_events.append)

    started = time.monotonic()
    client.initialize()
    elapsed = time.monotonic() - started

    assert client.is_ready is True
    assert elapsed < 2.0
    assert len(ready_events) == 1


def test_a_watch_is_called_once_with_the_offline_value_and_never_again(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))
    watched: list[bool] = []
    client.watch("new-checkout", False, watched.append)

    client.initialize()
    client.get_value("new-checkout", False)
    client.get_all_configs()

    assert watched == [True]


def test_initializing_again_reads_the_file_again(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"max-items": 20}')
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))
    client.initialize()
    file.write_text('{"max-items": 30}')

    client.initialize()

    assert client.get_value("max-items", 0) == 30


def test_a_later_initialize_that_cannot_read_the_file_keeps_the_values_read_before(
    create: ClientFactory, tmp_path: Path
) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"max-items": 20}')
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))
    client.initialize()
    file.unlink()

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    ready_after_the_rejection = client.is_ready
    assert ready_after_the_rejection is True
    assert client.get_value("max-items", 0) == 20


def test_a_missing_file_rejects_initialization(create: ClientFactory, tmp_path: Path) -> None:
    client = create(connection=ConnectionOptions(mode="offline", file=str(tmp_path / "missing.json")))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_an_unreadable_file_rejects_initialization(create: ClientFactory, tmp_path: Path) -> None:
    client = create(connection=ConnectionOptions(mode="offline", file=str(tmp_path)))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_a_file_that_is_not_json_rejects_initialization(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"new-checkout": true,')
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_a_file_holding_an_array_rejects_initialization(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('["new-checkout"]')
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_a_file_holding_a_null_value_rejects_initialization(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"new-checkout": null}')
    client = create(connection=ConnectionOptions(mode="offline", file=str(file)))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_an_inline_none_value_rejects_initialization(create: ClientFactory) -> None:
    client = create(
        connection=ConnectionOptions(mode="offline", values={"new-checkout": None})  # type: ignore[dict-item]
    )

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_a_file_and_values_together_reject_initialization(create: ClientFactory, tmp_path: Path) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"new-checkout": true}')
    client = create(
        connection=ConnectionOptions(mode="offline", file=str(file), values={"new-checkout": False})
    )

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False


def test_a_file_in_streaming_mode_rejects_initialization_without_connecting(
    create: ClientFactory, tmp_path: Path, http_requests: list[str]
) -> None:
    file = tmp_path / "flags.json"
    file.write_text('{"new-checkout": true}')
    client = create(SDK_KEY, connection=ConnectionOptions(mode="streaming", file=str(file)))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False
    assert http_requests == []


def test_values_in_polling_mode_reject_initialization_without_connecting(
    create: ClientFactory, http_requests: list[str]
) -> None:
    client = create(SDK_KEY, connection=ConnectionOptions(mode="polling", values={"new-checkout": True}))

    with pytest.raises(ConfigDirectorInitializationError):
        client.initialize()

    assert client.is_ready is False
    assert http_requests == []


def test_sends_nothing_and_starts_no_sdk_thread(create: ClientFactory, http_requests: list[str]) -> None:
    threads = ThreadWatch()
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))

    client.initialize()
    client.get_value("new-checkout", False)
    client.get_value("max-items", 0)
    new_sdk_threads = threads.new_sdk_threads()
    client.close()

    assert new_sdk_threads == set()
    assert http_requests == []


def test_an_invalid_url_is_ignored(create: ClientFactory) -> None:
    client = create(
        connection=ConnectionOptions(mode="offline", values={"new-checkout": True}, url="not-a-url")
    )

    client.initialize()

    assert client.get_value("new-checkout", False) is True


def test_a_non_positive_connection_timeout_is_ignored(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}, timeout=0))

    client.initialize()

    assert client.get_value("new-checkout", False) is True


def test_a_non_positive_initialize_timeout_is_ignored(create: ClientFactory) -> None:
    client = create(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))

    client.initialize(timeout=0)

    assert client.get_value("new-checkout", False) is True


def test_a_polling_interval_below_the_minimum_is_ignored_without_a_warning(create: ClientFactory) -> None:
    logger = RecordingLogger()
    client = create(
        connection=ConnectionOptions(mode="offline", values={"new-checkout": True}, polling_interval=1),
        logger=logger,
    )

    client.initialize()

    assert client.get_value("new-checkout", False) is True
    assert logger.messages("warning") == []
