"""Tests for the sample, written the way an application reading flags through OpenFeature tests
itself: by swapping the provider.

The application reads its OpenFeature client through ``get_client()``, which registers the
ConfigDirector provider on first use. Each test registers OpenFeature's own ``InMemoryProvider``
instead and points ``get_client`` at the OpenFeature API, so nothing from ConfigDirector is
involved, no network is used, and no SDK key is needed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from openfeature import api
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

import app as app_module
from app import app

SAMPLE_FLAGS = {
    "temporary-feature-flag": InMemoryFlag("off", {"on": True, "off": False}),
    "permanent-kill-switch": InMemoryFlag("on", {"on": True, "off": False}),
    "integer-config": InMemoryFlag("forty-two", {"forty-two": 42}),
    "day-of-the-week-config": InMemoryFlag("tuesday", {"tuesday": "Tuesday"}),
    "json-value-config": InMemoryFlag("greeting", {"greeting": {"greeting": "hello"}}),
}


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    api.set_provider_and_wait(InMemoryProvider(SAMPLE_FLAGS))
    monkeypatch.setattr(app_module, "get_client", api.get_client)
    yield app.test_client()
    api.shutdown()


def test_configs_returns_the_value_of_every_flag(http: FlaskClient) -> None:
    response = http.get("/configs?id=user-123&plan=pro")

    assert response.status_code == 200
    assert response.get_json() == {
        "temporary-feature-flag": False,
        "permanent-kill-switch": True,
        "integer-config": 42,
        "day-of-the-week-config": "Tuesday",
        "json-value-config": {"greeting": "hello"},
    }


def test_a_flag_the_provider_does_not_know_falls_back_to_the_default(http: FlaskClient) -> None:
    api.set_provider_and_wait(InMemoryProvider({}))

    assert http.get("/configs").get_json()["day-of-the-week-config"] == "Friday"


def test_details_report_the_variant_and_reason(http: FlaskClient) -> None:
    details = http.get("/configs/permanent-kill-switch").get_json()

    assert details["value"] is True
    assert details["variant"] == "on"
    assert details["reason"] == "STATIC"
    assert details["error_code"] is None


def test_details_explain_why_a_default_was_served(http: FlaskClient) -> None:
    details = http.get("/configs/no-such-flag").get_json()

    assert details["value"] is False
    assert details["reason"] == "ERROR"
    assert details["error_code"] == "FLAG_NOT_FOUND"


def test_an_unknown_route_returns_json(http: FlaskClient) -> None:
    response = http.get("/nope")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found. Try GET /configs"}
