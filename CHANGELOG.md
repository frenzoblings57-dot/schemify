# Changelog

## 0.2.0
- Production runtime: Gunicorn, pinned dependencies, Dockerfile, compose file for local/staging.
- Every response, including errors, is a JSON object with `error` and `code`.
- New status codes: 413 (body too large), 415 (not JSON), 422 (unsupported schema type).
- Request size limit (default 256 KiB, set `MAX_BODY_BYTES`).
- Rejects `NaN` and `Infinity` literals, and deeply nested JSON, with 400.
- Ambiguous input keys (for example `user_id` and `UserID`) are reported instead of silently picking one.
- Number parsing is strict: no `nan`, `inf`, or `1_000`. Numeric strings up to 64 characters.
- Booleans: `"true"`, `"yes"`, `"1"` and `"false"`, `"no"`, `"0"` (any case). Numbers only if 0 or 1.
- Output is independent of the order of keys in the schema.
- Error messages no longer echo input values.
- Added `/healthz` and richer `/v1/version`.
- Added OpenAPI 3.1 spec, pytest suite, smoke test, CI.

## 0.1.0
- First prototype: Flask app with `/v1/health`, `/v1/version`, `/v1/normalize`.
