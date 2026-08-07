from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import urllib3
from urllib3.exceptions import HTTPError, LocationValueError
from urllib3.response import BaseHTTPResponse

from .errors import ConfigDirectorConnectionError, ConfigDirectorValidationError

__all__ = ["MAX_RESPONSE_BYTES", "HttpResponse", "post"]

# Caps how much of a response body is held in memory. A config bundle is orders of magnitude
# smaller than this; anything larger is a misconfigured proxy or a hostile endpoint, and a
# server SDK must not let either exhaust the host's memory.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# Reconnection and polling cadence are the transport's job. urllib3 must not retry underneath
# it, or one logical poll would become several.
_NO_RETRIES = False

_pool = urllib3.PoolManager()


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def post(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    try:
        response = _pool.request(
            "POST",
            url,
            body=body,
            headers=dict(headers),
            timeout=urllib3.Timeout(connect=timeout, read=timeout),
            retries=_NO_RETRIES,
            # The body is read below against a size cap rather than loaded whole.
            preload_content=False,
        )
    except LocationValueError as error:
        # The URL itself is unusable, so every retry would fail identically.
        raise ConfigDirectorValidationError(f"The URL '{url}' is not usable: {error}") from error
    except HTTPError as error:
        # Refused, unresolved, timed out. All worth retrying.
        raise ConfigDirectorConnectionError(f"Connection failed with error: {error}.") from error

    # An error response is still a response: the caller reads the status and the body to decide
    # whether the failure is worth retrying.
    try:
        return HttpResponse(status=response.status, body=_read_text(response))
    finally:
        response.release_conn()


def _read_text(response: BaseHTTPResponse) -> str:
    payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ConfigDirectorConnectionError(
            f"The server response exceeded the {MAX_RESPONSE_BYTES} byte limit and was discarded"
        )
    # The server always sends UTF-8. Replacing rather than raising keeps a corrupted byte from
    # turning into an exception that reads nothing like the actual problem.
    return payload.decode("utf-8", errors="replace")
