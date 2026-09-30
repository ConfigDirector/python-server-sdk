from __future__ import annotations

import threading

from configdirector import ConnectionOptions, create_client
from configdirector._telemetry import TelemetryCollectorOptions
from configdirector._transport import PollingTransport, TransportOptions
from configdirector.client import _ConfigDirectorClient
from tests.helpers import TelemetryRecorder, TransportRecorder, bundle, config

SDK_KEY = "test-server-sdk-key"


def telemetry_thread_names() -> list[str]:
    return [thread.name for thread in threading.enumerate() if thread.name == "configdirector-telemetry"]


class TestTransportFactory:
    def test_receives_the_transport_options_and_supplies_the_transport(
        self, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        transports.initial_bundle = bundle(config("greeting", "hello"))
        client = _ConfigDirectorClient(
            SDK_KEY,
            connection=ConnectionOptions(timeout=7.5),
            transport_factory=transports,
            telemetry_factory=telemetry,
        )

        client.initialize()

        assert isinstance(transports.last.options, TransportOptions)
        assert transports.last.options.server_sdk_key == SDK_KEY
        assert transports.last.connect_timeouts == [7.5]
        assert client.get_value("greeting", "fallback") == "hello"


class TestTelemetryFactory:
    def test_receives_the_collector_options_and_supplies_the_collector(
        self, transports: TransportRecorder, telemetry: TelemetryRecorder
    ) -> None:
        client = _ConfigDirectorClient(SDK_KEY, transport_factory=transports, telemetry_factory=telemetry)
        client.initialize()

        client.get_value("missing", "fallback")
        client.close()

        assert isinstance(telemetry.last.options, TelemetryCollectorOptions)
        assert telemetry.last.options.server_sdk_key == SDK_KEY
        assert [evaluation.key for evaluation in telemetry.evaluations] == ["missing"]
        assert telemetry.last.closed is True

    def test_defaults_to_the_real_collector_whose_thread_ends_on_close(
        self, transports: TransportRecorder
    ) -> None:
        client = _ConfigDirectorClient(SDK_KEY, transport_factory=transports)

        assert telemetry_thread_names() == ["configdirector-telemetry"]
        client.close()

        assert telemetry_thread_names() == []


def test_create_client_builds_the_production_transport_and_collector() -> None:
    client = create_client(SDK_KEY, connection=ConnectionOptions(mode="polling"))

    assert isinstance(client._transport, PollingTransport)  # type: ignore[attr-defined]
    assert telemetry_thread_names() == ["configdirector-telemetry"]
    client.close()

    assert telemetry_thread_names() == []
