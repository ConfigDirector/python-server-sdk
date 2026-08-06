from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .types import ResponseStream

__all__ = ["StreamRequest", "open_stream", "set_read_timeout"]


@dataclass(frozen=True, slots=True)
class StreamRequest:
    url: str
    method: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float | None
    follow_redirects: bool


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> urllib.request.Request | None:
        # Returning None leaves the 3xx to surface as a status rather than being followed.
        return None


_FOLLOWING = urllib.request.build_opener()
_NOT_FOLLOWING = urllib.request.build_opener(_NoRedirectHandler)


def open_stream(request: StreamRequest) -> ResponseStream:
    prepared = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method,
    )
    opener = _FOLLOWING if request.follow_redirects else _NOT_FOLLOWING
    try:
        return cast(ResponseStream, opener.open(prepared, timeout=request.timeout))
    except urllib.error.HTTPError as error:
        # An error response is still a response: the caller reads its status and decides whether
        # to reconnect, exactly as it would for a 2xx.
        return cast(ResponseStream, error)


def set_read_timeout(response: ResponseStream, seconds: float) -> bool:
    """Bound how long a single read may block, so the reader can notice it has been stopped.

    Closing a response from another thread cannot do this: the reader holds the buffered
    reader's lock while it waits, so close() would block until the read completed. Returns
    False when the socket is not reachable, which leaves reads blocking until data arrives.
    """
    raw = getattr(getattr(response, "fp", None), "raw", None)
    socket_ = getattr(raw, "_sock", None)
    if socket_ is None:
        return False
    try:
        socket_.settimeout(seconds)
    except OSError:
        return False
    return True
