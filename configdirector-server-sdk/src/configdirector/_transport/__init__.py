from .._connection_plan import LiveConnectionMode
from .base import DEFAULT_POLLING_INTERVAL, MIN_POLLING_INTERVAL, Transport, TransportOptions
from .offline import OfflineTransport
from .polling import PollingTransport
from .streaming import StreamingTransport

__all__ = [
    "DEFAULT_POLLING_INTERVAL",
    "MIN_POLLING_INTERVAL",
    "OfflineTransport",
    "PollingTransport",
    "StreamingTransport",
    "Transport",
    "TransportOptions",
    "create_transport",
]


def create_transport(mode: LiveConnectionMode, options: TransportOptions) -> Transport:
    match mode:
        case "polling":
            return PollingTransport(options)
        case "streaming":
            return StreamingTransport(options)
