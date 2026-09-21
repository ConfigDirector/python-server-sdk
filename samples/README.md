# Sample apps

Small, self-contained applications showing how to use the ConfigDirector Python packages with
different web frameworks, grouped by the package they demonstrate.

## [configdirector-server-sdk](configdirector-server-sdk/)

| Sample | Framework | Description |
|---|---|---|
| [flask/](configdirector-server-sdk/flask/) | [Flask](https://flask.palletsprojects.com/) | Minimal WSGI app: client lifecycle, per-request evaluation, SSR hydration |

## [configdirector-openfeature-server-provider](configdirector-openfeature-server-provider/)

| Sample | Framework | Description |
|---|---|---|
| [flask/](configdirector-openfeature-server-provider/flask/) | [Flask](https://flask.palletsprojects.com/) | Minimal WSGI app: provider lifecycle, per-request evaluation context, evaluation details |

Each sample is an independent project with its own `pyproject.toml`, depending on the released
package from PyPI exactly as a real app would. They do not run against the working copy in this
repository; `make samples-local` checks them against it, and to try a local change in a sample by
hand, add a temporary source override to that sample and remove it before committing:

```toml
[tool.uv.sources]
configdirector-server-sdk = { path = "../../../configdirector-server-sdk", editable = true }
```

To run one:

```bash
cd samples/configdirector-server-sdk/flask
uv run flask --app app run --port 3600
```

> The samples need a real server SDK key to resolve configs. Without one the client stays
> unready and every config falls back to the default the sample passes in, which is also what
> a production app sees when it cannot reach ConfigDirector.
