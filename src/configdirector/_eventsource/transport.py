from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import urllib3
from urllib3.exceptions import ProtocolError, ReadTimeoutError
from urllib3.response import BaseHTTPResponse

from .errors import StreamClosedError, StreamStalledError
from .types import ResponseStream

__all__ = ["StreamRequest", "open_stream"]

# Reconnection, including its backoff, belongs to EventSourceClient. urllib3 must not quietly
# retry underneath it, or a single logical attempt would become several.
_NO_RETRIES = 0

# Only relevant when the caller opted into redirects; urllib3 needs a bound either way.
_MAX_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class StreamRequest:
    url: str
    method: str
    headers: Mapping[str, str]
    body: bytes | None
    # Applies to establishing the connection only. Once the stream is open it must not bound
    # how long the SDK waits for the next event.
    connect_timeout: float | None
    # How long a stream may stay silent before it is considered dead. None means indefinitely,
    # which is what a stream fed by server-sent keepalives wants.
    read_timeout: float | None
    follow_redirects: bool


_pool = urllib3.PoolManager()


class _Stream:
    """Adapts a urllib3 response to `ResponseStream`, translating its errors into ours.

    Keeping the translation here is what lets `EventSourceClient` stay transport-agnostic: it
    only ever sees this SDK's own exception types, so a caller can supply a different transport
    without urllib3 semantics leaking into the reader.
    """

    def __init__(self, response: BaseHTTPResponse) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status

    def chunks(self, amount: int) -> Iterator[bytes]:
        try:
            while True:
                # read1() hands back whatever has arrived. stream() is the obvious choice here
                # and the wrong one: on a response delimited by the connection closing rather
                # than by chunked framing it waits for `amount` bytes, so events would sit in a
                # buffer until the server hung up.
                data = self._response.read1(amount)
                if not data:
                    return
                yield data
        except ReadTimeoutError as error:
            raise StreamStalledError(f"The stream went silent: {error}") from error
        except ProtocolError as error:
            # The peer went away, or close() cancelled the read from another thread. Both mean
            # this response is finished; whether to reconnect is the reader's decision.
            raise StreamClosedError(f"The response stream ended: {error}") from error

    def cancel(self) -> None:
        # Deliberately does not close the response. A reader parked in recv() holds the
        # buffered reader's lock until it returns, and closing the response takes that same
        # lock, so doing it here would park the caller behind the read it is trying to end.
        # Both steps below only touch the socket.
        with contextlib.suppress(ValueError, RuntimeError, OSError):
            # urllib3's supported way to end a read from another thread. It objects when there
            # is no longer a socket to shut down, which is the case where nothing is parked.
            self._response.shutdown()
        _close_socket(self._response)

    def close(self) -> None:
        self._response.close()


def _close_socket(response: BaseHTTPResponse) -> None:
    """Closes the connection's socket for real, cancelling any read parked on it.

    shutdown() is enough on POSIX, where it wakes the parked recv(). Winsock only disallows
    *subsequent* receives, so on Windows the reader stays in the kernel; closesocket() is what
    documents itself as cancelling a pending blocking call, and it is the only thing that does.

    Neither `HTTPConnection.close()` nor `socket.close()` reaches closesocket() here: http.client
    holds the socket through `makefile()`, which pins `_io_refs` above zero, and `socket.close()`
    only flags the socket and defers the real close to whoever drops the last file object -- the
    buffered reader, whose teardown is exactly what is blocked. `_real_close()` is the unguarded
    form, and it is private, so this stays optional: if it moves, this degrades to
    shutdown()-only rather than raising out of cancel().
    """
    real_close = getattr(_socket_of(response), "_real_close", None)
    if real_close is None:
        return
    with contextlib.suppress(Exception):
        real_close()


def _socket_of(response: BaseHTTPResponse) -> object | None:
    """The live socket behind a streaming response, or None if it cannot be reached.

    Not `response._connection.sock`: urllib3 hands the socket to the response and leaves the
    connection's own reference set to None, so that route is always a dead end. The socket is
    reachable only through the response's file object, as
    ``http.client response -> BufferedReader -> SocketIO -> socket``.

    Every step is private to urllib3, http.client, or socket, which is why this returns None
    instead of raising when one of them moves.
    """
    buffered = getattr(getattr(response, "_fp", None), "fp", None)
    return getattr(getattr(buffered, "raw", None), "_sock", None)


def open_stream(request: StreamRequest) -> ResponseStream:
    response = _pool.request(
        request.method,
        request.url,
        body=request.body,
        headers=dict(request.headers),
        timeout=urllib3.Timeout(connect=request.connect_timeout, read=request.read_timeout),
        # The reader consumes the body incrementally; preloading it would block until the
        # server closed the stream, which for SSE is never.
        preload_content=False,
        redirect=request.follow_redirects,
        retries=urllib3.Retry(
            total=None,
            connect=_NO_RETRIES,
            read=_NO_RETRIES,
            status=_NO_RETRIES,
            other=_NO_RETRIES,
            redirect=_MAX_REDIRECTS if request.follow_redirects else _NO_RETRIES,
            # An error response is still a response: the reader inspects the status and decides
            # whether to reconnect, exactly as it would for a 2xx.
            raise_on_status=False,
            raise_on_redirect=False,
        ),
    )
    return _Stream(response)
