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

> **Stage 1 note.** The SDK's evaluation is still stubbed, so every config resolves to the
> default value the sample passes in. The samples exist to demonstrate the API shape and
> lifecycle; the values will become real as later stages land.
