from ..types import ConnectionMode
from .base import DEFAULT_POLLING_INTERVAL, MIN_POLLING_INTERVAL, Transport, TransportOptions
from .polling import PollingTransport
from .streaming import StreamingTransport

__all__ = [
    "DEFAULT_POLLING_INTERVAL",
    "MIN_POLLING_INTERVAL",
    "PollingTransport",
    "StreamingTransport",
    "Transport",
    "TransportOptions",
    "create_transport",
]


def create_transport(mode: ConnectionMode, options: TransportOptions) -> Transport:
    match mode:
        case "polling":
            return PollingTransport(options)
        case _:
            return StreamingTransport(options)
