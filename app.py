"""Schemify HTTP API. Every response, including errors, is a JSON object."""
import json
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from normalizer import SchemaError, compile_schema, normalize_compiled
from repair import RepairError, repair_json

SERVICE_ID = "schemify"
APP_VERSION = "0.3.0"
SCHEMA_VERSION = "1"
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", "262144"))
MAX_BATCH_RECORDS = int(os.environ.get("MAX_BATCH_RECORDS", "100"))

app = Flask(__name__)
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
    app.logger.error("unhandled error: %s", type(exc).__name__)
    return _error(500, "internal_error", "internal error")


def _reject_constant(name):
    raise ValueError("invalid JSON constant")


def _checked_float(text):
    number = float(text)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("number out of range")
    return number


def _read_body():
    """Return (body, failure_response). Exactly one of them is None."""
    mimetype = request.mimetype or ""
    if mimetype != "application/json" and not mimetype.endswith("+json"):
        return None, _error(415, "unsupported_media_type", "Content-Type must be application/json")
    raw = request.get_data(cache=False)
    try:
        body = json.loads(raw, parse_constant=_reject_constant, parse_float=_checked_float)
    except (ValueError, RecursionError):
        return None, _error(400, "invalid_json", "request body must be valid JSON")
    if not isinstance(body, dict):
        return None, _error(400, "invalid_request", "request body must be a JSON object")
    return body, None


@app.route("/", methods=["GET", "HEAD"])
def root():
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
    body, failure = _read_body()
    if failure:
        return failure

    data = body.get("data")
    schema = body.get("schema")
    if data is None or schema is None:
        return _error(400, "invalid_request", "request must include both 'data' and 'schema' fields")
    if not isinstance(data, dict) or not isinstance(schema, dict):
        return _error(400, "invalid_request", "'data' and 'schema' must both be JSON objects")

    try:
        compiled = compile_schema(schema)
    except SchemaError as exc:
        return _error(422, "unsupported_schema", str(exc))
    return jsonify(normalize_compiled(data, compiled)), 200


@app.post("/v1/batch")
def batch_endpoint():
    body, failure = _read_body()
    if failure:
        return failure

    schema = body.get("schema")
    records = body.get("records")
    if schema is None or records is None:
        return _error(400, "invalid_request", "request must include both 'schema' and 'records' fields")
    if not isinstance(schema, dict) or not isinstance(records, list):
        return _error(400, "invalid_request", "'schema' must be a JSON object and 'records' must be a list")
    if len(records) > MAX_BATCH_RECORDS:
        return _error(400, "invalid_request", f"records must contain at most {MAX_BATCH_RECORDS} items")

    try:
        compiled = compile_schema(schema)
    except SchemaError as exc:
        return _error(422, "unsupported_schema", str(exc))

    results = []
    with_errors = 0
    for index, record in enumerate(records):
        if isinstance(record, dict):
            result = normalize_compiled(record, compiled)
        else:
            result = {"normalized": {}, "changes": [], "errors": ["record is not an object"]}
        result["index"] = index
        if result["errors"]:
            with_errors += 1
        results.append(result)
    summary = {"records": len(records), "records_with_errors": with_errors}
    return jsonify({"results": results, "summary": summary}), 200


@app.post("/v1/repair")
def repair_endpoint():
    body, failure = _read_body()
    if failure:
        return failure

    text = body.get("text")
    schema = body.get("schema")
    if not isinstance(text, str):
        return _error(400, "invalid_request", "request must include 'text' as a string")
    if schema is not None and not isinstance(schema, dict):
        return _error(400, "invalid_request", "'schema' must be a JSON object")

    compiled = None
    if schema is not None:
        try:
            compiled = compile_schema(schema)
        except SchemaError as exc:
            return _error(422, "unsupported_schema", str(exc))

    try:
        parsed, fixes = repair_json(text)
    except RepairError as exc:
        return _error(422, "unrepairable", str(exc))

    result = {"parsed": parsed, "fixes": fixes}
    if compiled is not None:
        if not isinstance(parsed, dict):
            return _error(422, "not_an_object", "repaired JSON is not an object, so it cannot be normalized")
        result.update(normalize_compiled(parsed, compiled))
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
