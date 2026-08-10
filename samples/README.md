# Sample apps

Small, self-contained applications showing how to use the ConfigDirector Python server SDK with
different web frameworks.

| Sample | Framework | Description |
|---|---|---|
| [flask/](flask/) | [Flask](https://flask.palletsprojects.com/) | Minimal WSGI app: client lifecycle, per-request evaluation, SSR hydration |

Each sample is an independent project with its own `pyproject.toml`, depending on the released
`configdirector-server-sdk` from PyPI exactly as a real app would. They do not run against the
working copy in this repository; to try a local change in a sample, add a temporary source
override to that sample and remove it before committing:

```toml
[tool.uv.sources]
configdirector-server-sdk = { path = "../..", editable = true }
```

To run one:

```bash
cd samples/flask
uv run flask --app app run --port 3600
```

> The samples need a real server SDK key to resolve configs. Without one the client stays
> unready and every config falls back to the default the sample passes in, which is also what
> a production app sees when it cannot reach ConfigDirector.
