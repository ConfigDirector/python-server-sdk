from __future__ import annotations

import http.server
import json
import threading
import time
from collections.abc import Callable
from typing import Any

from openfeature import api
from openfeature.provider import FeatureProvider

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
                if self.path == STREAMING_PATH:
                    outer._stream(self)
                elif self.path == POLLING_PATH and outer.available:
                    outer._respond(self, 200, outer._bundle)
                elif self.path == POLLING_PATH:
                    outer._respond(self, 503, "")
                else:
                    outer._respond(self, 200, "{}")

            def log_message(self, *args: object) -> None:
                pass

        self._bundle = bundle(*configs)
        self.available = True
        self.stream_released = threading.Event()
        self.stream_released.set()
        self._closing = threading.Event()
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

    def requests_to(self, path: str) -> list[Request]:
        return [request for request in list(self.requests) if request.path == path]

    def close(self) -> None:
        self._closing.set()
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
        if self._closing.is_set():
            return
        try:
            request.wfile.write(f"data: {self._bundle}\n\n".encode())
            request.wfile.flush()
        except OSError:
            return
        self._closing.wait()


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the condition to become true")


def set_provider_and_wait(provider: FeatureProvider) -> None:
    getattr(api, "set_provider_and_wait", api.set_provider)(provider)
