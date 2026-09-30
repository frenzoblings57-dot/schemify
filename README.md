# Schemify

A JSON schema normalizer built for Pocket Network's Agentic Portal hackathon.

Schemify takes messy JSON data plus a simple schema and returns cleaned,
type-corrected data along with a report of exactly what was fixed. Built
for AI agents that need reliable, consistent data when calling other
services.

## Endpoints

- `GET /v1/health` — service health check
- `GET /v1/version` — service and version info
- `POST /v1/normalize` — the core service. Send `{"data": {...}, "schema": {...}}`

## Example

Request:
```json
{
  "data": { "UserID": "123", "Name": "Frenzo" },
  "schema": { "user_id": "number", "name": "string", "active": "boolean" }
}
```

Response:
```json
{
  "normalized": { "user_id": 123, "name": "Frenzo" },
  "changes": [
    "mapped key 'UserID' -> 'user_id'",
    "'user_id': coerced string to number",
    "mapped key 'Name' -> 'name'"
  ],
  "errors": [
    "'active': required field missing entirely"
  ]
}
```

## Run locally

```
pip install flask
python3 app.py
```
