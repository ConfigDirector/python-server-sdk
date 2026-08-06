from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

__all__ = [
    "EventSourceMessage",
    "ReadyState",
    "ReconnectionState",
    "ResponseStream",
]


class ReadyState(Enum):
    CONNECTING = "connecting"
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class EventSourceMessage:
    data: str
    type: str | None = None
    id: str | None = None


@dataclass(frozen=True, slots=True)
class ReconnectionState:
    attempt: int
    server_reconnect_delay: float
    status: int | None = None
    error: BaseException | None = None


class ResponseStream(Protocol):
    """The subset of a HTTP response the reader needs.

    `chunks` yields body bytes as they arrive and ends when the stream does. It must raise this
    SDK's own exception types rather than any belonging to the underlying HTTP library, so that
    supplying a different transport does not change what the reader has to handle.
    """

    @property
    def status(self) -> int: ...

    def chunks(self, amount: int) -> Iterator[bytes]: ...

    # Must be safe to call from another thread while `chunks` is blocked, and must make that
    # iterator stop rather than waiting for it.
    def close(self) -> None: ...
