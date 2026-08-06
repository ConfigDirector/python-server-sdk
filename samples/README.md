# Sample apps

Small, self-contained applications showing how to use the ConfigDirector Python server SDK with
different web frameworks.

| Sample | Framework | Description |
|---|---|---|
| [flask/](flask/) | [Flask](https://flask.palletsprojects.com/) | Minimal WSGI app: client lifecycle, per-request evaluation, SSR hydration |

Each sample is an independent project with its own `pyproject.toml`. They depend on the SDK
through a local path (`configdirector-server-sdk = { path = "../.." }`) so that they always run
against the working copy in this repository rather than a published release.

To run one:

```bash
cd samples/flask
uv run flask --app app run --port 3600
```

> The samples need a real server SDK key to resolve configs. Without one the client stays
> unready and every config falls back to the default the sample passes in, which is also what
> a production app sees when it cannot reach ConfigDirector.
