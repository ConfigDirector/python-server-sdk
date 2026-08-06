from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from configdirector._eventsource import StreamRequest

WAIT_TIMEOUT = 5.0


def wait_for(predicate: Callable[[], bool], *, timeout: float = WAIT_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


class FakeResponse:
    def __init__(self, status: int = 200, chunks: Iterable[bytes] = (), *, hang: bool = False) -> None:
        self.status = status
        self._chunks = list(chunks)
        self._hang = hang
        self._released = threading.Event()
        self.closed = False

    def read1(self, amount: int = -1, /) -> bytes:
        if self.closed:
            return b""
        if self._chunks:
            return self._chunks.pop(0)
        # An idle connection, behaving like a real socket with a read timeout: the read gives up
        # periodically so the reader can notice it has been stopped.
        if self._hang and not self._released.wait(0.02):
            raise TimeoutError
        return b""

    def close(self) -> None:
        self.closed = True
        self._released.set()


class FakeTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self._responses = list(responses)
        self.requests: list[StreamRequest] = []
        self.opened = threading.Semaphore(0)
        self._lock = threading.Lock()

    def __call__(self, request: StreamRequest) -> FakeResponse:
        with self._lock:
            self.requests.append(request)
            index = min(len(self.requests) - 1, len(self._responses) - 1)
            response = self._responses[index]
        self.opened.release()
        return response

    @property
    def attempts(self) -> int:
        with self._lock:
            return len(self.requests)


class FailingTransport:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.attempts = 0

    def __call__(self, request: StreamRequest) -> FakeResponse:
        self.attempts += 1
        raise self._error


def sse(*chunks: str) -> list[bytes]:
    return [chunk.encode("utf-8") for chunk in chunks]
