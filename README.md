# ConfigDirector Python SDKs

[![CI][ci-badge]][ci]

Python packages for [ConfigDirector](https://www.configdirector.com), remote config and feature flags with typed values, JSON Schema validation, and safe renames of live flags. Start free, no card required.

| Package | PyPI | Description |
|---|---|---|
| [configdirector-server-sdk](configdirector-server-sdk/) | [![PyPI][sdk-badge]][sdk-pypi] | The Python server SDK |
| [configdirector-openfeature-server-provider](configdirector-openfeature-server-provider/) | [![PyPI][provider-badge]][provider-pypi] | [OpenFeature](https://openfeature.dev) server provider, built on the server SDK |

Each package has its own README, changelog, version, and release. Pick the server SDK to use ConfigDirector directly, or the OpenFeature provider if your application reads flags through the OpenFeature API.

## Sample apps

[`samples/`](samples/) holds small, runnable applications, grouped by the package they demonstrate.

## Getting Help

- [Ask a question in Discussions](https://github.com/orgs/ConfigDirector/discussions)
- [Contact support](https://www.configdirector.com/support)

[//]: # "links"
[ci-badge]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/ConfigDirector/python-server-sdk/actions/workflows/ci.yml
[sdk-badge]: https://img.shields.io/pypi/v/configdirector-server-sdk
[sdk-pypi]: https://pypi.org/project/configdirector-server-sdk/
[provider-badge]: https://img.shields.io/pypi/v/configdirector-openfeature-server-provider
[provider-pypi]: https://pypi.org/project/configdirector-openfeature-server-provider/
