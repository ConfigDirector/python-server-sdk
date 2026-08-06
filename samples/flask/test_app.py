"""Smoke tests for the sample.

They double as an example of testing an application that reads configs: the client resolves to
the defaults you pass in when it cannot reach ConfigDirector, so handlers stay testable without
a network or a real SDK key.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

import app as app_module
from app import app


@pytest.fixture
def http() -> FlaskClient:
    return app.test_client()


def test_configs_returns_every_config(http: FlaskClient) -> None:
    response = http.get("/configs?id=user-123&plan=pro")

    assert response.status_code == 200
    assert response.get_json() == {
        "temporary-feature-flag": True,
        "permanent-kill-switch": False,
        "integer-config": 10,
        "day-of-the-week-config": "Friday",
        "json-value-config": {},
    }


def test_an_unknown_route_returns_json(http: FlaskClient) -> None:
    response = http.get("/nope")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found. Try GET /configs"}


def test_one_client_instance_serves_the_whole_process(http: FlaskClient) -> None:
    """The client is a singleton: importing it again hands back the same, live object."""
    from configdirector_client import client

    assert client is app_module.client

    http.get("/configs?id=first-caller")
    http.get("/configs?id=second-caller")

    # Requests neither replace the client nor tear it down.
    assert app_module.client is client
    assert client.closed is False


def test_configs_resolve_to_defaults_when_configdirector_is_unreachable(
    http: FlaskClient,
) -> None:
    # conftest.py points the SDK at an address nothing answers on, so this is the offline path.
    assert app_module.client.is_ready is False
    assert http.get("/configs").get_json()["temporary-feature-flag"] is True
