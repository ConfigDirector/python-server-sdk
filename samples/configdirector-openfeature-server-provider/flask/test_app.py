"""Smoke tests for the sample.

They double as an example of testing an application that reads flags through OpenFeature: when
ConfigDirector cannot be reached every flag resolves to the default you pass in, so handlers stay
testable without a network or a real SDK key.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient
from openfeature import api

import app as app_module
from app import app
from openfeature_client import provider


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


def test_details_explain_why_a_default_was_served(http: FlaskClient) -> None:
    details = http.get("/configs/temporary-feature-flag").get_json()

    assert details["value"] is False
    assert details["reason"] == "ERROR"
    assert details["error_code"] == "PROVIDER_NOT_READY"


def test_an_unknown_route_returns_json(http: FlaskClient) -> None:
    response = http.get("/nope")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found. Try GET /configs"}


def test_one_provider_serves_the_whole_process(http: FlaskClient) -> None:
    http.get("/configs?id=first-caller")
    http.get("/configs?id=second-caller")

    assert app_module.client.provider is provider
    assert api.get_provider_metadata().name == "ConfigDirectorProvider"
