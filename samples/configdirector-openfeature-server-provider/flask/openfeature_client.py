"""Registers the one ConfigDirector provider this process uses, and hands out the OpenFeature client.

``get_client()`` registers the provider on its first call and returns OpenFeature's client; every
later call returns the client again without touching the provider. Never create a provider inside
a request handler: each one holds its own connection to ConfigDirector and starts out with no
config state.

Why a getter rather than registering the provider when the module is imported: importing would
run the real provider before a test can intervene. A getter is one name a test can replace, which
is how ``test_app.py`` points the app at OpenFeature's own in-memory provider. The first request
pays for the provider's initialization; a deployment that would rather pay it at startup calls
``get_client()`` from its server's worker-start hook (Gunicorn's ``post_worker_init``, for
instance).
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import cast

from configdirector import ConnectionMode, ConnectionOptions, Metadata
from configdirector_openfeature import ConfigDirectorProvider
from dotenv import load_dotenv
from openfeature import api
from openfeature.client import OpenFeatureClient
from openfeature.provider import ProviderStatus

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

logger = logging.getLogger(__name__)

_provider_registered = False
_provider_lock = threading.Lock()


def get_client() -> OpenFeatureClient:
    """The OpenFeature client, with the ConfigDirector provider registered on the first call."""
    global _provider_registered
    with _provider_lock:
        if not _provider_registered:
            _register_provider()
            _provider_registered = True
        return api.get_client()


def _register_provider() -> None:
    provider = ConfigDirectorProvider(
        os.environ.get("CONFIGDIRECTOR_SERVER_KEY", "fake-sample-key"),
        metadata=Metadata(app_name="openfeature-flask-sample", app_version="1.0.0"),
        connection=ConnectionOptions(
            url=os.environ.get("CONFIGDIRECTOR_BASE_URL") or None,
            mode=cast(ConnectionMode, os.environ.get("CONFIGDIRECTOR_MODE", "streaming")),
            timeout=float(os.environ.get("CONFIGDIRECTOR_TIMEOUT", "3")),
        ),
        log_level=os.environ.get("CONFIGDIRECTOR_LOG_LEVEL", "INFO"),
    )

    # Blocks until the provider has initialized or its timeout has elapsed, so the first request
    # is not answered with defaults while the initial config state is still in flight.
    api.set_provider_and_wait(provider)
    atexit.register(api.shutdown)

    logger.info(
        "ConfigDirector provider registered once for pid %d (ready=%s)",
        os.getpid(),
        api.get_client().get_provider_status() == ProviderStatus.READY,
    )
