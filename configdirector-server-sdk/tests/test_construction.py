from __future__ import annotations

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
from configdirector.client import _DEFAULT_BASE_URL
from tests.helpers import ClientBuilder

SDK_KEY = "test-server-sdk-key"


def test_create_client_builds_a_client() -> None:
    client = create_client(SDK_KEY)

    assert isinstance(client, ConfigDirectorClient)
    assert client.is_ready is False
    assert client.closed is False
    client.close()


def test_the_implementation_satisfies_the_public_interface(build: ClientBuilder) -> None:
    # isinstance rather than issubclass: a runtime-checkable protocol with non-method members
    # supports one and not the other.
    assert isinstance(build(SDK_KEY), ConfigDirectorClient)


def test_accepts_every_option(build: ClientBuilder) -> None:
    client = build(
        SDK_KEY,
        metadata=Metadata(app_name="my-app", app_version="1.2.3"),
        connection=ConnectionOptions(mode="polling", polling_interval=90, timeout=5),
        telemetry=TelemetryOptions(event_queue_limit=100, flush_interval=10),
        hooks=ClientHooks(client_ready=lambda _event: None),
    )

    assert isinstance(client, ConfigDirectorClient)


def test_identifies_the_sdk(build: ClientBuilder) -> None:
    client = build(SDK_KEY)

    assert client._sdk_identity.sdk_name == "python-server-sdk"
    assert client._sdk_identity.sdk_version == __version__


@pytest.mark.parametrize("sdk_key", ["", "   "])
def test_rejects_a_blank_sdk_key(build: ClientBuilder, sdk_key: str) -> None:
    with pytest.raises(ConfigDirectorValidationError, match="server SDK key"):
        build(sdk_key)


def test_validation_errors_are_also_value_errors(build: ClientBuilder) -> None:
    with pytest.raises(ValueError, match="server SDK key"):
        build("")

    with pytest.raises(ConfigDirectorError, match="server SDK key"):
        build("")


def test_defaults_to_the_production_url(build: ClientBuilder) -> None:
    assert build(SDK_KEY)._base_url == _DEFAULT_BASE_URL


def test_accepts_a_custom_url(build: ClientBuilder) -> None:
    client = build(SDK_KEY, connection=ConnectionOptions(url="https://proxy.example.com"))

    assert client._base_url == "https://proxy.example.com"


@pytest.mark.parametrize("url", ["not-a-url", "://missing-scheme", "https://"])
def test_rejects_an_invalid_url(build: ClientBuilder, url: str) -> None:
    with pytest.raises(ConfigDirectorValidationError, match="Invalid base URL"):
        build(SDK_KEY, connection=ConnectionOptions(url=url))
