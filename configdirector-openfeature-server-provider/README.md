# ConfigDirector OpenFeature Python Server Provider

[![CI][ci-badge]][ci] [![PyPI][pypi-badge]][pypi]

[OpenFeature](https://openfeature.dev) Python server provider for [ConfigDirector](https://www.configdirector.com), remote config and feature flags with typed values, JSON Schema validation, and safe renames of live flags. It wraps the [ConfigDirector Python server SDK](https://pypi.org/project/configdirector-server-sdk/) and requires Python 3.10 or newer.

## Install

```bash
pip install configdirector-openfeature-server-provider
```

The OpenFeature Python SDK (`openfeature-sdk`) and the ConfigDirector Python server SDK come with it as dependencies.

## Retrieve a value

```python
from configdirector_openfeature import ConfigDirectorProvider
from openfeature import api

# The server SDK key is a secret. Do not commit it to your source code.
api.set_provider_and_wait(ConfigDirectorProvider("YOUR-SERVER-SDK-KEY"))
client = api.get_client()

new_checkout = client.get_boolean_value("new-checkout", False)
```

`set_provider_and_wait` waits up to the connection timeout, 3 seconds by default, for config to arrive. If none arrives in time, or ConfigDirector rejects the server SDK key, it raises `openfeature.exception.ProviderNotReadyError` and OpenFeature reports the `ERROR` status. Evaluations then return their in-code default values with `PROVIDER_NOT_READY`. After a timeout the provider keeps connecting, and OpenFeature reports `READY` once config arrives.

To start without waiting for ConfigDirector, call `api.set_provider` instead, which initializes the provider in the background, or catch the error:

```python
import logging

from openfeature.exception import ProviderNotReadyError

try:
    api.set_provider_and_wait(ConfigDirectorProvider("YOUR-SERVER-SDK-KEY"))
except ProviderNotReadyError as error:
    logging.warning("Starting on in-code default values until ConfigDirector sends config: %s", error)
```

The provider accepts the same `metadata`, `connection`, `logger`, `log_level`, and `telemetry` options as the server SDK's `create_client`.

## Evaluation context

The OpenFeature evaluation context maps onto the ConfigDirector context used by targeting rules:

| OpenFeature | ConfigDirector |
|---|---|
| `targeting_key`, or failing that an `id` attribute | `id` |
| `kind` attribute | `kind` |
| `name` attribute | `name` |
| `traits` attribute, a mapping | `traits` |
| `anonymous` attribute, a boolean | `anonymous` |

```python
from openfeature.evaluation_context import EvaluationContext

context = EvaluationContext("user-123", {"name": "Ada", "traits": {"plan": "pro"}})
new_checkout = client.get_boolean_value("new-checkout", False, context)

device = EvaluationContext("kiosk-7", {"kind": "device"})
new_checkout = client.get_boolean_value("new-checkout", False, device)
```

Without a `kind` attribute the context is a `user`, and a `kind` inside `traits` is an ordinary trait. A kind has 1 to 64 characters, using only lowercase letters, digits, `-` and `_`. When the kind is invalid, including any kind that is not a string, the whole context is ignored: the evaluation still resolves successfully, to the value for no context, and the SDK logs an error.

## Evaluation details

| Outcome | `reason` | `error_code` |
|---|---|---|
| A value was evaluated | `TARGETING_MATCH`, with the value's id as the `variant` | |
| The config has no value | `DEFAULT` | |
| No config has that key | `ERROR` | `FLAG_NOT_FOUND` |
| The value does not match the requested type | `ERROR` | `TYPE_MISMATCH` |
| No config state has been received yet | `ERROR` | `PROVIDER_NOT_READY` |

`PROVIDER_READY` fires once, when config first arrives. The provider emits `PROVIDER_CONFIGURATION_CHANGED` whenever configs are updated, with the keys the update carried followed by the keys a full update removed.

## Test your code

Tests of code that reads flags through OpenFeature swap the provider for the in-memory one the OpenFeature Python SDK ships, `InMemoryProvider`, so the test controls the values and nothing from ConfigDirector is involved:

```python
from openfeature import api
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

api.set_provider_and_wait(InMemoryProvider({"new-checkout": InMemoryFlag("on", {"on": True, "off": False})}))
client = api.get_client()

assert client.get_boolean_value("new-checkout", False) is True
```

The provider copies its flags and has no method to change them, so a mid-test change sets a new provider. Shut OpenFeature down after each test with `api.shutdown()`. Full details are in the [testing section of the official documentation](https://docs.configdirector.com/sdks/openfeature/python#test-your-code).

## Documentation

Refer to the [official documentation for the OpenFeature Python provider](https://docs.configdirector.com/sdks/openfeature/python).

There is also [a quickstart guide for ConfigDirector and any of our SDKs](https://docs.configdirector.com/getting-started/quickstart).

## Sample apps

[`samples/configdirector-openfeature-server-provider/`](https://github.com/ConfigDirector/python-server-sdk/tree/main/samples/configdirector-openfeature-server-provider) holds small, runnable applications built on this provider. Start with [`flask`](https://github.com/ConfigDirector/python-server-sdk/tree/main/samples/configdirector-openfeature-server-provider/flask):

```bash
cd samples/configdirector-openfeature-server-provider/flask
uv run flask --app app run --port 3600
```

## Getting Help

- [Ask a question in Discussions](https://github.com/orgs/ConfigDirector/discussions)
- [Contact support](https://www.configdirector.com/support)

[//]: # "links"
[ci-badge]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml
[pypi-badge]: https://img.shields.io/pypi/v/configdirector-openfeature-server-provider
[pypi]: https://pypi.org/project/configdirector-openfeature-server-provider/
