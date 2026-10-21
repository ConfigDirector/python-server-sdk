from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args
from urllib.parse import urlparse

from ._validation import validated_server_sdk_key
from .errors import ConfigDirectorValidationError
from .types import ConfigValue, ConnectionMode, ConnectionOptions

__all__ = [
    "Connect",
    "InCodeDefaults",
    "InlineValues",
    "LiveConnectionMode",
    "OfflineFile",
    "OfflineSource",
    "RejectedSource",
    "StayOffline",
    "plan_connection",
]

_DEFAULT_BASE_URL = "https://server-sdk-api.configdirector.com"

LiveConnectionMode = Literal["streaming", "polling"]


@dataclass(frozen=True, slots=True)
class InCodeDefaults:
    pass


@dataclass(frozen=True, slots=True)
class OfflineFile:
    path: str | os.PathLike[str]


@dataclass(frozen=True, slots=True)
class InlineValues:
    values: Mapping[str, ConfigValue]


@dataclass(frozen=True, slots=True)
class RejectedSource:
    message: str


OfflineSource = InCodeDefaults | OfflineFile | InlineValues | RejectedSource


@dataclass(frozen=True, slots=True)
class Connect:
    mode: LiveConnectionMode
    server_sdk_key: str
    base_url: str


@dataclass(frozen=True, slots=True)
class StayOffline:
    source: OfflineSource


ConnectionPlan = Connect | StayOffline


def plan_connection(server_sdk_key: str | None, connection: ConnectionOptions) -> ConnectionPlan:
    if connection.mode == "offline":
        return StayOffline(source=_offline_source_of(connection))
    mode = _live_mode_of(connection.mode)
    live_server_sdk_key = validated_server_sdk_key(server_sdk_key)
    if connection.file is not None or connection.values is not None:
        return StayOffline(
            source=RejectedSource(
                message=f"The connection options 'file' and 'values' apply only when the connection mode is "
                f"'offline', but the mode is '{mode}'."
            )
        )
    return Connect(
        mode=mode,
        server_sdk_key=live_server_sdk_key,
        base_url=_base_url_of(connection.url),
    )


def _live_mode_of(mode: object) -> LiveConnectionMode:
    match mode:
        case "streaming" | "polling":
            return mode
        case _:
            raise ConfigDirectorValidationError(
                f"Unknown connection mode '{mode}'. Expected one of: "
                f"{', '.join(sorted(get_args(ConnectionMode)))}."
            )


def _offline_source_of(connection: ConnectionOptions) -> OfflineSource:
    if connection.file is not None and connection.values is not None:
        return RejectedSource(message="An offline connection takes either 'file' or 'values', not both.")
    if connection.file is not None:
        return OfflineFile(path=connection.file)
    if connection.values is not None:
        return InlineValues(values=connection.values)
    return InCodeDefaults()


def _base_url_of(url: str | None) -> str:
    if url is None:
        return _DEFAULT_BASE_URL

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigDirectorValidationError(
            f"Invalid base URL '{url}'. The URL must include a scheme and a host."
        )
    return url
