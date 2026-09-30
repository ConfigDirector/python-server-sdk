"""Creates the one ConfigDirector client this process uses.

**The client is a singleton.** Create it once, share it for the whole lifetime of the process,
and close it on shutdown. ``get_client()`` is that singleton: the first call creates and
initializes the client, every later call returns the same instance.

Why it matters:

* **Each client holds its own connection.** In streaming mode it keeps a long-lived connection
  open to receive config updates; a client per request would open, and abandon, one per request.
* **Initialization does network I/O.** ``initialize()`` blocks until the initial config state
  arrives. Paying that on every request would add latency to every response.
* **A fresh client is never ready.** Until its first config state arrives, every config resolves
  to the default — so per-request clients would serve defaults more or less forever.
* **Telemetry is batched per client.** ConfigDirector's dashboard insights depend on those
  batches being flushed; short-lived clients drop them.
* **Watches and hooks are registered on the instance.** They only fire for as long as the client
  they were registered on is alive.

So: never call ``create_client()`` inside a request handler.

Why a getter rather than a module-level ``client``: creating the client when the module is
imported runs the real client before a test can intervene. A getter is created on first use and
is one name a test can replace, which is how ``test_app.py`` hands the app a test client from
``configdirector.testing``. The first request pays for initialization; a deployment that would
rather pay it at startup calls ``get_client()`` from its server's worker-start hook (Gunicorn's
``post_worker_init``, for instance).

Concurrency is not a reason to make more of them — the client is thread-safe, so every worker
thread in the WSGI server shares this one instance safely, and the lock below makes sure two
first requests arriving together still end up with one client. Process-based servers (Gunicorn
workers, ``flask run --debug``'s reloader) do get one client each, which is correct: a client
cannot be shared across processes.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import cast

from configdirector import ConfigDirectorClient, ConnectionMode, ConnectionOptions, Metadata, create_client
from dotenv import load_dotenv

load_dotenv()

# Logging is configured here, not in app.py, because this module is the first thing to log —
# anything emitted before a handler exists is dropped.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

logger = logging.getLogger(__name__)

_client: ConfigDirectorClient | None = None
_client_lock = threading.Lock()


def get_client() -> ConfigDirectorClient:
    """The process-wide client, created and initialized on the first call."""
    global _client
    with _client_lock:
        if _client is None:
            _client = _create_and_initialize_client()
        return _client


def _create_and_initialize_client() -> ConfigDirectorClient:
    # The logger handed to the client. Left to itself the SDK logs to the standard library logger
    # named "configdirector"; passing one in puts its output under this application's own logging
    # namespace instead, where existing handlers, filters, and level config already apply.
    #
    # Any object with debug/info/warning/error methods works, and a stdlib Logger satisfies that.
    # Passing `log_level=` instead of `logger=` is the shortcut when you would rather not configure
    # the logging module at all.
    sdk_logger = logging.getLogger("flask_sample.configdirector")
    sdk_logger.setLevel(os.environ.get("CONFIGDIRECTOR_LOG_LEVEL", "INFO"))

    # Connection options read from the environment, the way a real deployment would supply them —
    # a proxy URL in one environment, a shorter timeout in another. The defaults here are the SDK's
    # own, so an app that needs none of this can leave `connection` out entirely.
    connection = ConnectionOptions(
        # Only needed when routing through a proxy to reach ConfigDirector.
        url=os.environ.get("CONFIGDIRECTOR_BASE_URL") or None,
        mode=cast(ConnectionMode, os.environ.get("CONFIGDIRECTOR_MODE", "streaming")),
        timeout=float(os.environ.get("CONFIGDIRECTOR_TIMEOUT", "3")),
    )

    # Creating the client makes no network calls.
    client = create_client(
        os.environ.get("CONFIGDIRECTOR_SERVER_KEY", "fake-sample-key"),
        metadata=Metadata(app_name="flask-sample", app_version="1.0.0"),
        connection=connection,
        logger=sdk_logger,
    )

    # Blocks until the initial config state arrives or the timeout elapses. This never raises on
    # connection failure — check `is_ready` to find out whether state was actually received.
    client.initialize()

    logger.info("ConfigDirector client created once for pid %d (ready=%s)", os.getpid(), client.is_ready)
    if not client.is_ready:
        logger.warning("ConfigDirector is not ready — every config will resolve to its default")

    # Closing drops the connection and flushes pending telemetry. `atexit` covers the normal
    # shutdown path; a production deployment would also hook its server's worker-exit signal.
    atexit.register(client.close)
    return client
