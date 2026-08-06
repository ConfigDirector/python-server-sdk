from __future__ import annotations

import threading

from .._bundle import parse_bundle
from .._eventsource import EventSourceClient, EventSourceMessage, ReadyState, ReconnectionState
from ..errors import ConfigDirectorConnectionError
from .base import (
    REQUEST_HEADERS,
    TransportOptions,
    fatal_status_error,
    is_fatal_status,
    json_body,
    resolve,
)

__all__ = ["StreamingTransport"]

_PATH = "server/sse/v1"

# 2^9 = 512 seconds, which caps the backoff just under 10 minutes.
_MAX_BACKOFF_EXPONENT = 9

# Past this many attempts a reconnect is no longer routine and deserves a louder log level.
_QUIET_ATTEMPTS = 5


class StreamingTransport:
    def __init__(self, options: TransportOptions) -> None:
        self._options = options
        self._logger = options.logger
        self._url = resolve(options.base_url, _PATH)
        self._client: EventSourceClient | None = None
        self._settled = threading.Event()
        self._fatal_error: ConfigDirectorConnectionError | None = None

    def connect(self, timeout: float) -> None:
        self.close()
        self._settled.clear()
        self._fatal_error = None

        client = EventSourceClient(
            self._url,
            method="POST",
            headers=REQUEST_HEADERS,
            body=json_body(
                {
                    "serverSdkKey": self._options.server_sdk_key,
                    "metaContext": self._options.meta_context,
                }
            ),
            logger=self._logger,
            on_message=self._on_message,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            should_reconnect=self._should_reconnect,
            calculate_reconnect_delay=self._reconnect_delay,
        )
        self._client = client
        client.connect()

        # Returning on the timeout is not a failure: the stream keeps retrying in the
        # background, and the client reports itself unready until config state arrives.
        self._settled.wait(timeout)
        if self._fatal_error is not None:
            raise self._fatal_error

    @property
    def is_connected(self) -> bool:
        client = self._client
        return client is not None and client.ready_state is ReadyState.OPEN

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    # -- stream handlers --------------------------------------------------------------------

    def _on_connect(self) -> None:
        self._logger.debug("[StreamingTransport] Connected")
        self._settled.set()

    def _on_disconnect(self) -> None:
        self._logger.debug("[StreamingTransport] Disconnected")

    def _on_message(self, message: EventSourceMessage) -> None:
        try:
            bundle = parse_bundle(message.data, self._logger)
        except ValueError as error:
            self._logger.error("[StreamingTransport] Error parsing a config update: %r", error)
            return
        self._options.on_bundle(bundle)

    def _should_reconnect(self, state: ReconnectionState) -> bool:
        if not is_fatal_status(state.status):
            return True

        detail = f"{state.error}" if state.error is not None else None
        self._fatal_error = fatal_status_error(state.status, detail)
        self._logger.error("[StreamingTransport] %s", self._fatal_error)
        # Whoever is still blocked in connect() is waiting for exactly this.
        self._settled.set()
        return False

    def _reconnect_delay(self, state: ReconnectionState) -> float:
        delay = float(2 ** min(state.attempt, _MAX_BACKOFF_EXPONENT))
        log = self._logger.info if state.attempt <= _QUIET_ATTEMPTS else self._logger.warning
        log("[StreamingTransport] Scheduling reconnect attempt #%d in %ss.", state.attempt, delay)
        return delay
