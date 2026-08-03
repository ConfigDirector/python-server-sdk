# ConfigDirector Python SDK

This is the Python server SDK for [ConfigDirector](https://www.configdirector.com), a remote
configuration and feature flag service.

> **Status: stage 1 — API preview.** The public API below is complete and stable, but the
> implementation is stubbed: no network calls are made and every config evaluation returns the
> default value you supply. Code written against this release will keep working as the
> implementation lands.

## Installation

```bash
pip install configdirector-server-sdk
```

Requires Python 3.10 or newer.

## Usage

```python
from configdirector import ConfigDirectorClient, Context, Metadata

client = ConfigDirectorClient(
    "YOUR-SERVER-SDK-KEY",
    metadata=Metadata(app_name="my-awesome-app", app_version="1.0.0"),
)
client.initialize()

if client.get_value("new-checkout", False, Context(id="user-123")):
    ...
```

Create a single client for the lifetime of your application, call `initialize()` during startup,
and `close()` during shutdown. The client is safe to share across threads.

`create_client(...)` is available as an alias for the constructor, for consistency with the other
ConfigDirector SDKs.

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

### Events

`on()` also returns a `Subscription`:

```python
subscription = client.on("configs_updated", lambda event: print(event.keys))
```

Available events are `client_ready`, `configs_updated`, and `config_evaluated`. Handlers can also
be attached up front with `hooks=`:

```python
from configdirector import ClientHooks

client = ConfigDirectorClient(
    "YOUR-SERVER-SDK-KEY",
    hooks=ClientHooks(config_evaluated=lambda event: print(event.evaluation)),
)
```

### Connection options

```python
from configdirector import ConnectionOptions

client = ConfigDirectorClient(
    "YOUR-SERVER-SDK-KEY",
    connection=ConnectionOptions(mode="polling", polling_interval=30, timeout=5),
)
```

All durations are expressed in **seconds**.

### Logging

The SDK logs through the standard library logger named `configdirector`, so your application
stays in control of levels, formatting, and destinations:

```python
import logging

logging.getLogger("configdirector").setLevel(logging.DEBUG)
```

With no logging configured at all, Python still surfaces warnings and errors on `stderr`, so an
invalid SDK key never passes silently.

Pass any object implementing `ConfigDirectorLogger` to override it — including a different
stdlib logger, or the SDK's own console logger if you would rather not configure `logging`:

```python
from configdirector import create_console_logger

client = ConfigDirectorClient("YOUR-SERVER-SDK-KEY", logger=logging.getLogger("my_app.flags"))
client = ConfigDirectorClient("YOUR-SERVER-SDK-KEY", logger=create_console_logger("debug"))
```

### Shutdown

```python
client.close()
```

The client is also a context manager — it initializes on entry and closes on exit:

```python
with ConfigDirectorClient("YOUR-SERVER-SDK-KEY") as client:
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

## Development

This project uses [uv](https://docs.astral.sh/uv/).

```bash
make install     # uv sync --all-extras
make test        # pytest
make lint        # ruff check + ruff format --check
make typecheck   # mypy
make check       # lint + typecheck + test
make build       # build the sdist and wheel
```

## Documentation

Refer to the [official documentation for the Python SDK](https://docs.configdirector.com/sdks/server/python).

There is also [a quickstart guide for ConfigDirector and any of our SDKs](https://docs.configdirector.com/getting-started/quickstart).

## Getting Help

Reach out to us via https://www.configdirector.com/support
