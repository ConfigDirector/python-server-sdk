from __future__ import annotations

import http.server
import threading
from collections.abc import Callable, Iterator

import pytest

from configdirector._eventsource import EventSourceClient, EventSourceMessage

from .helpers import wait_for
from helpers import create_stubbed_logger

Handler = Callable[[http.server.BaseHTTPRequestHandler, threading.Event], None]

logger = create_stubbed_logger()


class _Server:
    """Serves one chunked `text/event-stream` response per connection."""

    def __init__(self, handle: Handler) -> None:
        outer = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                outer.connections += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                # Chunked framing is the part the fakes cannot reproduce.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                handle(self, outer.stop)

            def log_message(self, *args: object) -> None:
                pass

        self.connections = 0
        self.stop = threading.Event()
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        self._httpd.daemon_threads = True
        threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port!s}/sse"

    def close(self) -> None:
        self.stop.set()
        self._httpd.shutdown()
        self._httpd.server_close()


def write_chunk(request: http.server.BaseHTTPRequestHandler, payload: str) -> None:
    encoded = payload.encode("utf-8")
    request.wfile.write(f"{len(encoded):X}\r\n".encode())
    request.wfile.write(encoded + b"\r\n")
    request.wfile.flush()


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


@pytest.fixture
def clients() -> Iterator[list[EventSourceClient]]:
    created: list[EventSourceClient] = []
    yield created
    for client in created:
        client.close()


class TestIdleStream:
    # A stream that is merely quiet must stay open. Two separate defects used to break this: a
    # 1s socket timeout used as a poll interval, and a connect timeout that urllib left on the
    # socket for the life of the connection. Both dropped an idle stream and reconnected in a
    # loop, forever.
    def test_survives_an_idle_period_longer_than_the_poll_interval(
        self, serve: Callable[[Handler], _Server], clients: list[EventSourceClient]
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler, stop: threading.Event) -> None:
            write_chunk(request, "data: first\n\n")
            # Longer than the reader's 1s poll, which is what used to break the stream.
            stop.wait(2.5)
            write_chunk(request, "data: second\n\n")
            stop.wait(5)

        server = serve(handle)
        received: list[str] = []
        client = EventSourceClient(
            server.url,
            method="POST",
            on_message=lambda message: received.append(message.data),
            logger=logger,
        )
        clients.append(client)
        client.connect()

        assert wait_for(lambda: len(received) >= 2, timeout=10), f"only received {received}"
        assert received == ["first", "second"]
        # The decisive assertion: both events arrived over a single connection.
        assert server.connections == 1

    def test_does_not_reconnect_while_the_stream_is_merely_quiet(
        self, serve: Callable[[Handler], _Server], clients: list[EventSourceClient]
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler, stop: threading.Event) -> None:
            write_chunk(request, "data: hello\n\n")
            stop.wait(10)

        server = serve(handle)
        received: list[EventSourceMessage] = []
        client = EventSourceClient(server.url, method="POST", on_message=received.append, logger=logger)
        clients.append(client)
        client.connect()

        assert wait_for(lambda: len(received) >= 1)
        # Stay quiet across several poll intervals; nothing should reconnect.
        assert not wait_for(lambda: server.connections > 1, timeout=3.5)
        assert server.connections == 1


class TestClosePromptness:
    # Blocking reads are only safe if close() can still interrupt one in flight.
    def test_close_returns_promptly_while_a_read_is_blocked(
        self, serve: Callable[[Handler], _Server], clients: list[EventSourceClient]
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler, stop: threading.Event) -> None:
            write_chunk(request, "data: hello\n\n")
            stop.wait(30)

        server = serve(handle)
        received: list[EventSourceMessage] = []
        client = EventSourceClient(server.url, method="POST", on_message=received.append, logger=logger)
        clients.append(client)
        client.connect()
        assert wait_for(lambda: len(received) >= 1)

        closed = threading.Event()

        def close_it() -> None:
            client.close()
            closed.set()

        threading.Thread(target=close_it, daemon=True).start()

        assert closed.wait(5), "close() blocked behind an in-flight read"
