from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from typing import NoReturn

from .._bundle import parse_bundle
from .._http import HttpResponse
from ..errors import ConfigDirectorConnectionError, ConfigDirectorValidationError
from .base import (
    REQUEST_HEADERS,
    TransportOptions,
    fatal_status_error,
    is_fatal_status,
    json_body,
    resolve,
)

__all__ = ["OneTimeTransport", "PollingTransport"]

_PATH = "server/polling/v1"

# How long close() waits for a poll already in flight to return.
_JOIN_TIMEOUT = 5.0


class PollingTransport:
    def __init__(self, options: TransportOptions) -> None:
        self._options = options
        self._logger = options.logger
        self._url = resolve(options.base_url, _PATH)
        self._interval = max(options.polling_interval, 0.0)
        self._last_update_timestamp: str | None = None
        self._session_id = str(uuid.uuid4())
        self._fatal = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def connect(self, timeout: float) -> None:
        try:
            self._fetch(timeout)
        finally:
            # A transient failure on the first fetch must not leave the SDK without a
            # connection, so polling starts either way. An unrecoverable one has already closed
            # the transport and must not be retried.
            if not self._has_failed_fatally():
                self._start_polling(timeout)

    @property
    def is_connected(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def session_id(self) -> str:
        return self._session_id

    def close(self) -> None:
        with self._lock:
            thread, self._thread = self._thread, None
        self._stop.set()
        # Joining from the polling thread itself would deadlock.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_JOIN_TIMEOUT)

    # -- polling loop -----------------------------------------------------------------------

    def _start_polling(self, timeout: float) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._poll,
                args=(timeout,),
                name="configdirector-polling",
                daemon=True,
            )
            self._thread.start()

    def _poll(self, timeout: float) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._fetch(timeout)
            except ConfigDirectorConnectionError as error:
                self._logger.error("[PollingTransport] Error during polling: %r", error)
            except Exception as error:  # the polling thread must not die without saying why
                self._logger.error("[PollingTransport] Polling stopped unexpectedly: %r", error)
                return
            if self._has_failed_fatally():
                return

    def _fetch(self, timeout: float) -> None:
        if self._has_failed_fatally():
            self._logger.warning(
                "[PollingTransport] There was a prior unrecoverable error. Ignoring attempt to reconnect."
            )
            return

        response = self._post(timeout)
        if not response.ok:
            if is_fatal_status(response.status):
                self._fail_fatally(fatal_status_error(response.status, response.body))
            raise ConfigDirectorConnectionError(
                f"Connection failed with status: {response.status}", response.status
            )

        # 204 means the server has nothing newer than the timestamp that was sent.
        if response.status != 200:
            return

        try:
            bundle = parse_bundle(response.body, self._logger)
        except ValueError as error:
            raise ConfigDirectorConnectionError(
                f"Failed to parse the response from the server: {error}"
            ) from error

        if bundle.timestamp is not None:
            with self._lock:
                self._last_update_timestamp = bundle.timestamp
        self._options.on_bundle(bundle)

    def _post(self, timeout: float) -> HttpResponse:
        with self._lock:
            last_update_timestamp = self._last_update_timestamp
        body = json_body(
            {
                "serverSdkKey": self._options.server_sdk_key,
                "metaContext": self._options.meta_context,
                "lastUpdateTimestamp": last_update_timestamp,
                "sessionId": self._session_id,
            }
        )
        try:
            # Network-level failures — refused, unresolved, timed out — arrive as
            # ConfigDirectorConnectionError and are left to propagate: all are worth retrying.
            return self._options.http.post(self._url, body, REQUEST_HEADERS, timeout)
        except ConfigDirectorValidationError as error:
            # The URL itself is unusable, so every retry would fail identically.
            self._fail_fatally(
                ConfigDirectorConnectionError(
                    f"Connection failed with an unusable URL '{self._url}': {error}. "
                    f"This is an unrecoverable error, retry attempts will be ignored."
                )
            )

    def _has_failed_fatally(self) -> bool:
        with self._lock:
            return self._fatal

    def _fail_fatally(self, error: ConfigDirectorConnectionError) -> NoReturn:
        with self._lock:
            self._fatal = True
        # Deliberately outside the lock: close() takes it too, and this Lock is not reentrant.
        self.close()
        raise error


class OneTimeTransport(PollingTransport):
    def __init__(self, options: TransportOptions) -> None:
        super().__init__(replace(options, polling_interval=0.0))
