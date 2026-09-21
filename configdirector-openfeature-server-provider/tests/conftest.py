from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from configdirector import ConnectionOptions
from openfeature import api

from configdirector_openfeature import ConfigDirectorProvider
from tests.helpers import FakeConfigDirectorServer

ServerFactory = Callable[..., FakeConfigDirectorServer]
ProviderFactory = Callable[..., ConfigDirectorProvider]


@pytest.fixture
def serve() -> Iterator[ServerFactory]:
    servers: list[FakeConfigDirectorServer] = []

    def start(*configs: dict[str, Any]) -> FakeConfigDirectorServer:
        server = FakeConfigDirectorServer(*configs)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def provide() -> Iterator[ProviderFactory]:
    providers: list[ConfigDirectorProvider] = []

    def create(
        server: FakeConfigDirectorServer, mode: str = "polling", timeout: float = 5.0, **options: Any
    ) -> ConfigDirectorProvider:
        provider = ConfigDirectorProvider(
            "sdk-key",
            connection=ConnectionOptions(mode=mode, url=server.url, timeout=timeout),  # type: ignore[arg-type]
            **options,
        )
        providers.append(provider)
        return provider

    yield create
    api.clear_providers()
    for provider in providers:
        provider.shutdown()
