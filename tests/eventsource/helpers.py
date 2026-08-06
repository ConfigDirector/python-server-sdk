from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator

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
    """A `ResponseStream` whose body is a fixed list of chunks.

    With `hang`, the stream stays open after the chunks run out, the way a real idle SSE
    connection does, and ends only when `close()` cancels it.
    """

    def __init__(self, status: int = 200, chunks: Iterable[bytes] = (), *, hang: bool = False) -> None:
        self.status = status
        self._chunks = list(chunks)
        self._hang = hang
        self._released = threading.Event()
        self.closed = False

    def chunks(self, amount: int) -> Iterator[bytes]:
        for chunk in self._chunks:
            if self.closed:
                return
            yield chunk
        # Bounded so a test that forgets to close cannot wedge the suite.
        if self._hang and not self.closed and not self._released.wait(WAIT_TIMEOUT):
            raise AssertionError("a hanging FakeResponse was never released")

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
