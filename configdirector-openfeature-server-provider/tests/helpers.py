from __future__ import annotations

import http.server
import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

POLLING_PATH = "/server/polling/v1"
STREAMING_PATH = "/server/sse/v1"
TELEMETRY_PATH = "/server/telemetry/v1"


def config(key: str, type: str, value: str, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": f"cfg-{key}",
        "key": key,
        "type": type,
        "variations": [],
        "target": {"defaultValue": value, "defaultValueId": f"default-of-{key}", "rules": rules or []},
    }


def rule(attribute: str, target_value: str, value: str, trait: str | None = None) -> dict[str, Any]:
    return {
        "id": f"rule-{attribute}-{target_value}",
        "type": "conditional",
        "order": 1,
        "target": "value",
        "value": value,
        "valueId": f"rule-value-{value}",
        "conditions": [
            {
                "id": f"condition-{attribute}-{target_value}",
                "attribute": attribute,
                "trait": trait,
                "operator": "equals",
                "targetType": "text",
                "targetValues": [target_value],
            }
        ],
    }


def bundle(*configs: dict[str, Any]) -> str:
    return json.dumps(
        {
            "environmentId": "10000000-0000-0000-0000-000000000000",
            "projectId": "20000000-0000-0000-0000-000000000000",
            "kind": "full",
            "timestamp": "2024-01-01T00:00:00.000Z",
            "configs": {entry["key"]: entry for entry in configs},
        }
    )


class Request:
    def __init__(self, path: str, headers: dict[str, str], body: Any) -> None:
        self.path = path
        self.headers = headers
        self.body = body


class FakeConfigDirectorServer:
    def __init__(self, *configs: dict[str, Any]) -> None:
        outer = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(Request(self.path, dict(self.headers), body))
                if self.path in (STREAMING_PATH, POLLING_PATH) and not outer.accepts_the_sdk_key:
                    outer._respond(self, 401, "")
                elif self.path == STREAMING_PATH:
                    outer._stream(self)
                elif self.path == POLLING_PATH and outer.available:
                    outer._respond(self, 200, outer._bundles[-1])
                elif self.path == POLLING_PATH:
                    outer._respond(self, 503, "")
                else:
                    outer._respond(self, 200, "{}")

            def log_message(self, *args: object) -> None:
                pass

        self._bundles = [bundle(*configs)]
        self._bundle_pushed = threading.Condition()
        self.available = True
        self.accepts_the_sdk_key = True
        self.stream_released = threading.Event()
        self.stream_released.set()
        self._closing = False
        self.requests: list[Request] = []
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

    def push(self, *configs: dict[str, Any]) -> None:
        with self._bundle_pushed:
            self._bundles.append(bundle(*configs))
            self._bundle_pushed.notify_all()

    def requests_to(self, path: str) -> list[Request]:
        return [request for request in list(self.requests) if request.path == path]

    def close(self) -> None:
        with self._bundle_pushed:
            self._closing = True
            self._bundle_pushed.notify_all()
        self.stream_released.set()
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

    def _stream(self, request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(200)
        request.send_header("Content-Type", "text/event-stream")
        request.send_header("Cache-Control", "no-cache")
        request.end_headers()
        request.wfile.flush()
        self.stream_released.wait()
        with self._bundle_pushed:
            next_unsent = len(self._bundles) - 1
        try:
            while True:
                with self._bundle_pushed:
                    if self._closing:
                        return
                    unsent = self._bundles[next_unsent:]
                for pushed in unsent:
                    request.wfile.write(f"data: {pushed}\n\n".encode())
                    request.wfile.flush()
                next_unsent += len(unsent)
                with self._bundle_pushed:
                    if len(self._bundles) == next_unsent:
                        self._bundle_pushed.wait(timeout=0.05)
        except OSError:
            return


class ForkedProcess:
    def __init__(self, text_to_report: Callable[[], str]) -> None:
        reported_text, report = os.pipe()
        self._process_id = os.fork()
        if self._process_id == 0:
            exit_code = 1
            try:
                os.write(report, text_to_report().encode())
                exit_code = 0
            finally:
                os._exit(exit_code)
        os.close(report)
        self._reported_text = reported_text

    def reported_text(self) -> str:
        try:
            return os.read(self._reported_text, 65536).decode()
        finally:
            os.close(self._reported_text)
            os.waitpid(self._process_id, 0)


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the condition to become true")
