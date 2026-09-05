from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urljoin

from .._bundle import ConfigBundle
from .._http import HttpClient
from .._version import _SDK_NAME, __version__
from ..errors import ConfigDirectorConnectionError
from ..types import ConfigDirectorLogger

__all__ = [
    "DEFAULT_POLLING_INTERVAL",
    "MIN_POLLING_INTERVAL",
    "REQUEST_HEADERS",
    "Transport",
    "TransportOptions",
    "fatal_status_error",
    "is_fatal_status",
    "json_body",
    "resolve",
]

# Every request identifies the SDK by name and version. Left to itself urllib sends
# "Python-urllib/3.x", which bot-protection layers in front of the API reject before the request
# ever reaches the origin — surfacing as a 403 that looks exactly like a rejected SDK key.
_USER_AGENT = f"{_SDK_NAME}/{__version__}"

DEFAULT_POLLING_INTERVAL = 300.0
MIN_POLLING_INTERVAL = 60.0

# A read-only view, because one dict is shared by every request the SDK makes: editing it in
# place would silently change the headers of the transport and the telemetry reporter alike.
REQUEST_HEADERS: Mapping[str, str] = MappingProxyType(
    {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
)


@dataclass(frozen=True, slots=True)
class TransportOptions:
    server_sdk_key: str
    base_url: str
    meta_context: Mapping[str, str]
    logger: ConfigDirectorLogger
    on_bundle: Callable[[ConfigBundle], None]
    # Owned by the client, and shared with the telemetry reporter: both talk to the same host.
    http: HttpClient = field(default_factory=HttpClient)
    polling_interval: float = DEFAULT_POLLING_INTERVAL


class Transport(Protocol):
    # Blocks until config state has been received, the connection has failed unrecoverably, or
    # `timeout` seconds have passed — whichever happens first. Raises only on an unrecoverable
    # failure; a transient one leaves the transport retrying in the background.
    def connect(self, timeout: float) -> None: ...

    @property
    def is_connected(self) -> bool: ...

    def close(self) -> None: ...


def resolve(base_url: str, path: str) -> str:
    # The trailing slash is what keeps urljoin from treating the last segment of a proxy base
    # URL as a file name and dropping it.
    return urljoin(base_url if base_url.endswith("/") else f"{base_url}/", path)


def json_body(payload: Mapping[str, Any]) -> bytes:
    return json.dumps({key: value for key, value in payload.items() if value is not None}).encode("utf-8")


def is_fatal_status(status: int | None) -> bool:
    # A 4xx means the request itself is wrong — a revoked SDK key, a bad URL — and repeating it
    # unchanged will only fail the same way.
    return status is not None and 400 <= status < 500


def fatal_status_error(status: int | None, detail: str | None = None) -> ConfigDirectorConnectionError:
    headline = f"Connection failed with status: {status if status is not None else 'unknown'}"
    body = f" ({detail.strip()})" if detail and detail.strip() else ""
    return ConfigDirectorConnectionError(
        f"{headline}{body}. This is an unrecoverable error, retry attempts will be ignored.",
        status,
    )
