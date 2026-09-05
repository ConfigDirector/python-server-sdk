from __future__ import annotations

import threading
import uuid

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
_HEARTBEAT_PATH = "server/heartbeat/v1"

# Fixed by the protocol rather than configurable: the dashboard decides a streaming session has
# died by how long ago its last heartbeat arrived, so every SDK has to beat on the same interval.
_HEARTBEAT_INTERVAL = 90.0

# How long close() waits for a heartbeat already in flight to return.
_HEARTBEAT_JOIN_TIMEOUT = 5.0

# 2^9 = 512 seconds, which caps the backoff just under 10 minutes.
_MAX_BACKOFF_EXPONENT = 9

# Past this many attempts a reconnect is no longer routine and deserves a louder log level.
_QUIET_ATTEMPTS = 5

# The server keeps the stream alive with a comment every 15 seconds, so silence for three of
# those in a row is not an idle stream, it is a dead one -- typically a connection an idle
# timeout somewhere in the middle dropped without telling either end. Waiting indefinitely
# instead, which is what None would mean, leaves the SDK reading from a socket that will never
# produce another byte and serving whatever config it last received.
_READ_TIMEOUT = 45.0


class StreamingTransport:
    def __init__(
        self,
        options: TransportOptions,
        read_timeout: float | None = _READ_TIMEOUT,
        heartbeat_interval: float = _HEARTBEAT_INTERVAL,
    ) -> None:
        self._options = options
        self._logger = options.logger
        self._url = resolve(options.base_url, _PATH)
        self._heartbeat_url = resolve(options.base_url, _HEARTBEAT_PATH)
        # Injectable so a test can stall a stream out in milliseconds rather than in minutes.
        self._read_timeout = read_timeout
        # Injectable for the same reason; the public API offers no way to change it.
        self._heartbeat_interval = heartbeat_interval
        self._client: EventSourceClient | None = None
        self._settled = threading.Event()
        self._fatal_error: ConfigDirectorConnectionError | None = None
        self._session_id: str | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_stop.set()
        self._heartbeat_thread: threading.Thread | None = None

    def connect(self, timeout: float) -> None:
        self.close()
        self._settled.clear()
        self._fatal_error = None

        client = EventSourceClient(
            self._url,
            method="POST",
            headers=REQUEST_HEADERS,
            body=self._build_request_body,
            logger=self._logger,
            read_timeout=self._read_timeout,
            on_message=self._on_message,
            on_error=self._on_error,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            should_reconnect=self._should_reconnect,
            calculate_reconnect_delay=self._reconnect_delay,
        )
        self._client = client
        client.connect()
        self._start_heartbeat()

        # Returning on the timeout is not a failure: the stream keeps retrying in the
        # background, and the client reports itself unready until config state arrives.
        self._settled.wait(timeout)
        if self._fatal_error is not None:
            raise self._fatal_error

    @property
    def read_timeout(self) -> float | None:
        return self._read_timeout

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def heartbeat_interval(self) -> float:
        return self._heartbeat_interval

    def _build_request_body(self) -> bytes:
        self._session_id = str(uuid.uuid4())
        return json_body(
            {
                "serverSdkKey": self._options.server_sdk_key,
                "metaContext": self._options.meta_context,
                "sessionId": self._session_id,
            }
        )

    @property
    def is_connected(self) -> bool:
        client = self._client
        return client is not None and client.ready_state is ReadyState.OPEN

    def close(self) -> None:
        self._heartbeat_stop.set()
        thread, self._heartbeat_thread = self._heartbeat_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_HEARTBEAT_JOIN_TIMEOUT)
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def _start_heartbeat(self) -> None:
        stop = threading.Event()
        self._heartbeat_stop = stop
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(stop,),
            name="configdirector-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        while not stop.wait(self._heartbeat_interval):
            self._send_heartbeat()

    def _send_heartbeat(self) -> None:
        session_id = self._session_id
        if not self.is_connected or session_id is None:
            return
        body = json_body({"serverSdkKey": self._options.server_sdk_key, "sessionId": session_id})
        try:
            self._options.http.post(self._heartbeat_url, body, REQUEST_HEADERS, self._heartbeat_interval)
        except Exception as error:
            # A missed heartbeat is not worth disturbing the stream over; the server tolerates
            # gaps, and a connection problem shows up on the stream itself soon enough.
            self._logger.debug("[StreamingTransport] The heartbeat failed: %r", error)

    # -- stream handlers --------------------------------------------------------------------

    def _on_connect(self) -> None:
        self._logger.debug("[StreamingTransport] Connected")
        self._settled.set()

    def _on_disconnect(self) -> None:
        self._logger.debug("[StreamingTransport] Disconnected")

    def _on_error(self, error: BaseException) -> None:
        # Says why the stream dropped. The reconnect it causes is logged on its own, at a level
        # that reflects how many have gone by; this is the detail behind it, and a stalled
        # stream has no other way of announcing itself.
        self._logger.debug("[StreamingTransport] The stream failed: %r", error)

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
