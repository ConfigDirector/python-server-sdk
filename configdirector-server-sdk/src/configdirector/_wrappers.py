from __future__ import annotations

import importlib.metadata
from enum import Enum

from ._version import SdkIdentity
from .client import _ConfigDirectorClient
from .errors import ConfigDirectorTypeError
from .types import (
    ClientHooks,
    ConfigDirectorClient,
    ConfigDirectorLogger,
    ConnectionOptions,
    Metadata,
    TelemetryOptions,
)

__all__ = ["Wrapper", "create_wrapped_client"]

_DEVELOPMENT_VERSION = "0.0.0-dev"


class Wrapper(Enum):
    OPENFEATURE_SERVER_PROVIDER = (
        "python-openfeature-server-provider",
        "configdirector-openfeature-server-provider",
    )

    def __init__(self, sdk_name: str, distribution: str) -> None:
        self.sdk_name = sdk_name
        self.distribution = distribution

    def identity(self) -> SdkIdentity:
        try:
            version = importlib.metadata.version(self.distribution)
        except importlib.metadata.PackageNotFoundError:
            version = _DEVELOPMENT_VERSION
        return SdkIdentity(sdk_name=self.sdk_name, sdk_version=version)


def create_wrapped_client(
    wrapper: Wrapper,
    server_sdk_key: str,
    *,
    metadata: Metadata | None = None,
    connection: ConnectionOptions | None = None,
    logger: ConfigDirectorLogger | None = None,
    log_level: int | str | None = None,
    telemetry: TelemetryOptions | None = None,
    hooks: ClientHooks | None = None,
) -> ConfigDirectorClient:
    if not isinstance(wrapper, Wrapper):
        raise ConfigDirectorTypeError(
            f"Invalid wrapper {wrapper!r}. The wrapper must be a known wrapper of this SDK, one of "
            f"{', '.join(member.name for member in Wrapper)}."
        )

    return _ConfigDirectorClient(
        server_sdk_key,
        metadata=metadata,
        connection=connection,
        logger=logger,
        log_level=log_level,
        telemetry=telemetry,
        hooks=hooks,
        sdk_identity=wrapper.identity(),
    )
