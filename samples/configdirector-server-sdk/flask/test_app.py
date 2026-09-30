"""Tests for the sample, written the way an application using the SDK tests itself.

The application reads its client through ``get_client()``. Each test replaces that with the
client of a **test client** from ``configdirector.testing``: the SDK's real client over an
in-memory connection the test controls, so no network is involved and no SDK key is needed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from configdirector import ConfigDirectorClient, ConfigEvaluatedEvent, ConfigValue
from configdirector.testing import TestClient, create_test_client
from flask.testing import FlaskClient

import app as app_module
import configdirector_client
from app import app

SAMPLE_VALUES: dict[str, ConfigValue] = {
    "temporary-feature-flag": False,
    "permanent-kill-switch": True,
    "integer-config": 42,
    "day-of-the-week-config": "Tuesday",
    "json-value-config": {"greeting": "hello"},
}


@pytest.fixture
def test_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with create_test_client(SAMPLE_VALUES) as test_client:
        test_client.client.initialize()
        monkeypatch.setattr(app_module, "get_client", lambda: test_client.client)
        yield test_client


@pytest.fixture
def http(test_client: TestClient) -> FlaskClient:
    return app.test_client()


def test_configs_returns_the_value_of_every_config(http: FlaskClient) -> None:
    response = http.get("/configs?id=user-123&plan=pro")

    assert response.status_code == 200
    assert response.get_json() == SAMPLE_VALUES


def test_a_changed_value_is_served_on_the_next_request(http: FlaskClient, test_client: TestClient) -> None:
    assert http.get("/configs").get_json()["integer-config"] == 42

    test_client.set_value("integer-config", 7)

    assert http.get("/configs").get_json()["integer-config"] == 7


def test_a_removed_config_falls_back_to_the_default(http: FlaskClient, test_client: TestClient) -> None:
    test_client.remove_value("day-of-the-week-config")

    assert http.get("/configs").get_json()["day-of-the-week-config"] == "Friday"


def test_the_query_string_becomes_the_evaluation_context(http: FlaskClient, test_client: TestClient) -> None:
    evaluated: list[ConfigEvaluatedEvent] = []
    test_client.client.on("config_evaluated", evaluated.append)

    http.get("/configs?id=user-123&name=Ada&anonymous=true&plan=pro")

    assert len(evaluated) == 5
    context = evaluated[0].evaluation.context
    assert all(event.evaluation.context == context for event in evaluated)
    assert context is not None
    assert context.id == "user-123"
    assert context.name == "Ada"
    assert context.anonymous is True
    assert context.traits == {"plan": "pro"}


def test_configs_resolve_to_defaults_when_configdirector_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with create_test_client(SAMPLE_VALUES, timeout=0.5) as test_client:
        test_client.fail_initialization()
        test_client.client.initialize()
        monkeypatch.setattr(app_module, "get_client", lambda: test_client.client)

        assert test_client.client.is_ready is False
        assert app.test_client().get("/configs").get_json() == {
            "temporary-feature-flag": True,
            "permanent-kill-switch": False,
            "integer-config": 10,
            "day-of-the-week-config": "Friday",
            "json-value-config": {},
        }


def test_get_client_creates_and_initializes_one_client_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[ConfigDirectorClient] = []

    def create_one(*args: object, **kwargs: object) -> ConfigDirectorClient:
        created.append(create_test_client(SAMPLE_VALUES).client)
        return created[-1]

    monkeypatch.setattr(configdirector_client, "_client", None)
    monkeypatch.setattr(configdirector_client, "create_client", create_one)
    try:
        first = configdirector_client.get_client()
        second = configdirector_client.get_client()

        assert created == [first]
        assert second is first
        assert first.is_ready is True
    finally:
        for client in created:
            client.close()


def test_an_unknown_route_returns_json(http: FlaskClient) -> None:
    response = http.get("/nope")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found. Try GET /configs"}
