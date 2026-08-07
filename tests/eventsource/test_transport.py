from __future__ import annotations

import http.server
import threading
import time
from collections.abc import Callable, Iterator
from typing import cast

import pytest
from urllib3.response import BaseHTTPResponse

from configdirector._eventsource import (
    EventSourceClient,
    EventSourceMessage,
    ReadyState,
    ReconnectionState,
)
from configdirector._eventsource.transport import _Stream

from .helpers import wait_for

Handler = Callable[[http.server.BaseHTTPRequestHandler], None]


class _Server:
    def __init__(self, handle: Handler) -> None:
        outer = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                outer.paths.append(self.path)
                handle(self)

            do_POST = do_GET  # noqa: N815 - the name is fixed by BaseHTTPRequestHandler

            def log_message(self, *args: object) -> None:
                pass

        self.paths: list[str] = []
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        # Handlers that are still sleeping must not hold up server_close().
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port!s}/sse"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def serve() -> Iterator[Callable[[Handler], _Server]]:
    servers: list[_Server] = []

    def start(handle: Handler) -> _Server:
        server = _Server(handle)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _collect_status(sink: list[int | None]) -> Callable[[ReconnectionState], bool]:
    def handler(state: ReconnectionState) -> bool:
        sink.append(state.status)
        return False

    return handler


def send_headers(request: http.server.BaseHTTPRequestHandler, status: int = 200) -> None:
    request.send_response(status)
    request.send_header("Content-Type", "text/event-stream")
    request.send_header("Cache-Control", "no-cache")
    request.send_header("Connection", "close")
    request.end_headers()


def test_events_arrive_as_the_server_sends_them(serve: Callable[[Handler], _Server]) -> None:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        send_headers(request)
        for index in range(3):
            request.wfile.write(f"data: event-{index}\n\n".encode())
            request.wfile.flush()
            time.sleep(0.05)

    server = serve(handle)
    arrivals: list[tuple[str, float]] = []
    started = time.monotonic()
    client = EventSourceClient(
        server.url,
        on_message=lambda message: arrivals.append((message.data, time.monotonic() - started)),
        should_reconnect=lambda state: False,
    )

    try:
        client.connect()
        assert wait_for(lambda: len(arrivals) == 3)
    finally:
        client.close()

    assert [data for data, _ in arrivals] == ["event-0", "event-1", "event-2"]
    # Buffering would deliver all three at the end; each should land while the server is still
    # writing the next.
    assert arrivals[0][1] < arrivals[2][1] - 0.02


def test_close_interrupts_a_read_that_is_already_blocked(
    serve: Callable[[Handler], _Server],
) -> None:
    release = threading.Event()

    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        send_headers(request)
        request.wfile.write(b"data: hello\n\n")
        request.wfile.flush()
        release.wait(10)

    server = serve(handle)
    connected = threading.Event()
    client = EventSourceClient(server.url, on_connect=connected.set)

    try:
        client.connect()
        assert connected.wait(timeout=5)

        started = time.monotonic()
        client.close()
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert client.ready_state is ReadyState.CLOSED
    # Without closing the response, this would block until the server let go.
    assert elapsed < 2.0


def test_a_server_error_status_is_reported_without_an_error(
    serve: Callable[[Handler], _Server],
) -> None:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(503)
        request.send_header("Content-Length", "0")
        request.end_headers()

    server = serve(handle)
    statuses: list[int | None] = []
    errors: list[BaseException] = []
    client = EventSourceClient(
        server.url,
        on_error=errors.append,
        should_reconnect=_collect_status(statuses),
    )

    try:
        client.connect()
        assert wait_for(lambda: statuses == [503])
    finally:
        client.close()

    assert errors == []


def test_no_content_disconnects_without_retrying(serve: Callable[[Handler], _Server]) -> None:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(204)
        request.send_header("Content-Length", "0")
        request.end_headers()

    server = serve(handle)
    disconnected = threading.Event()
    client = EventSourceClient(server.url, on_disconnect=disconnected.set)

    try:
        client.connect()
        assert disconnected.wait(timeout=5)
    finally:
        client.close()

    assert len(server.paths) == 1
    assert client.ready_state is ReadyState.CLOSED


def test_a_redirect_is_followed_by_default(serve: Callable[[Handler], _Server]) -> None:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        if request.path == "/sse":
            request.send_response(302)
            request.send_header("Location", "/moved")
            request.send_header("Content-Length", "0")
            request.end_headers()
            return
        send_headers(request)
        request.wfile.write(b"data: redirected\n\n")
        request.wfile.flush()

    server = serve(handle)
    received: list[EventSourceMessage] = []
    client = EventSourceClient(server.url, on_message=received.append, should_reconnect=lambda state: False)

    try:
        client.connect()
        assert wait_for(lambda: len(received) == 1)
    finally:
        client.close()

    assert received[0].data == "redirected"
    assert server.paths == ["/sse", "/moved"]


def test_a_redirect_is_a_status_when_following_is_disabled(
    serve: Callable[[Handler], _Server],
) -> None:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(302)
        request.send_header("Location", "/moved")
        request.send_header("Content-Length", "0")
        request.end_headers()

    server = serve(handle)
    statuses: list[int | None] = []
    client = EventSourceClient(
        server.url,
        follow_redirects=False,
        should_reconnect=_collect_status(statuses),
    )

    try:
        client.connect()
        assert wait_for(lambda: len(statuses) == 1)
    finally:
        client.close()

    assert statuses == [302]
    assert server.paths == ["/sse"]


def test_a_multibyte_character_split_across_reads_survives(
    serve: Callable[[Handler], _Server],
) -> None:
    payload = "héllo wörld ✓"

    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        send_headers(request)
        encoded = f"data: {payload}\n\n".encode()
        for index in range(len(encoded)):
            request.wfile.write(encoded[index : index + 1])
            request.wfile.flush()
        time.sleep(0.05)

    server = serve(handle)
    received: list[EventSourceMessage] = []
    client = EventSourceClient(server.url, on_message=received.append, should_reconnect=lambda state: False)

    try:
        client.connect()
        assert wait_for(lambda: len(received) == 1)
    finally:
        client.close()

    assert received[0].data == payload


class TestStreamClose:
    """The teardown order in `_Stream.close()`, which no live test can pin on a POSIX runner.

    A reader parked in `recv()` holds the response's buffered-reader lock for as long as it is
    parked. `shutdown()` wakes it on POSIX, so the order is invisible there; Winsock leaves it
    parked, and closing the response then blocks on that lock forever. Only closing the socket
    cancels the pending read, so the connection has to go first.
    """

    class _Connection:
        def __init__(self, calls: list[str]) -> None:
            self._calls = calls

        def close(self) -> None:
            self._calls.append("connection.close")

    class _Response:
        status = 200

        def __init__(self, calls: list[str], *, shutdown_error: Exception | None = None) -> None:
            self._calls = calls
            self._shutdown_error = shutdown_error
            self._connection = TestStreamClose._Connection(calls)

        def shutdown(self) -> None:
            self._calls.append("shutdown")
            if self._shutdown_error is not None:
                raise self._shutdown_error

        def close(self) -> None:
            self._calls.append("response.close")

    def test_the_socket_is_dropped_before_the_response_is_closed(self) -> None:
        calls: list[str] = []
        _Stream(cast(BaseHTTPResponse, self._Response(calls))).close()

        assert calls == ["shutdown", "connection.close", "response.close"]

    def test_a_refused_shutdown_does_not_skip_the_rest_of_the_teardown(self) -> None:
        # urllib3 raises when there is no longer a socket to shut down, which is exactly the
        # case where nothing is parked on one. The response still has to be closed.
        calls: list[str] = []
        response = self._Response(calls, shutdown_error=ValueError("no socket"))
        _Stream(cast(BaseHTTPResponse, response)).close()

        assert calls == ["shutdown", "connection.close", "response.close"]

    def test_a_response_without_a_connection_is_still_closed(self) -> None:
        # Guards the getattr fallback: a urllib3 that renames `_connection` must degrade to the
        # old behaviour rather than raising out of close().
        calls: list[str] = []

        class Bare:
            status = 200

            def shutdown(self) -> None:
                calls.append("shutdown")

            def close(self) -> None:
                calls.append("response.close")

        _Stream(cast(BaseHTTPResponse, Bare())).close()

        assert calls == ["shutdown", "response.close"]
