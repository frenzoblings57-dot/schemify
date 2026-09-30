from flask import Flask, request, jsonify
from normalizer import normalize

app = Flask(__name__)

SERVICE_ID = "schemify"
VERSION = "0.1.0"


# --- Required probe endpoints (Pocket checks these to confirm the service is alive) ---

@app.route("/v1/version", methods=["GET"])
def version():
    return jsonify({"service": SERVICE_ID, "version": VERSION}), 200


@app.route("/v1/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# --- The actual service ---

@app.route("/v1/normalize", methods=["POST"])
def normalize_endpoint():
    body = request.get_json(silent=True)

    if body is None:
        return jsonify({"error": "request body must be valid JSON"}), 400

    raw_data = body.get("data")
    schema = body.get("schema")

    if raw_data is None or schema is None:
        return jsonify({
            "error": "request must include both 'data' and 'schema' fields"
        }), 400

    if not isinstance(raw_data, dict) or not isinstance(schema, dict):
        return jsonify({
            "error": "'data' and 'schema' must both be JSON objects"
        }), 400

    result = normalize(raw_data, schema)
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
