from __future__ import annotations

import pytest

import configdirector.client
from tests.helpers import TelemetryRecorder, TransportRecorder


@pytest.fixture(autouse=True)
def transports(monkeypatch: pytest.MonkeyPatch) -> TransportRecorder:
    recorder = TransportRecorder()
    monkeypatch.setattr(configdirector.client, "create_transport", recorder)
    return recorder


@pytest.fixture(autouse=True)
def telemetry(monkeypatch: pytest.MonkeyPatch) -> TelemetryRecorder:
    """Stands in for the real collector, so that constructing a client neither starts a flush
    thread nor reaches the network."""
    recorder = TelemetryRecorder()
    monkeypatch.setattr(configdirector.client, "TelemetryCollector", recorder)
    return recorder
