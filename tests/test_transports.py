from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from configdirector._bundle import ConfigBundle
from configdirector._transport import (
    OneTimeTransport,
    PollingTransport,
    StreamingTransport,
    TransportOptions,
)
from configdirector.errors import ConfigDirectorConnectionError
from tests.helpers import RecordingLogger, wait_for

Handler = Callable[[http.server.BaseHTTPRequestHandler], None]


class _Server:
    def __init__(self, handle: Handler) -> None:
        outer = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append(json.loads(self.rfile.read(length) or b"{}"))
                outer.paths.append(self.path)
                outer.headers.append(dict(self.headers))
                handle(self)

            def log_message(self, *args: object) -> None:
                pass

        self.paths: list[str] = []
        self.requests: list[Any] = []
        self.headers: list[dict[str, str]] = []
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        # Handlers still in flight must not hold up server_close().
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port!s}"

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


class Sink:
    def __init__(self) -> None:
        self.bundles: list[ConfigBundle] = []

    def __call__(self, bundle: ConfigBundle) -> None:
        self.bundles.append(bundle)

    @property
    def keys(self) -> list[list[str]]:
        return [sorted(bundle.configs) for bundle in self.bundles]


def options(url: str, sink: Sink, logger: RecordingLogger, **overrides: Any) -> TransportOptions:
    return TransportOptions(
        server_sdk_key="sdk-key",
        base_url=url,
        meta_context={"sdkName": "python-server-sdk", "sdkVersion": "1.2.3"},
        logger=logger,
        on_bundle=sink,
        **overrides,
    )


def bundle_json(*keys: str) -> str:
    return json.dumps(
        {
            "environmentId": "10000000-0000-0000-0000-000000000000",
            "projectId": "20000000-0000-0000-0000-000000000000",
            "kind": "full",
            "timestamp": "2024-01-01T00:00:00.000Z",
            "configs": {
                key: {
                    "id": f"cfg-{key}",
                    "key": key,
                    "type": "string",
                    "variations": [],
                    "target": {"defaultValue": "hello", "rules": []},
                }
                for key in keys
            },
        }
    )


def respond(request: http.server.BaseHTTPRequestHandler, status: int, body: str = "") -> None:
    payload = body.encode("utf-8")
    request.send_response(status)
    request.send_header("Content-Type", "application/json")
    request.send_header("Content-Length", str(len(payload)))
    request.end_headers()
    if payload:
        request.wfile.write(payload)


def sse_headers(request: http.server.BaseHTTPRequestHandler) -> None:
    request.send_response(200)
    request.send_header("Content-Type", "text/event-stream")
    request.send_header("Cache-Control", "no-cache")
    request.send_header("Connection", "close")
    request.end_headers()


@pytest.fixture
def sink() -> Sink:
    return Sink()


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


class TestPollingTransport:
    def test_posts_the_sdk_key_and_meta_context_to_the_polling_endpoint(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = PollingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
        finally:
            transport.close()

        assert server.paths == ["/server/polling/v1"]
        assert server.requests[0]["serverSdkKey"] == "sdk-key"
        assert server.requests[0]["metaContext"]["sdkName"] == "python-server-sdk"

    def test_delivers_the_bundle_from_the_first_fetch(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = PollingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
        finally:
            transport.close()

        assert sink.keys == [["greeting"]]

    def test_omits_the_timestamp_on_the_first_request(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json()))
        transport = PollingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
        finally:
            transport.close()

        assert "lastUpdateTimestamp" not in server.requests[0]

    def test_sends_the_previous_timestamp_on_later_polls(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = PollingTransport(options(server.url, sink, logger, polling_interval=0.02))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(server.requests) >= 2)
        finally:
            transport.close()

        assert server.requests[1]["lastUpdateTimestamp"] == "2024-01-01T00:00:00.000Z"

    def test_keeps_polling_on_the_interval(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = PollingTransport(options(server.url, sink, logger, polling_interval=0.02))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(sink.bundles) >= 3)
        finally:
            transport.close()

    def test_no_content_delivers_nothing(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 204))
        transport = PollingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
        finally:
            transport.close()

        assert sink.bundles == []

    def test_a_server_error_is_raised_but_leaves_polling_running(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 503, "unavailable"))
        transport = PollingTransport(options(server.url, sink, logger, polling_interval=0.02))

        try:
            with pytest.raises(ConfigDirectorConnectionError, match="status: 503"):
                transport.connect(5.0)

            # A transient failure must not leave the SDK without a connection.
            assert wait_for(lambda: len(server.requests) >= 2)
        finally:
            transport.close()

    def test_a_client_error_is_fatal_and_stops_polling(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 401, "Unauthorized"))
        transport = PollingTransport(options(server.url, sink, logger, polling_interval=0.02))

        try:
            with pytest.raises(ConfigDirectorConnectionError, match="unrecoverable") as raised:
                transport.connect(5.0)
        finally:
            transport.close()

        assert raised.value.status == 401
        assert "Unauthorized" in str(raised.value)
        assert transport.is_connected is False
        assert len(server.requests) == 1

    def test_a_malformed_response_body_is_reported(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, "{not json"))
        transport = PollingTransport(options(server.url, sink, logger))

        try:
            with pytest.raises(ConfigDirectorConnectionError, match="Failed to parse the response"):
                transport.connect(5.0)
        finally:
            transport.close()

    def test_an_unreachable_server_is_reported_as_transient(
        self, sink: Sink, logger: RecordingLogger
    ) -> None:
        # Port 1 is reserved and never listening.
        transport = PollingTransport(options("http://127.0.0.1:1", sink, logger))

        try:
            with pytest.raises(ConfigDirectorConnectionError, match="Connection failed with error"):
                transport.connect(1.0)
        finally:
            transport.close()

    def test_close_stops_the_polling_thread(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = PollingTransport(options(server.url, sink, logger, polling_interval=0.02))
        transport.connect(5.0)
        assert transport.is_connected is True

        transport.close()

        assert wait_for(lambda: transport.is_connected is False)
        polled = len(server.requests)
        assert wait_for(lambda: len(server.requests) > polled, timeout=0.2) is False

    def test_a_proxy_base_url_keeps_its_path(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json()))
        transport = PollingTransport(options(f"{server.url}/proxy", sink, logger))

        try:
            transport.connect(5.0)
        finally:
            transport.close()

        assert server.paths == ["/proxy/server/polling/v1"]


class TestOneTimeTransport:
    def test_fetches_once_and_never_polls(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("greeting")))
        transport = OneTimeTransport(options(server.url, sink, logger, polling_interval=0.02))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(server.requests) > 1, timeout=0.2) is False
        finally:
            transport.close()

        assert sink.keys == [["greeting"]]
        assert transport.is_connected is False


class TestStreamingTransport:
    def test_posts_the_sdk_key_to_the_sse_endpoint(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            request.wfile.write(f"data: {bundle_json('greeting')}\n\n".encode())
            request.wfile.flush()

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(sink.bundles) == 1)
        finally:
            transport.close()

        assert server.paths == ["/server/sse/v1"]
        assert server.requests[0]["serverSdkKey"] == "sdk-key"
        assert sink.keys == [["greeting"]]

    def test_connect_returns_once_the_stream_is_open(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        release = threading.Event()

        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            request.wfile.write(b": open\n\n")
            request.wfile.flush()
            release.wait(5)

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
            assert transport.is_connected is True
        finally:
            release.set()
            transport.close()

    def test_delivers_every_update_on_the_stream(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            for key in ("first", "second"):
                request.wfile.write(f"data: {bundle_json(key)}\n\n".encode())
                request.wfile.flush()

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(sink.bundles) == 2)
        finally:
            transport.close()

        assert sink.keys == [["first"], ["second"]]

    def test_a_malformed_message_is_logged_and_skipped(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            request.wfile.write(b"data: {not json\n\n")
            request.wfile.write(f"data: {bundle_json('greeting')}\n\n".encode())
            request.wfile.flush()

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            transport.connect(5.0)
            assert wait_for(lambda: len(sink.bundles) == 1)
        finally:
            transport.close()

        assert sink.keys == [["greeting"]]
        assert any("Error parsing a config update" in m for m in logger.messages("error"))

    def test_a_client_error_status_is_unrecoverable(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 401, "Unauthorized"))
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            with pytest.raises(ConfigDirectorConnectionError, match="unrecoverable") as raised:
                transport.connect(5.0)
        finally:
            transport.close()

        assert raised.value.status == 401
        assert len(server.requests) == 1

    def test_a_server_error_status_is_retried(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            if len(server.requests) == 1:
                respond(request, 503, "unavailable")
                return
            sse_headers(request)
            request.wfile.write(f"data: {bundle_json('greeting')}\n\n".encode())
            request.wfile.flush()

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))

        try:
            # The first attempt fails; the backoff schedules the retry that succeeds.
            transport.connect(0.1)
            assert wait_for(lambda: len(sink.bundles) == 1, timeout=10)
        finally:
            transport.close()

        assert sink.keys == [["greeting"]]

    def test_close_stops_the_stream(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        release = threading.Event()

        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            request.wfile.write(b": open\n\n")
            request.wfile.flush()
            release.wait(5)

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))
        transport.connect(5.0)

        try:
            transport.close()
        finally:
            release.set()

        assert transport.is_connected is False


class TestUserAgent:
    # Without an explicit User-Agent, urllib identifies itself as "Python-urllib/3.x", which
    # bot-protection layers in front of the API reject outright — the request never reaches the
    # origin, and the SDK reports a 403 that looks like a bad SDK key.
    def test_polling_identifies_the_sdk(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        server = serve(lambda request: respond(request, 200, bundle_json("a")))
        OneTimeTransport(options(server.url, sink, logger)).connect(5.0)

        user_agent = server.headers[0].get("User-Agent", "")
        assert "python-server-sdk" in user_agent
        assert "Python-urllib" not in user_agent

    def test_streaming_identifies_the_sdk(
        self, serve: Callable[[Handler], _Server], sink: Sink, logger: RecordingLogger
    ) -> None:
        def handle(request: http.server.BaseHTTPRequestHandler) -> None:
            sse_headers(request)
            request.wfile.write(f"data: {bundle_json('a')}\n\n".encode())
            request.wfile.flush()

        server = serve(handle)
        transport = StreamingTransport(options(server.url, sink, logger))
        transport.connect(5.0)
        wait_for(lambda: bool(server.headers))
        transport.close()

        user_agent = server.headers[0].get("User-Agent", "")
        assert "python-server-sdk" in user_agent
        assert "Python-urllib" not in user_agent
