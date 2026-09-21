"""A minimal Flask app using the ConfigDirector OpenFeature provider.

Run it with::

    uv run flask --app app run --port 3600

Then try http://localhost:3600/configs?id=user-123&plan=pro

Query parameters double as the evaluation context: ``id`` becomes the targeting key, ``name``
and ``anonymous`` map to the matching ConfigDirector context fields, and anything else becomes a
trait.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request
from openfeature.evaluation_context import EvaluationContext

from openfeature_client import client

CONTEXT_FIELDS = frozenset({"id", "name", "anonymous"})

app = Flask(__name__)


def resolve_configs(context: EvaluationContext) -> dict[str, object]:
    return {
        "temporary-feature-flag": client.get_boolean_value("temporary-feature-flag", True, context),
        "permanent-kill-switch": client.get_boolean_value("permanent-kill-switch", False, context),
        "integer-config": client.get_integer_value("integer-config", 10, context),
        "day-of-the-week-config": client.get_string_value("day-of-the-week-config", "Friday", context),
        "json-value-config": client.get_object_value("json-value-config", {}, context),
    }


def context_from_request() -> EvaluationContext:
    traits = {key: value for key, value in request.args.items() if key not in CONTEXT_FIELDS}
    attributes: dict[str, object] = {"anonymous": request.args.get("anonymous") == "true"}
    if "name" in request.args:
        attributes["name"] = request.args["name"]
    if traits:
        attributes["traits"] = traits
    return EvaluationContext(targeting_key=request.args.get("id"), attributes=attributes)  # type: ignore[arg-type]


@app.get("/configs")
def configs() -> Response:
    return jsonify(resolve_configs(context_from_request()))


@app.get("/configs/<key>")
def config_details(key: str) -> Response:
    details = client.get_boolean_details(key, False, context_from_request())
    return jsonify(
        value=details.value,
        variant=details.variant,
        reason=details.reason,
        error_code=details.error_code,
        error_message=details.error_message,
    )


@app.errorhandler(404)
def not_found(_error: object) -> tuple[Response, int]:
    return jsonify(error="Not found. Try GET /configs"), 404
