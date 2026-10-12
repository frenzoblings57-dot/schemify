# Schemify

Schemify cleans up messy JSON for AI agents. Send it a JSON object and a simple schema. It returns clean data and a report of every change it made.

Built for Pocket Network's Agentic Portal hackathon. Beta/TestNet service ID: `schemify`.
Public Beta URL: https://beta.schemify.com.ng

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health` (also `/healthz`) | `{"status":"ok"}` |
| GET | `/v1/version` | service, version, schema version, commit |
| POST | `/v1/normalize` | normalize `data` against `schema` |

Full contract: [`openapi.yaml`](openapi.yaml). Every response, including errors, is a JSON object.

### Example

Request:
```json
{"data": {"UserID": "123", "Name": "Frenzo"},
 "schema": {"user_id": "number", "name": "string", "active": "boolean"}}
```
Response:
```json
{"changes": ["mapped key 'Name' -> 'name'", "mapped key 'UserID' -> 'user_id'", "'user_id': coerced string to number"],
 "errors": ["'active': required field missing entirely"],
 "normalized": {"name": "Frenzo", "user_id": 123}}
```

### Rules

- Schema types: `string`, `number`, `boolean`, `array`, `object`. Any other type returns **422**.
- Keys match ignoring case, `_` and `-` (`UserID` matches `user_id`).
- If two input keys match one schema field, that field is reported in `errors` as ambiguous. Nothing is guessed.
- Unknown input fields are ignored.
- Numbers: numeric strings are converted (`"42.0"` becomes `42`). `nan`, `inf`, `1_000` and strings over 64 characters are rejected. Booleans are never numbers.
- Booleans: `true/yes/1` and `false/no/0` as strings in any case. Numbers only if 0 or 1.
- A single value where an array is expected is wrapped in an array.
- `null` is reported as an error, never converted.
- Output is deterministic: the same request always returns the same bytes.

### Errors

| Status | Code | When |
|---|---|---|
| 400 | `invalid_json`, `invalid_request` | bad JSON, or `data` / `schema` missing or not objects |
| 413 | `payload_too_large` | body over `MAX_BODY_BYTES` (default 262144) |
| 415 | `unsupported_media_type` | Content-Type is not `application/json` |
| 422 | `unsupported_schema` | a schema type is not supported |
| 500 | `internal_error` | unexpected error, no details exposed |

## Run and test

```bash
pip install -r requirements-dev.txt
python -m pytest -q              # unit, HTTP and OpenAPI tests
python app.py                    # dev server on 127.0.0.1:8080
python smoke_test.py http://127.0.0.1:8080
```

Production runs Gunicorn:
```bash
docker build -t schemify:0.2.0 --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) .
docker run --rm -p 127.0.0.1:28080:8080 schemify:0.2.0
```
Settings: `PORT` (default 8080), `MAX_BODY_BYTES`, `WEB_CONCURRENCY` (default 2). No secrets are needed.

Operator notes: [`ops/README.md`](ops/README.md).
