"""Registers the one ConfigDirector provider this process uses, and exposes the OpenFeature client.

Importing this module is what creates the provider and hands it to OpenFeature. Python caches
modules in ``sys.modules``, so that happens exactly once per process no matter how many modules
import ``client``. Never create a provider inside a request handler: each one holds its own
connection to ConfigDirector and starts out with no config state.
"""

from __future__ import annotations

import atexit
import logging
import os
from typing import cast

from configdirector import ConnectionMode, ConnectionOptions, Metadata
from configdirector_openfeature import ConfigDirectorProvider
from dotenv import load_dotenv
from openfeature import api
from openfeature.provider import ProviderStatus

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

logger = logging.getLogger(__name__)

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

api.set_provider_and_wait(provider)
atexit.register(api.shutdown)

client = api.get_client()

logger.info(
    "ConfigDirector provider registered once for pid %d (ready=%s)",
    os.getpid(),
    client.get_provider_status() == ProviderStatus.READY,
)
