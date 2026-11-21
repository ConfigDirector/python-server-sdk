from __future__ import annotations

import contextlib
import http.server
import json
import os
import select
import signal
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tests.helpers import WAIT_TIMEOUT

STREAMING_PATH = "/server/sse/v1"
POLLING_PATH = "/server/polling/v1"
HEARTBEAT_PATH = "/server/heartbeat/v1"
TELEMETRY_PATH = "/server/telemetry/v1"

_REPORT_TIMEOUT = WAIT_TIMEOUT * 3
_KEEP_ALIVE_INTERVAL = 0.02


@dataclass(frozen=True)
class ReceivedRequest:
    path: str
    body: Any
    peer_port: int


class PublishingServer:
    def __init__(self, greeting: str | None) -> None:
        outer = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(ReceivedRequest(self.path, body, self.client_address[1]))
                if self.path in (STREAMING_PATH, POLLING_PATH) and not outer.accepts_the_sdk_key:
                    outer._respond(self, 401, "Unauthorized")
                elif self.path == STREAMING_PATH:
                    outer._stream(self, body["sessionId"])
                elif self.path == POLLING_PATH:
                    outer._answer_poll(self, body.get("lastUpdateTimestamp"))
                else:
                    outer._respond(self, 204, "")

            def log_message(self, *args: object) -> None:
                pass

        self.requests: list[ReceivedRequest] = []
        self.session_ids_of_ended_streams: list[str] = []
        self.accepts_the_sdk_key = True
        self._publication_made = threading.Condition()
        self._greeting = greeting
        self._publication = 1
        self._closing = False
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port!s}"

    def publish(self, greeting: str) -> None:
        with self._publication_made:
            self._greeting = greeting
            self._publication += 1
            self._publication_made.notify_all()

    def requests_to(self, path: str) -> list[ReceivedRequest]:
        return [request for request in list(self.requests) if request.path == path]

    def close(self) -> None:
        with self._publication_made:
            self._closing = True
            self._publication_made.notify_all()
        self._httpd.shutdown()
        self._httpd.server_close()

    def _respond(self, request: http.server.BaseHTTPRequestHandler, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(payload)))
        request.end_headers()
        if payload:
            request.wfile.write(payload)

    def _answer_poll(
        self, request: http.server.BaseHTTPRequestHandler, last_update_timestamp: str | None
    ) -> None:
        with self._publication_made:
            greeting, publication = self._greeting, self._publication
        if greeting is None or last_update_timestamp == _timestamp_of(publication):
            self._respond(request, 204, "")
        else:
            self._respond(request, 200, _payload(greeting, publication))

    def _stream(self, request: http.server.BaseHTTPRequestHandler, session_id: str) -> None:
        request.send_response(200)
        request.send_header("Content-Type", "text/event-stream")
        request.send_header("Cache-Control", "no-cache")
        request.send_header("Connection", "close")
        request.end_headers()
        sent_publication = 0
        try:
            while True:
                with self._publication_made:
                    if self._closing:
                        return
                    greeting, publication = self._greeting, self._publication
                if greeting is not None and publication != sent_publication:
                    request.wfile.write(f"data: {_payload(greeting, publication)}\n\n".encode())
                    sent_publication = publication
                else:
                    request.wfile.write(b": keep-alive\n\n")
                request.wfile.flush()
                with self._publication_made:
                    self._publication_made.wait(timeout=_KEEP_ALIVE_INTERVAL)
        except OSError:
            return
        finally:
            self.session_ids_of_ended_streams.append(session_id)


def _timestamp_of(publication: int) -> str:
    return f"2026-01-01T00:00:{publication:02d}.000Z"


def _payload(greeting: str, publication: int) -> str:
    return json.dumps(
        {
            "environmentId": "10000000-0000-0000-0000-000000000000",
            "projectId": "20000000-0000-0000-0000-000000000000",
            "kind": "full",
            "timestamp": _timestamp_of(publication),
            "configs": {
                "greeting": {
                    "id": "cfg-greeting",
                    "key": "greeting",
                    "type": "string",
                    "variations": [],
                    "target": {"defaultValue": greeting, "rules": []},
                }
            },
        }
    )


class LinkToTheParentProcess:
    def __init__(self, reports: int, release: int) -> None:
        self._reports = reports
        self._release = release

    def report(self, value: Any) -> None:
        _write_line(self._reports, {"report": value})

    def wait_for_the_parent(self) -> None:
        os.read(self._release, 1)


class ForkedProcess:
    def __init__(self, run: Callable[[LinkToTheParentProcess], None]) -> None:
        reports_read, reports_write = os.pipe()
        release_read, release_write = os.pipe()
        self._process_id = os.fork()
        if self._process_id == 0:
            exit_code = 1
            try:
                os.close(reports_read)
                os.close(release_write)
                run(LinkToTheParentProcess(reports_write, release_read))
                exit_code = 0
            except BaseException:
                _write_line(reports_write, {"failure": traceback.format_exc()})
            finally:
                os._exit(exit_code)
        os.close(reports_write)
        os.close(release_read)
        self._reports = reports_read
        self._release = release_write
        self._unread = b""
        self._exit_code: int | None = None

    @property
    def process_id(self) -> int:
        return self._process_id

    def next_report(self) -> Any:
        deadline = time.monotonic() + _REPORT_TIMEOUT
        while b"\n" not in self._unread:
            readable, _, _ = select.select([self._reports], [], [], max(deadline - time.monotonic(), 0))
            received = os.read(self._reports, 65536) if readable else b""
            if not received:
                raise AssertionError("The forked process sent no report")
            self._unread += received
        line, _, self._unread = self._unread.partition(b"\n")
        message = json.loads(line)
        if "failure" in message:
            raise AssertionError(f"The forked process failed:\n{message['failure']}")
        return message["report"]

    def release(self) -> None:
        os.write(self._release, b"1")

    def wait_for_exit(self) -> int:
        if self._exit_code is None:
            _, status = os.waitpid(self._process_id, 0)
            self._exit_code = os.waitstatus_to_exitcode(status)
        return self._exit_code

    def end(self) -> None:
        if self._exit_code is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self._process_id, signal.SIGKILL)
            self.wait_for_exit()
        os.close(self._reports)
        os.close(self._release)


def _write_line(file_descriptor: int, message: dict[str, Any]) -> None:
    os.write(file_descriptor, json.dumps(message).encode() + b"\n")
