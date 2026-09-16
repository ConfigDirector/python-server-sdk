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

## Documentation

Refer to the [official documentation for the Python SDK](https://docs.configdirector.com/sdks/server/python).

There is also [a quickstart guide for ConfigDirector and any of our SDKs](https://docs.configdirector.com/getting-started/quickstart).

## Sample apps

[`samples/`](samples/) holds small, runnable applications built on this SDK, one per web
framework. Start with [`samples/flask`](samples/flask/):

```bash
cd samples/flask
uv run flask --app app run --port 3600
```

## Getting Help

- [Ask a question in Discussions](https://github.com/orgs/ConfigDirector/discussions)
- [Contact support](https://www.configdirector.com/support)

[//]: # "links"
[ci-badge]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml
[pypi-badge]: https://img.shields.io/pypi/v/configdirector-server-sdk
[pypi]: https://pypi.org/project/configdirector-server-sdk/
