# ConfigDirector Python SDK

[![CI][ci-badge]][ci] [![PyPI][pypi-badge]][pypi]

Python server SDK for [ConfigDirector](https://www.configdirector.com), remote config and feature flags with typed values, JSON Schema validation, and safe renames of live flags. Start free, no card required.

## Install

```bash
pip install configdirector-server-sdk
```

## Retrieve a value

```python
from configdirector import create_client

# The server SDK key is a secret. Do not commit it to your source code.
client = create_client("YOUR-SERVER-SDK-KEY")
client.initialize()

new_checkout = client.get_value("new-checkout", False)
```

Full details are in the [official documentation](https://docs.configdirector.com/sdks/server/python).

## Test your code

`configdirector.testing` creates a **test client**: the SDK's real client connected to an in-memory
server that your test controls, with no network connection, no telemetry, and no thread. Seed
values, change them mid-test so watches and `configs_updated` handlers fire, and hold or fail
initialization to test loading states. It ships in the package, so there is nothing else to install.

```python
from configdirector.testing import create_test_client

with create_test_client({"new-checkout": True}) as test_client:
    service = CheckoutService(test_client.client)
    test_client.client.initialize()

    assert service.is_new_checkout_enabled("user-123")

    test_client.set_value("new-checkout", False)
    assert not service.is_new_checkout_enabled("user-123")
```

`test_client.client` is a `ConfigDirectorClient`, so it goes anywhere your code accepts one. It
starts uninitialized, like a production client, because the code under test usually owns the call
to `initialize`; with no hold or failure armed, `initialize` completes at once with the stored
values. The test client is a context manager that closes its client on exit.

### Values

`create_test_client`, `set_value`, and `replace_values` take native values, and the config type
follows from each value's type: a `bool`; an `int` (an integer config); a `float` (a float
config); a `str`; or a `dict` with `str` keys or a `list` (a JSON config). A `str` is always a
string config, so JSON text meant as a JSON config is given as `json.loads(text)`. Every value is
served as an unconditional config, so every context receives the same value; a test that needs
different values per context is written as one test per value. `None`, an unsupported type such
as a `tuple` or a `set`, or a `dict` with a non-`str` key raise `ConfigDirectorTypeError`; a blank
key, a non-finite number, or an integer with too many digits to write out raise
`ConfigDirectorValidationError`. In every case nothing changes.

Reads behave as they do in production: `set_value("k", True)` read as a string returns the in-code
default value with the `type-mismatch` reason, `set_value("k", 2.5)` read with an `int` default
returns the default with the `invalid-number` reason, and `set_value("k", "")` serves the in-code
default value with the `value-missing` reason. Reasons arrive on the `config_evaluated` event. JSON
objects keep their insertion order.

### Controls

| Control | Effect |
| --- | --- |
| `set_value(key, value)` | Stores the value and, once the client is connected, delivers an update carrying only `key`. Watches of `key`, `configs_updated` handlers, and reads see it before the call returns. |
| `remove_value(key)` | Removes the value and delivers a full update without it. Reads return the in-code default value with the `config-state-missing` reason, watches of `key` receive the default, and `configs_updated` lists `key` in `removed_keys`. |
| `replace_values(values)` | Replaces every stored value, disarms any armed hold or failure, and delivers a full update. Use it to reset a test client shared across tests. |
| `hold_initialization()` | The next `initialize` waits until `complete_initialization()` or `fail_initialization()`, or until the client's timeout elapses. `initialize` blocks, so a test calls it on another thread. |
| `complete_initialization()` | Delivers the stored values to the held `initialize`, on the calling thread, so the client is ready when the call returns. Called while a hold is armed but not picked up, it disarms the hold. |
| `fail_initialization()` | Fails the held `initialize` the way an invalid SDK key does: it completes promptly, the client is not ready, and the error is logged. Called with no `initialize` held, it arms the next one to fail. |

After a failed attempt, the next `initialize` succeeds and delivers the values stored in the
meantime.

### Options

`create_test_client(values, timeout=..., logger=...)` takes `timeout` (the client's connection
timeout in seconds, which bounds how long a held `initialize` waits; defaults to the SDK's
production timeout, and a timeout given to `initialize` itself takes precedence) and `logger`
(defaults to the standard library logger named `configdirector`, so pytest's `caplog` captures it).

### Module-level clients

An application that creates and initializes its client when a module loads runs the real client
before any test can intervene, which opens a connection and starts threads. A `monkeypatch` also
has to reach every module that bound the name: `from configdirector_client import client` binds its
own `client`, so patching `configdirector_client.client` does not change it. Structure the
application around a lazy getter instead, and replace that in tests:

```python
_client: ConfigDirectorClient | None = None


def get_client() -> ConfigDirectorClient:
    global _client
    if _client is None:
        _client = create_client(os.environ["CONFIGDIRECTOR_SERVER_SDK_KEY"])
        _client.initialize()
    return _client
```

```python
def test_new_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    with create_test_client({"new-checkout": True}) as test_client:
        test_client.client.initialize()
        monkeypatch.setattr(app, "get_client", lambda: test_client.client)
        ...
```

### What to expect

- The first update is delivered while `initialize` connects, so watches registered before
  `initialize` run before it returns, and `configs_updated` fires before `client_ready`.
- Watches and handlers run on the thread that calls `set_value`, `remove_value`,
  `replace_values`, `complete_initialization`, or `initialize`, not on a transport thread.
- A held `initialize` that times out, or that is interrupted by `close`, leaves the client not
  ready until the next `initialize`, and logs the SDK's timeout warning; production streaming
  would keep retrying in the background. Readiness is sticky: once the client is ready, a later
  held, failed, or timed-out attempt leaves it ready with its previous values, and completing such
  an attempt fires no `client_ready`.
- Watches fire on every update carrying their key, whether or not the value changed, as in
  production. `remove_value` and `replace_values` deliver a full update, so they also fire the
  watches of every remaining key.
- An exception raised by a watch or handler is logged and does not propagate, as with the
  production transports.
- After `close`, `is_ready` is false, `get_value` serves the last values, `get_all_configs`
  returns an empty dict, `initialize` raises `ConfigDirectorValidationError`, every watch and
  event handler has been removed, the test client's controls are silent no-ops, and no SDK thread
  is left running.

## Documentation

Refer to the [official documentation for the Python SDK](https://docs.configdirector.com/sdks/server/python).

There is also [a quickstart guide for ConfigDirector and any of our SDKs](https://docs.configdirector.com/getting-started/quickstart).

## Sample apps

[`samples/configdirector-server-sdk/`](https://github.com/ConfigDirector/python-server-sdk/tree/main/samples/configdirector-server-sdk)
holds small, runnable applications built on this SDK, one per web framework. Start with
[`flask`](https://github.com/ConfigDirector/python-server-sdk/tree/main/samples/configdirector-server-sdk/flask):

```bash
cd samples/configdirector-server-sdk/flask
uv run flask --app app run --port 3600
```

## OpenFeature

To read ConfigDirector flags through the [OpenFeature](https://openfeature.dev) API, use
[`configdirector-openfeature-server-provider`](https://pypi.org/project/configdirector-openfeature-server-provider/),
which is built on this SDK.

## Getting Help

- [Ask a question in Discussions](https://github.com/orgs/ConfigDirector/discussions)
- [Contact support](https://www.configdirector.com/support)

[//]: # "links"
[ci-badge]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml
[pypi-badge]: https://img.shields.io/pypi/v/configdirector-server-sdk
[pypi]: https://pypi.org/project/configdirector-server-sdk/
