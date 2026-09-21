"""A minimal Flask app using the ConfigDirector Python server SDK.

Run it with::

    uv run flask --app app run --port 3600

Then try http://localhost:3600/configs?id=user-123&plan=pro

Query parameters double as the evaluation context: ``id``, ``name``, and ``anonymous`` map to
the matching :class:`~configdirector.Context` fields, and anything else becomes a trait.
"""

from __future__ import annotations

from configdirector import Context
from flask import Flask, Response, jsonify, request

# The single, process-wide client. It was created and initialized when this import ran, and the
# same instance serves every request below — see configdirector_client.py for why, and for the
# logging setup that has to happen before it.
from configdirector_client import client

# Query parameters that describe the user rather than one of their traits.
CONTEXT_FIELDS = frozenset({"id", "name", "anonymous"})

app = Flask(__name__)


def resolve_configs(context: Context) -> dict[str, object]:
    """Evaluate every config this app reads.

    ``get_value`` is cheap: it evaluates against config state the client already holds in
    memory, with no network call on the request path. That is what makes it safe to call
    several times per request.

    The default passed to ``get_value`` is what the app serves whenever ConfigDirector is
    unreachable, so it should always be the safe choice. Its type also decides how the config
    value is parsed.
    """
    return {
        "temporary-feature-flag": client.get_value("temporary-feature-flag", True, context),
        "permanent-kill-switch": client.get_value("permanent-kill-switch", False, context),
        "integer-config": client.get_value("integer-config", 10, context),
        "day-of-the-week-config": client.get_value("day-of-the-week-config", "Friday", context),
        "json-value-config": client.get_value("json-value-config", {}, context),
    }


def context_from_request() -> Context:
    """Build an evaluation context from the query string.

    The context is per-request; the client that evaluates it is not. A real application would
    build this from the authenticated session instead.
    """
    traits = {key: value for key, value in request.args.items() if key not in CONTEXT_FIELDS}
    return Context(
        id=request.args.get("id"),
        name=request.args.get("name"),
        traits=traits or None,
        anonymous=request.args.get("anonymous") == "true",
    )


@app.get("/configs")
def configs() -> Response:
    return jsonify(resolve_configs(context_from_request()))


@app.errorhandler(404)
def not_found(_error: object) -> tuple[Response, int]:
    return jsonify(error="Not found. Try GET /configs"), 404
