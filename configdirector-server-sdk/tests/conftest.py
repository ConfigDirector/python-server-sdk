from __future__ import annotations

import pytest

from tests.helpers import ClientBuilder, TelemetryRecorder, TransportRecorder, client_builder


@pytest.fixture
def transports() -> TransportRecorder:
    return TransportRecorder()


@pytest.fixture
def telemetry() -> TelemetryRecorder:
    """Stands in for the real collector, so that constructing a client neither starts a flush
    thread nor reaches the network."""
    return TelemetryRecorder()


@pytest.fixture
def build(transports: TransportRecorder, telemetry: TelemetryRecorder) -> ClientBuilder:
    return client_builder(transports, telemetry)
