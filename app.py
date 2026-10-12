"""Schemify HTTP API. Every response, including errors, is a JSON object."""
import json
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from normalizer import SchemaError, normalize

SERVICE_ID = "schemify"
APP_VERSION = "0.2.1"
SCHEMA_VERSION = "1"
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", "262144"))

app = Flask(name)
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
app.json.sort_keys = True

_ERROR_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def _error(status, code, message):
    response = jsonify({"error": message, "code": code})
    response.status_code = status
    return response


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    status = exc.code or 500
    messages = {
        404: "not found",
        405: "method not allowed",
        413: f"request body exceeds {MAX_BODY_BYTES} bytes",
    }
    response = _error(
        status,
        _ERROR_CODES.get(status, "http_error"),
        messages.get(status, (exc.name or "error").lower()),
    )
    allowed = getattr(exc, "valid_methods", None)
    if status == 405 and allowed:
        response.headers["Allow"] = ", ".join(sorted(allowed))
    return response


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Log the exception type only: no tracebacks, paths or values reach clients.
    app.logger.error("unhandled error: %s", type(exc).name)
    return _error(500, "internal_error", "internal error")


def _reject_constant(name):
    raise ValueError("invalid JSON constant")


@app.route("/", methods=["GET", "HEAD"])
def root():
    # The RelayMiner checks the backend at the root path. Must return 200 JSON.
    return jsonify({"service": SERVICE_ID, "status": "ok"}), 200


@app.get("/v1/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@app.get("/v1/version")
def version():
    return jsonify(
        {
            "service": SERVICE_ID,
            "version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "commit": os.environ.get("GIT_COMMIT", "unknown"),
        }
    ), 200


@app.post("/v1/normalize")
def normalize_endpoint():
    mimetype = request.mimetype or ""
    if mimetype != "application/json" and not mimetype.endswith("+json"):
        return _error(415, "unsupported_media_type", "Content-Type must be application/json")

    raw = request.get_data(cache=False)
    try:
        body = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return _error(400, "invalid_json", "request body must be valid JSON")

    if not isinstance(body, dict):
        return _error(400, "invalid_request", "request body must be a JSON object")

    data = body.get("data")
    schema = body.get("schema")
    if data is None or schema is None:
        return _error(400, "invalid_request", "request must include both 'data' and 'schema' fields")
    if not isinstance(data, dict) or not isinstance(schema, dict):
        return _error(400, "invalid_request", "'data' and 'schema' must both be JSON objects")

    try:
        result = normalize(data, schema)
    except SchemaError as exc:
        return _error(422, "unsupported_schema", str(exc))
    return jsonify(result), 200


if name == "main":
    # Local development only. Production runs Gunicorn (see gunicorn.conf.py).
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
