# ConfigDirector Python SDK

This is the Python server SDK for [ConfigDirector](https://www.configdirector.com), a remote
configuration and feature flag service.

> **Status: pre-release.** Config retrieval, evaluation, and telemetry reporting are all
> implemented. The API may still change before 1.0.

## Installation

```bash
pip install configdirector-server-sdk
```

Requires Python 3.10 or newer.

## Usage

```python
from configdirector import Context, Metadata, create_client

client = create_client(
    "YOUR-SERVER-SDK-KEY",
    metadata=Metadata(app_name="my-awesome-app", app_version="1.0.0"),
)
client.initialize()

if client.get_value("new-checkout", False, Context(id="user-123")):
    ...
```

`create_client(...)` is how you create a client, and matches the other ConfigDirector SDKs.
`ConfigDirectorClient` is the interface a client satisfies — annotate against it, but build one
with `create_client`, since an interface cannot be instantiated:

```python
from configdirector import ConfigDirectorClient


def in_new_checkout(client: ConfigDirectorClient, user_id: str) -> bool:
    return client.get_value("new-checkout", False, Context(id=user_id))
```

Create a single client for the lifetime of your application, call `initialize()` during startup,
and `close()` during shutdown. The client is safe to share across threads.

### Evaluating configs

The type of the default you pass determines the type the config is parsed as, and is returned
whenever config state is unavailable.

```python
retries = client.get_value("max-retries", 3)
theme = client.get_value("theme", "light")
limits = client.get_value("rate-limits", {"per_minute": 60})
```

### Watching for changes

`watch()` returns a `Subscription`. Close it to stop watching, or use it as a context manager to
scope the watch to a block.

```python
def on_change(value: bool) -> None:
    print(f"new-checkout is now {value}")


subscription = client.watch("new-checkout", False, on_change)
...
subscription.close()

# or, scoped to a block
with client.watch("new-checkout", False, on_change):
    ...
```

The callback runs on the SDK's background connection thread rather than the thread that
registered it, so keep it quick and thread-safe. An exception it raises is logged and does not
affect other watchers.

### Reading every config at once

`get_all_configs()` returns the evaluated `ConfigState` for every known key, intended for
server-side rendering hydration. It records no telemetry, and returns an empty mapping until the
client is ready.

```python
states = client.get_all_configs(context=Context(id="user-123"))
states = client.get_all_configs(config_keys=["new-checkout", "theme"])
```

### Events

`on()` also returns a `Subscription`:

```python
subscription = client.on("configs_updated", lambda event: print(event.keys))
```

Available events are `client_ready`, `configs_updated`, and `config_evaluated`. Handlers can also
be attached up front with `hooks=`:

```python
from configdirector import ClientHooks

client = create_client(
    "YOUR-SERVER-SDK-KEY",
    hooks=ClientHooks(config_evaluated=lambda event: print(event.evaluation)),
)
```

### Connection options

```python
from configdirector import ConnectionOptions

client = create_client(
    "YOUR-SERVER-SDK-KEY",
    connection=ConnectionOptions(mode="polling", polling_interval=30, timeout=5),
)
```

| Mode | Behaviour |
|---|---|
| `streaming` (default) | Holds a connection open and receives updates as configs change in the dashboard |
| `polling` | Fetches config state during initialization, then re-fetches every `polling_interval` |
| `one-time` | Fetches config state during initialization only, and never refreshes it |

All durations are expressed in **seconds**. Set `url=` only when routing through a proxy to
reach ConfigDirector.

### Telemetry

The SDK reports which configs your application evaluated back to ConfigDirector. This is what
powers the usage insights in the dashboard — which configs are in use, what they evaluate to,
and which users they were evaluated for.

Evaluations are collected in memory and reported on an interval by a background thread, so
`get_value()` never waits on the network. Identical evaluations are collapsed into a single
entry with a count, and values too large to send inline are reported by a digest rather than in
full. Contexts marked `anonymous=True` are used for targeting but never reported.

It is unlikely these settings need adjusting, but if your application performs a large number of
evaluations per second they let you trade memory footprint against how often telemetry requests
are made:

```python
from configdirector import TelemetryOptions

client = create_client(
    "YOUR-SERVER-SDK-KEY",
    telemetry=TelemetryOptions(event_queue_limit=10_000, flush_interval=15),
)
```

| Option | Default | Notes |
|---|---|---|
| `event_queue_limit` | `5000` | Between 100 and 100,000. Once reached, the oldest events are dropped and the number dropped is reported |
| `flush_interval` | `30` | **Seconds** between reports |

Calling `close()` reports whatever was collected since the last flush, so shutting the client
down cleanly is what keeps the tail of a short-lived process from being lost.

### Logging

The SDK logs through the standard library logger named `configdirector`, so your application
stays in control of levels, formatting, and destinations:

```python
import logging

logging.getLogger("configdirector").setLevel(logging.DEBUG)
```

The SDK sets no level of its own, so this logger follows the usual `logging` rules. With nothing
configured at all, Python still surfaces warnings and errors on `stderr`, so an invalid SDK key
never passes silently.

If you would rather not configure `logging`, `log_level` sets a level on that logger for you:

```python
client = create_client("YOUR-SERVER-SDK-KEY", log_level="DEBUG")
```

Pass any object implementing `ConfigDirectorLogger` to override the logger entirely — a
different stdlib logger, or your own adapter:

```python
client = create_client("YOUR-SERVER-SDK-KEY", logger=logging.getLogger("my_app.flags"))
```

### Shutdown

```python
client.close()
```

Closing the client closes its connection to ConfigDirector, reports any telemetry collected
since the last flush, and cancels every event and config key subscription. Safe to call more
than once.

The client is also a context manager — it initializes on entry and closes on exit:

```python
with create_client("YOUR-SERVER-SDK-KEY") as client:
    if client.get_value("new-checkout", False):
        ...
```

### Errors

Everything the SDK raises inherits from `ConfigDirectorError`. Argument validation errors also
inherit from the built-in exception you would expect, so ordinary handlers keep working:

| Exception | Also a | Raised when |
|---|---|---|
| `ConfigDirectorValidationError` | `ValueError` | An argument has an unusable value (empty config key, unknown event name) |
| `ConfigDirectorTypeError` | `TypeError` | An argument has an unsupported type (a `set` default, a non-callable handler) |
| `ConfigDirectorConnectionError` | — | The SDK cannot reach the ConfigDirector servers |
| `ConfigDirectorInitializationError` | — | The client cannot be initialized |

## Sample apps

[`samples/`](samples/) holds small, runnable applications built on this SDK, one per web
framework. Start with [`samples/flask`](samples/flask/):

```bash
cd samples/flask
uv run flask --app app run --port 3600
curl 'http://localhost:3600/configs?id=user-123&plan=pro'
```

## Development

This project uses [uv](https://docs.astral.sh/uv/).

```bash
make install     # uv sync --all-extras
make hooks       # install the pre-push hook (once, per clone)

make test        # pytest
make lint        # ruff check + ruff format --check
make typecheck   # mypy
make samples     # typecheck and test every app under samples/
make build       # build the sdist and wheel
make dist-check  # build, validate the metadata, import the wheel in a clean env

make check       # lint + typecheck + test — the fast loop
make check-all   # everything CI runs
```

CI and the pre-push hook both call these targets rather than repeating the commands, so the
three cannot drift apart.

### Pre-push hook

`make hooks` points `core.hooksPath` at [`.githooks/`](.githooks/), so
[`.githooks/pre-push`](.githooks/pre-push) runs `make check-all` before every push: lockfile,
lint, formatting, types, tests, a real distribution build, and every sample app. It takes a few
seconds.

Pushes that only delete remote refs skip the checks. To bypass it for a single push:

```bash
git push --no-verify
```

Note that the hook checks your working tree, not the commits being pushed, so uncommitted
changes count.

## Documentation

Refer to the [official documentation for the Python SDK](https://docs.configdirector.com/sdks/server/python).

There is also [a quickstart guide for ConfigDirector and any of our SDKs](https://docs.configdirector.com/getting-started/quickstart).

## Getting Help

Reach out to us via https://www.configdirector.com/support
