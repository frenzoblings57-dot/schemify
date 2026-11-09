"""Smoke test for a running Schemify. Standard library only.

Usage: python smoke_test.py http://127.0.0.1:28080
       python smoke_test.py https://beta.schemify.com.ng
"""
import json
import sys
import urllib.error
import urllib.request


def call(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    checks = []

    status, body = call(base, "GET", "/v1/health")
    checks.append(("GET /v1/health", status == 200 and body == {"status": "ok"}))

    status, body = call(base, "GET", "/v1/version")
    checks.append(("GET /v1/version", status == 200 and body.get("service") == "schemify"))

    status, body = call(base, "POST", "/v1/normalize",
                        {"data": {"user_id": "123"}, "schema": {"user_id": "number"}})
    checks.append(("POST /v1/normalize", status == 200 and body.get("normalized") == {"user_id": 123}))

    status, body = call(base, "POST", "/v1/normalize", {"data": {}, "schema": {"a": "float"}})
    checks.append(("422 on unsupported type", status == 422 and "error" in body))

    status, body = call(base, "POST", "/v1/normalize",
                        {"data": {"Price": "$1,200", "when": "23 Oct 2026"},
                         "schema": {"price": "money", "when": "date"}})
    checks.append(("rich types (money, date)",
                   status == 200 and body.get("normalized") == {"price": 1200, "when": "2026-10-23"}))

    status, body = call(base, "POST", "/v1/batch",
                        {"schema": {"id": "integer"}, "records": [{"id": "1"}, {"id": "x"}]})
    checks.append(("POST /v1/batch",
                   status == 200 and body.get("summary") == {"records": 2, "records_with_errors": 1}))

    status, body = call(base, "POST", "/v1/repair", {"text": "```json\n{'a': 1,}\n```"})
    checks.append(("POST /v1/repair", status == 200 and body.get("parsed") == {"a": 1}))

    status, body = call(base, "POST", "/v1/repair", {"text": "no json here"})
    checks.append(("422 on unrepairable text", status == 422 and body.get("code") == "unrepairable"))

    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
    sys.exit(0 if all(ok for _, ok in checks) else 1)


if __name__ == "__main__":
    main()
