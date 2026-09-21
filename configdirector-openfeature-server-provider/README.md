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

`set_provider_and_wait` needs `openfeature-sdk` 0.10 or newer. On an older version use `api.set_provider`, which waits for the provider to initialize there.

The provider accepts the same `metadata`, `connection`, `logger`, `log_level`, and `telemetry` options as the server SDK's `create_client`.

## Evaluation context

The OpenFeature evaluation context maps onto the ConfigDirector context used by targeting rules:

| OpenFeature | ConfigDirector |
|---|---|
| `targeting_key`, or failing that an `id` attribute | `id` |
| `name` attribute | `name` |
| `traits` attribute, a mapping | `traits` |
| `anonymous` attribute, a boolean | `anonymous` |

```python
from openfeature.evaluation_context import EvaluationContext

context = EvaluationContext("user-123", {"name": "Ada", "traits": {"plan": "pro"}})
new_checkout = client.get_boolean_value("new-checkout", False, context)
```

## Evaluation details

| Outcome | `reason` | `error_code` |
|---|---|---|
| A value was evaluated | `TARGETING_MATCH`, with the value's id as the `variant` | |
| The config has no value | `DEFAULT` | |
| No config has that key | `ERROR` | `FLAG_NOT_FOUND` |
| The value does not match the requested type | `ERROR` | `TYPE_MISMATCH` |
| No config state has been received yet | `ERROR` | `PROVIDER_NOT_READY` |

If the first config state does not arrive within the configured timeout, initialization still completes and evaluations return their defaults. The provider keeps connecting, and emits `PROVIDER_READY` once config state arrives. It emits `PROVIDER_CONFIGURATION_CHANGED`, with the keys that changed, whenever configs are updated.

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
