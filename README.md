# Schemify

Schemify cleans and repairs JSON for AI agents. It fixes wrong types, odd key names, broken model output and
messy dates and prices, and it lists every change it made.

Built for Pocket Network's Agentic Services Hackathon. Beta/TestNet service ID: `schemify`.
Public Beta URL: https://beta.schemify.com.ng

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health` (also `/healthz`) | `{"status":"ok"}` |
| GET | `/v1/version` | service, version, schema version, commit |
| POST | `/v1/normalize` | normalize `data` against `schema` |
| POST | `/v1/batch` | normalize up to 100 `records` with one `schema` |
| POST | `/v1/repair` | repair broken JSON `text`, optionally normalize it |

Full contract with examples: [`openapi.yaml`](openapi.yaml). Every response, including errors, is a JSON object.
The same request always returns the same bytes.

### Normalize

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

### Schema

A field is a type name, or an object with options.

| Type | Accepts | Becomes |
|---|---|---|
| `string` | text, numbers, booleans | text |
| `number` | `"42"`, `"1e3"`, `42.0` | a number |
| `integer` | `"42"`, `42.0` | a whole number (4.5 is an error) |
| `boolean` | `true/yes/1`, `false/no/0` in any case | true or false |
| `money` | `"$1,200.50"`, `"USD 1,200"`, `"(1,200)"` | a number |
| `percent` | `"12%"`, `"12.5"` | a number (12, not 0.12) |
| `date` | `"23 Oct 2026"`, `"2026/10/23"`, `"23/10/2026"` | `"2026-10-23"` |
| `array` | a list, or one value | a list |
| `object` | an object | an object |

Options: `required` (false allows a missing field), `default` (used when missing or null),
`enum` (string only, matched ignoring case and spaces), `properties` (nested object), `items` (list items).

```json
{"user": {"type": "object", "properties": {"id": "integer", "address": {"type": "object", "properties": {"zip": "string"}}}},
 "orders": {"type": "array", "items": {"type": "object", "properties": {"price": "money", "date": "date"}}},
 "status": {"type": "string", "enum": ["open", "closed"]},
 "retries": {"type": "integer", "default": 3}}
```

Rules:
- Keys match ignoring case, `_` and `-` (`UserID` matches `user_id`). Two input keys for one field are reported as ambiguous.
- Fields that fail are left out and reported with their path, like `'orders[0].price'`.
- If any item of a list fails, the whole list is left out and each failing item is reported.
- Dates are never guessed: `03/04/2026` is ambiguous and refused. `23/04/2026` and `05/05/2026` are fine.
- `null` is an error unless the field has a default or is optional.
- Unknown input fields are ignored. Schemas may nest 6 levels deep.

### Repair

```json
{"text": "Here you go:\n```json\n{'name': 'Frenzo', active: True, tags: ['a', 'b',],}\n```"}
```
returns the parsed value and the list of fixes. Add a `schema` to normalize the repaired object in the same call.
If the text holds more than one JSON object, or cannot be repaired safely, you get a 422 instead of a guess.

### Errors

| Status | Code | When |
|---|---|---|
| 400 | `invalid_json`, `invalid_request` | bad JSON, infinite numbers, or missing or wrongly typed fields |
| 413 | `payload_too_large` | body over `MAX_BODY_BYTES` (default 262144) |
| 415 | `unsupported_media_type` | Content-Type is not `application/json` |
| 422 | `unsupported_schema`, `unrepairable`, `not_an_object` | schema invalid, text cannot be repaired, or repaired JSON is not an object |
| 500 | `internal_error` | unexpected error, no details exposed |

## Run and test

```bash
pip install -r requirements-dev.txt
python -m pytest -q              # unit, HTTP, OpenAPI and fuzz tests
python app.py                    # dev server on 127.0.0.1:8080
python smoke_test.py http://127.0.0.1:8080
```

Production runs Gunicorn:
```bash
docker build -t schemify:0.3.0 --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) .
docker run --rm -p 127.0.0.1:28080:8080 schemify:0.3.0
```
Settings: `PORT` (default 8080), `MAX_BODY_BYTES`, `MAX_BATCH_RECORDS` (default 100), `WEB_CONCURRENCY` (default 2).
No secrets are needed.

Operator notes: [`ops/README.md`](ops/README.md).
