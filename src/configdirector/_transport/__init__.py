from ..types import ConnectionMode
from .base import Transport, TransportOptions
from .polling import OneTimeTransport, PollingTransport
from .streaming import StreamingTransport

__all__ = [
    "OneTimeTransport",
    "PollingTransport",
    "StreamingTransport",
    "Transport",
    "TransportOptions",
    "create_transport",
]


def create_transport(mode: ConnectionMode, options: TransportOptions) -> Transport:
    match mode:
        case "one-time":
            return OneTimeTransport(options)
        case "polling":
            return PollingTransport(options)
        case _:
            return StreamingTransport(options)
