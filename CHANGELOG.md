# Changelog

## 0.3.0
New endpoints:
- `POST /v1/repair`: fixes broken JSON text (code fences, text around the JSON, trailing commas,
  single quotes, unquoted keys, comments, Python literals, cut-off output). Optionally normalizes
  the result in the same call. Refuses to guess when the text is ambiguous.
- `POST /v1/batch`: normalize up to 100 records with one schema in a single call.

`/v1/normalize` is unchanged for existing clients. New, optional schema features:
- Nested objects (`properties`) and lists (`items`), including lists of objects.
- New types: `integer`, `date` (to ISO 8601), `money` ("$1,200" to 1200), `percent` ("12%" to 12).
- `enum`, `default` and `required: false` per field.
- Error and change messages name the full path, for example `'orders[0].price'`.

Safety and quality:
- Infinite numbers (`1e999`) are rejected everywhere, so a response is always valid JSON.
- Ambiguous dates like `03/04/2026` are refused, never guessed.
- Reports are capped at 200 entries per list.
- Schemas are limited to 6 levels of nesting.
- 244 tests, including random-input fuzz tests.

Note: `integer` used to be an unsupported type (422). It is now supported.

## 0.2.1
- Added `GET /`.

## 0.2.0
- Gunicorn, pinned dependencies, Dockerfile, OpenAPI spec, tests, CI.
- Every response, including errors, is a JSON object with `error` and `code`.
- Ambiguous input keys are reported instead of guessed.

## 0.1.0
- First prototype.
