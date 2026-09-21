# Flask sample

A minimal [Flask](https://flask.palletsprojects.com/) app reading ConfigDirector flags through
[OpenFeature](https://openfeature.dev), using the ConfigDirector OpenFeature Python server
provider. It is the OpenFeature counterpart of the
[server SDK's Flask sample](../../configdirector-server-sdk/flask/): a `/configs` endpoint that
evaluates a handful of flags and returns them as JSON.

## Running it

```bash
cd samples/configdirector-openfeature-server-provider/flask
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

Query parameters double as the evaluation context: `id` becomes the targeting key, `name` and
`anonymous` map to the matching ConfigDirector context fields, and anything else becomes a trait:

```
/configs?id=user-123&name=Ada&plan=pro&region=eu
```

`/configs/<key>` returns the full evaluation details of one boolean flag, which is the quickest
way to see why a value was served:

```bash
curl 'http://localhost:3600/configs/temporary-feature-flag?id=user-123'
```

```json
{
  "error_code": "PROVIDER_NOT_READY",
  "error_message": "The ConfigDirector client has not received any configs yet.",
  "reason": "ERROR",
  "value": false,
  "variant": null
}
```

Run the smoke tests with `uv run pytest`.

## The provider is registered once

[`openfeature_client.py`](openfeature_client.py) creates one provider when the server starts,
hands it to OpenFeature, and shuts OpenFeature down on exit:

```python
# openfeature_client.py — runs exactly once per process
api.set_provider_and_wait(ConfigDirectorProvider(os.environ["CONFIGDIRECTOR_SERVER_KEY"], ...))
atexit.register(api.shutdown)

client = api.get_client()
```

```python
# app.py — every request handler shares that one client
from openfeature_client import client
```

Importing the module is what registers it: Python caches modules in `sys.modules`, so the code
runs once no matter how many places import `client`. Never create a provider inside a request
handler — each one opens its own connection to ConfigDirector, blocks while it initializes, and
starts out with no config state.

Process-based servers (Gunicorn workers, or `flask run --debug`'s reloader) get one provider per
process, which is correct: a connection cannot be shared across processes.

## What else it demonstrates

**Initialization is non-fatal.** `set_provider_and_wait` blocks until the initial config state
arrives or the timeout elapses. If ConfigDirector cannot be reached the app still starts, serves
the defaults it passes in, and the provider keeps connecting in the background.

**Defaults are the fallback.** Every evaluation passes the value to serve when ConfigDirector is
unreachable, so it should be the safe choice.

**Context is per-request; the provider is not.** `context_from_request()` maps query parameters
onto an OpenFeature `EvaluationContext`; a real app would build this from the authenticated
session.

**Shutdown is clean.** `api.shutdown` closes the provider, dropping its connection and flushing
pending telemetry.

## Running without a server SDK key

Without a valid key the provider never receives config state and every flag falls back to the
default this app passes in. That is the same path a production app takes when it cannot reach
ConfigDirector, so it is worth seeing: the app keeps serving, on the defaults you chose.
