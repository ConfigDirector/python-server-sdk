from __future__ import annotations

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

    Matches http.client.HTTPResponse, so urllib responses satisfy it as-is, and a caller can
    supply requests/httpx with a thin wrapper.
    """

    @property
    def status(self) -> int: ...

    def read1(self, amount: int = -1, /) -> bytes: ...

    def close(self) -> None: ...
