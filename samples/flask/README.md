# Flask sample

A minimal [Flask](https://flask.palletsprojects.com/) app using the ConfigDirector Python
server SDK. It mirrors the `openfeature-server` sample in the JavaScript SDKs: a single
`/configs` endpoint that evaluates a handful of configs and returns them as JSON.

## Running it

```bash
cd samples/flask
cp .env.example .env      # optional — the sample runs without a real key
uv run flask --app app run --port 3600
```

Then:

```bash
curl 'http://localhost:3600/configs?id=user-123&plan=pro'
```

```json
{
  "day-of-the-week-config": "Friday",
  "integer-config": 10,
  "json-value-config": {},
  "permanent-kill-switch": false,
  "temporary-feature-flag": true
}
```

Query parameters double as the evaluation context — `id`, `name`, and `anonymous` map to the
matching `Context` fields, and anything else becomes a trait:

```
/configs?id=user-123&name=Ada&plan=pro&region=eu
```

Run the smoke tests with `uv run pytest`.

## The client is a singleton

This is the single most important thing the sample shows, so it lives in its own module:
[`configdirector_client.py`](configdirector_client.py). Create one client when the server
starts, share it for the whole lifetime of the process, and close it on shutdown.

```python
# configdirector_client.py — runs exactly once per process
client = create_client(os.environ["CONFIGDIRECTOR_SERVER_KEY"], ...)
client.initialize()
atexit.register(client.close)
```

```python
# app.py — every request handler shares that one instance
from configdirector_client import client
```

Importing the module is what creates it: Python caches modules in `sys.modules`, so the code
runs once no matter how many places import `client`. Never call `create_client()` inside a
request handler — each client opens its own connection, blocks on `initialize()`, starts
out not-ready (so it serves defaults), and drops its batched telemetry when it is discarded.

Concurrency is not a reason to make more of them: the client is thread-safe, so every worker
thread shares this one safely. Process-based servers (Gunicorn workers, or `flask run --debug`'s
reloader) get one client per process, which is correct — a client cannot be shared across
processes.

Evaluation itself is cheap. `get_value()` reads config state the client already holds in memory,
with no network call on the request path, which is what makes it safe to call several times per
request.

## What else it demonstrates

**Initialization is explicit and non-fatal.** `initialize()` blocks until the initial config
state arrives or the timeout elapses, and never raises on connection failure. The sample checks
`is_ready`, logs a warning, and carries on serving defaults.

**Defaults are the fallback.** Every `get_value()` call passes the value to serve when
ConfigDirector is unreachable, so it should be the safe choice. Its type also decides how the
config value is parsed.

**Context is per-request; the client is not.** `context_from_request()` maps query parameters
onto a `Context`; a real app would build this from the authenticated session.

**Logging is yours to configure.** The sample passes its own logger to the client, so SDK output
lands in the application's logging namespace rather than the SDK's:

```python
sdk_logger = logging.getLogger("flask_sample.configdirector")
sdk_logger.setLevel(os.environ.get("CONFIGDIRECTOR_LOG_LEVEL", "INFO"))

client = create_client(..., logger=sdk_logger)
```

```
flask_sample.configdirector DEBUG No config state found for 'integer-config', returning default value 10
```

Any object with `debug`/`info`/`warning`/`error` methods works, and a stdlib `Logger` satisfies
that. Omit `logger=` entirely and the SDK falls back to the standard library logger named
`configdirector`, leaving the level to your application — or pass `log_level=` if you would
rather not configure the `logging` module at all. Set `CONFIGDIRECTOR_LOG_LEVEL=DEBUG` to watch
every evaluation as it happens.

**Shutdown is clean.** `atexit` closes the client, dropping connections and flushing pending
telemetry. A production deployment would also hook its server's worker-exit signal.

The SDK also supports watching configs for changes and subscribing to client events; see the
[SDK README](../../README.md) for `watch()` and `on()`.

## Running without a server SDK key

Without a valid key the client stays unready and every config falls back to the default this
app passes in. That is the same path a production app takes when it cannot reach ConfigDirector,
so it is worth seeing: the app keeps serving, on the defaults you chose.
