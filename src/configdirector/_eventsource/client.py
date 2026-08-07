from __future__ import annotations

import codecs
import contextlib
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from ..errors import ConfigDirectorTypeError
from ..types import ConfigDirectorLogger
from .errors import StreamClosedError, ValueOutOfRangeError
from .parser import DEFAULT_MAX_EVENT_CHARS, DEFAULT_MAX_LINE_CHARS, EventSourceParser
from .transport import StreamOpener, StreamRequest
from .types import EventSourceMessage, ReadyState, ReconnectionState, ResponseStream

__all__ = ["EventSourceClient"]

_T = TypeVar("_T")
_C = TypeVar("_C", bound=Callable[..., Any])

# Bytes taken from the socket per read. Large enough that a burst of events costs few syscalls,
# small enough that a slow trickle is still delivered promptly.
_READ_SIZE = 1 << 16

# How long close() waits for the reader to notice the socket has been shut down under it.
_CLOSE_TIMEOUT = 5.0

_DEFAULT_SERVER_DELAY = 2.0
_MIN_RECONNECT_DELAY = 0.001
_MAX_RECONNECT_DELAY = 3600.0


@dataclass(frozen=True, slots=True)
class _Failure:
    status: int | None = None
    error: BaseException | None = None


class EventSourceClient:
    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        last_event_id: str | None = None,
        connect_timeout: float | None = 10.0,
        read_timeout: float | None = None,
        follow_redirects: bool = True,
        transport: Callable[[StreamRequest], ResponseStream] | None = None,
        logger: ConfigDirectorLogger,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        on_message: Callable[[EventSourceMessage], None] | None = None,
        on_comment: Callable[[str], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        should_reconnect: Callable[[ReconnectionState], bool] | None = None,
        calculate_reconnect_delay: Callable[[ReconnectionState], float] | None = None,
        max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
        max_event_chars: int = DEFAULT_MAX_EVENT_CHARS,
    ) -> None:
        self._url = url
        self._method = method
        self._body = body
        # The caller's headers may override Accept, but not by accident.
        self._headers = {"Accept": "text/event-stream", **(headers or {})}
        self._last_event_id = last_event_id
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._follow_redirects = follow_redirects
        # Only owned when the caller did not bring its own transport, and only then is it this
        # client's to close: a supplied one belongs to whoever supplied it.
        self._opener: StreamOpener | None = None
        if transport is None:
            self._opener = StreamOpener()
            transport = self._opener
        self._transport = transport
        self._logger = logger
        self._max_line_chars = max_line_chars
        self._max_event_chars = max_event_chars

        self.on_connect = _checked(on_connect, "on_connect")
        self.on_disconnect = _checked(on_disconnect, "on_disconnect")
        self.on_message = _checked(on_message, "on_message")
        self.on_comment = _checked(on_comment, "on_comment")
        self.on_error = _checked(on_error, "on_error")
        self.should_reconnect = _checked(should_reconnect, "should_reconnect")
        self.calculate_reconnect_delay = _checked(calculate_reconnect_delay, "calculate_reconnect_delay")

        # Guards the compound parts of connect() and close() against each other. Everything
        # else is a single attribute read or write, and _stop is what says whether the worker
        # should still be running.
        self._lock = threading.Lock()
        self._ready_state = ReadyState.CLOSED
        self._attempt = 0
        self._server_delay = _DEFAULT_SERVER_DELAY
        self._stop = threading.Event()
        self._stop.set()
        self._thread: threading.Thread | None = None
        # The response the reader is currently blocked on, so close() can interrupt it.
        self._response: ResponseStream | None = None

    @property
    def ready_state(self) -> ReadyState:
        return self._ready_state

    # -- lifecycle --------------------------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            if self._ready_state is not ReadyState.CLOSED:
                return
            self._ready_state = ReadyState.CONNECTING
            self._attempt = 0
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, name="configdirector-eventsource", daemon=True)
            self._thread.start()

    def close(self) -> None:
        with self._lock:
            self._ready_state = ReadyState.CLOSED
            stop, thread, response = self._stop, self._thread, self._response
            self._thread = None

        stop.set()
        # Drops the connection under the reader, so a chunks() call blocked waiting for the next
        # event gives up instead of holding close() until the server sends something. Cancelling
        # rather than closing is what keeps this thread out of the reader's way: releasing the
        # response needs a lock the parked reader holds, so the reader does that itself on the
        # way out. Should the cancel fail to land, close() still returns on the join timeout
        # below, having leaked a stream rather than hung its caller.
        if response is not None:
            _cancel_quietly(response)
        # Joining from the worker itself would deadlock, and close() is reachable from a handler.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_CLOSE_TIMEOUT)
        # Last, so the reader has unwound off the connection before its pool is released.
        if self._opener is not None:
            self._opener.close()

    # -- connection loop --------------------------------------------------------------------

    def _set_state(self, state: ReadyState) -> None:
        # A worker that has been stopped must not resurrect the state it was closed out of.
        if not self._stop.is_set():
            self._ready_state = state

    def _run(self) -> None:
        try:
            while True:
                failure = self._connect_once()
                if failure is None or self._stop.is_set():
                    return

                self._attempt += 1
                state = ReconnectionState(
                    attempt=self._attempt,
                    server_reconnect_delay=self._server_delay,
                    status=failure.status,
                    error=failure.error,
                )
                if not self._ask(self.should_reconnect, state, default=True):
                    self._disconnected()
                    return

                self._set_state(ReadyState.CONNECTING)
                if self._stop.wait(self._reconnect_delay(state)):
                    return
        except BaseException as error:
            # The loop is over either way, and a state left at OPEN would have callers believing
            # there is still a reader on the stream.
            self._ready_state = ReadyState.CLOSED
            # SystemExit and KeyboardInterrupt ask to unwind; they are not stream failures.
            # Logging one as "the connection stopped" would describe a problem the caller never
            # had, so they are left to travel as themselves.
            if not isinstance(error, Exception):
                raise
            # Anything else: the worker must not die without saying why.
            self._logger.error("[EventSource] The connection loop stopped unexpectedly: %r", error)

    def _connect_once(self) -> _Failure | None:
        try:
            response = self._open()
        except Exception as error:
            if self._stop.is_set():
                return None
            self._notify(self.on_error, error)
            return _Failure(error=error)

        status = response.status
        try:
            if status == 204:
                self._disconnected()
                return None
            if status >= 400:
                return _Failure(status=status)

            # Published before the first read so close() has something to interrupt.
            with self._lock:
                self._response = response
            if self._stop.is_set():
                # close() landed in the gap and saw no response to cancel. Reading now would
                # block on something nothing is going to interrupt.
                return None

            self._begin_stream()
            self._read(response)
        except Exception as error:
            if self._stop.is_set():
                return None
            self._notify(self.on_error, error)
            return _Failure(status=status, error=error)
        finally:
            with self._lock:
                self._response = None
            _close_quietly(response)

        if self._stop.is_set():
            return None
        return _Failure(status=status, error=StreamClosedError("The response stream was closed"))

    def _open(self) -> ResponseStream:
        headers = dict(self._headers)
        if self._last_event_id is not None:
            headers["Last-Event-ID"] = self._last_event_id

        response = self._transport(
            StreamRequest(
                url=self._url,
                method=self._method,
                headers=headers,
                body=self._body,
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
                follow_redirects=self._follow_redirects,
            )
        )
        if self._stop.is_set():
            # close() landed while the request was in flight.
            _close_quietly(response)
            raise StreamClosedError("The client was closed while connecting")
        return response

    def _begin_stream(self) -> None:
        self._set_state(ReadyState.OPEN)
        self._attempt = 0
        self._notify(self.on_connect)

    def _read(self, response: ResponseStream) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        parser = EventSourceParser(
            on_event=self._handle_event,
            on_comment=lambda comment: self._notify(self.on_comment, comment),
            on_retry=self._handle_retry,
            max_line_chars=self._max_line_chars,
            max_event_chars=self._max_event_chars,
        )

        for chunk in response.chunks(_READ_SIZE):
            if self._stop.is_set():
                # Whatever arrived alongside close() is not delivered.
                return
            parser.feed(decoder.decode(chunk))

        if self._stop.is_set():
            return
        parser.feed(decoder.decode(b"", True))
        parser.finish()

    def _handle_event(self, message: EventSourceMessage) -> None:
        if message.id is not None:
            self._last_event_id = message.id
        self._notify(self.on_message, message)

    def _handle_retry(self, milliseconds: int) -> None:
        # The SSE field is milliseconds; every duration this SDK exposes is seconds.
        self._server_delay = milliseconds / 1000.0

    def _disconnected(self) -> None:
        self._ready_state = ReadyState.CLOSED
        self._stop.set()
        self._notify(self.on_disconnect)

    def _reconnect_delay(self, state: ReconnectionState) -> float:
        delay = _as_seconds(self._ask(self.calculate_reconnect_delay, state, default=self._server_delay))
        if delay is None or not _MIN_RECONNECT_DELAY <= delay <= _MAX_RECONNECT_DELAY:
            self._notify(
                self.on_error,
                ValueOutOfRangeError(
                    f"The calculated reconnect delay {delay} is out of range; "
                    f"falling back to {self._server_delay} seconds"
                ),
            )
            return self._server_delay
        return delay

    # -- callback plumbing ------------------------------------------------------------------

    def _notify(self, callback: Callable[..., Any] | None, *args: Any) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:
            # A caller's handler must not take the connection down with it.
            self._logger.error("[EventSource] A %s handler raised: %r", _name(callback), error)

    def _ask(self, callback: Callable[..., _T] | None, state: ReconnectionState, *, default: _T) -> _T:
        if callback is None:
            return default
        try:
            return callback(state)
        except Exception as error:
            self._logger.error(
                "[EventSource] A %s handler raised, using %r: %r", _name(callback), default, error
            )
            return default


def _checked(callback: _C | None, name: str) -> _C | None:
    if callback is not None and not callable(callback):
        raise ConfigDirectorTypeError(f"{name} must be callable")
    return callback


def _as_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    return seconds if math.isfinite(seconds) else None


def _close_quietly(response: ResponseStream | None) -> None:
    if response is None:
        return
    # Already broken; there is nothing useful left to do about a failure here.
    with contextlib.suppress(Exception):
        response.close()


def _cancel_quietly(response: ResponseStream) -> None:
    with contextlib.suppress(Exception):
        response.cancel()


def _name(callback: Callable[..., Any]) -> str:
    return getattr(callback, "__name__", type(callback).__name__)
