from __future__ import annotations

from ..errors import ConfigDirectorError

__all__ = [
    "EventSourceError",
    "StreamClosedError",
    "StreamStalledError",
    "StreamTooLargeError",
    "ValueOutOfRangeError",
]


class EventSourceError(ConfigDirectorError):
    pass


class StreamClosedError(EventSourceError):
    pass


class StreamStalledError(EventSourceError):
    pass


class StreamTooLargeError(EventSourceError):
    pass


class ValueOutOfRangeError(EventSourceError):
    pass
