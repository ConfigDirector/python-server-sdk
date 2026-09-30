# Flask sample

A minimal [Flask](https://flask.palletsprojects.com/) app using the ConfigDirector Python
server SDK. It mirrors the `openfeature-server` sample in the JavaScript SDKs: a single
`/configs` endpoint that evaluates a handful of configs and returns them as JSON.

## Running it

```bash
cd samples/configdirector-server-sdk/flask
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

Run the tests with `uv run pytest`.

## The client is a singleton

This is the single most important thing the sample shows, so it lives in its own module:
[`configdirector_client.py`](configdirector_client.py). Create one client, share it for the
whole lifetime of the process, and close it on shutdown.

```python
# configdirector_client.py — the first call creates and initializes the client
def get_client() -> ConfigDirectorClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = _create_and_initialize_client()
        return _client
```

```python
# app.py — every request handler shares that one instance
from configdirector_client import get_client
```

The getter is created on first use and cached for the rest of the process; the lock makes sure
two first requests arriving together still end up with one client. Never call `create_client()`
inside a request handler — each client opens its own connection, blocks on `initialize()`, starts
out not-ready (so it serves defaults), and drops its batched telemetry when it is discarded.

A getter rather than a module-level `client` is also what makes the app testable: a test
replaces `get_client` with a client of its own, whereas a client created at import runs before
any test can intervene. See [Testing](#testing) below.

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
[SDK README](../../../configdirector-server-sdk/README.md) for `watch()` and `on()`.

## Testing

[`test_app.py`](test_app.py) tests the app the way an application using the SDK tests itself:
with a **test client** from `configdirector.testing`, the SDK's real client over an in-memory
connection the test controls. No network, no SDK key, no thread.

```python
from configdirector.testing import create_test_client

with create_test_client({"integer-config": 42}) as test_client:
    test_client.client.initialize()
    monkeypatch.setattr(app_module, "get_client", lambda: test_client.client)

    assert app.test_client().get("/configs").get_json()["integer-config"] == 42

    test_client.set_value("integer-config", 7)
    assert app.test_client().get("/configs").get_json()["integer-config"] == 7
```

`app.py` binds `get_client` with `from configdirector_client import get_client`, so the test
patches the name in `app`, the module that calls it. `fail_initialization()` is how the tests
cover the unreachable path: the client stays unready and the app serves the defaults it chose.

## Running without a server SDK key

Without a valid key the client stays unready and every config falls back to the default this
app passes in. That is the same path a production app takes when it cannot reach ConfigDirector,
so it is worth seeing: the app keeps serving, on the defaults you chose.
