from __future__ import annotations

import pytest

import configdirector.client

from helpers import TransportRecorder


@pytest.fixture(autouse=True)
def transports(monkeypatch: pytest.MonkeyPatch) -> TransportRecorder:
    recorder = TransportRecorder()
    monkeypatch.setattr(configdirector.client, "create_transport", recorder)
    return recorder
