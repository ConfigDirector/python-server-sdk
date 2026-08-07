from __future__ import annotations

import inspect

import pytest

from configdirector import (
    ClientHooks,
    ConfigDirectorClient,
    ConfigDirectorError,
    ConfigDirectorValidationError,
    ConnectionOptions,
    Metadata,
    TelemetryOptions,
    __version__,
    create_client,
)
from configdirector.client import DEFAULT_BASE_URL

SDK_KEY = "test-server-sdk-key"


def test_the_client_is_constructed_directly() -> None:
    client = ConfigDirectorClient(SDK_KEY)

    assert client.is_ready is False
    assert client.closed is False


def test_create_client_is_equivalent_to_the_constructor() -> None:
    client = create_client(SDK_KEY)

    assert isinstance(client, ConfigDirectorClient)
    assert client.is_ready is False


def test_create_client_takes_every_constructor_option() -> None:
    # create_client documents itself as equivalent to the constructor, so an option added to one
    # and not the other is a defect rather than a design choice.
    assert list(inspect.signature(create_client).parameters) == list(
        inspect.signature(ConfigDirectorClient).parameters
    )


def test_accepts_every_option() -> None:
    client = ConfigDirectorClient(
        SDK_KEY,
        metadata=Metadata(app_name="my-app", app_version="1.2.3"),
        connection=ConnectionOptions(mode="polling", polling_interval=15, timeout=5),
        telemetry=TelemetryOptions(event_queue_limit=100, flush_interval=10),
        hooks=ClientHooks(client_ready=lambda _event: None),
    )

    assert isinstance(client, ConfigDirectorClient)


def test_identifies_the_sdk() -> None:
    client = ConfigDirectorClient(SDK_KEY)

    assert client._sdk_name == "python-server-sdk"
    assert client._sdk_version == __version__


@pytest.mark.parametrize("sdk_key", ["", "   "])
def test_rejects_a_blank_sdk_key(sdk_key: str) -> None:
    with pytest.raises(ConfigDirectorValidationError, match="server SDK key"):
        ConfigDirectorClient(sdk_key)


def test_validation_errors_are_also_value_errors() -> None:
    with pytest.raises(ValueError, match="server SDK key"):
        ConfigDirectorClient("")

    with pytest.raises(ConfigDirectorError, match="server SDK key"):
        ConfigDirectorClient("")


def test_defaults_to_the_production_url() -> None:
    assert ConfigDirectorClient(SDK_KEY)._base_url == DEFAULT_BASE_URL


def test_accepts_a_custom_url() -> None:
    client = ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(url="https://proxy.example.com"))

    assert client._base_url == "https://proxy.example.com"


@pytest.mark.parametrize("url", ["not-a-url", "://missing-scheme", "https://"])
def test_rejects_an_invalid_url(url: str) -> None:
    with pytest.raises(ConfigDirectorValidationError, match="Invalid base URL"):
        ConfigDirectorClient(SDK_KEY, connection=ConnectionOptions(url=url))
