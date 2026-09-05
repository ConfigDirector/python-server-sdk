from ..types import ConnectionMode
from .base import Transport, TransportOptions
from .polling import PollingTransport
from .streaming import StreamingTransport

__all__ = [
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
