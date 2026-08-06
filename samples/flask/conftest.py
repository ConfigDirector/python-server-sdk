"""Keeps the sample's tests off the network.

Importing the app creates and initializes the client, so these have to be set before pytest
collects anything. Pointing the SDK at an address nothing is listening on makes initialization
fail immediately instead of waiting out its timeout, and exercises the same path a production
app takes when ConfigDirector is unreachable: it serves the defaults you passed in.

The telemetry warning this prints once the run has been going for a few seconds is that same
path, not a failure: the collector's background flush finds nothing listening, says so, and
leaves the app alone.
"""

from __future__ import annotations

import os

os.environ.setdefault("CONFIGDIRECTOR_BASE_URL", "http://127.0.0.1:1")
os.environ.setdefault("CONFIGDIRECTOR_MODE", "one-time")
os.environ.setdefault("CONFIGDIRECTOR_TIMEOUT", "0.5")
