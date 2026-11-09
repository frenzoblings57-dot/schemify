import json

import pytest

import app as app_module
from app import MAX_BODY_BYTES, app


@pytest.fixture
def client():
    return app.test_client()


def post(client, payload, content_type="application/json"):
    body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    return client.post("/v1/normalize", data=body, content_type=content_type)


def post_to(client, path, payload, content_type="application/json"):
    body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    return client.post(path, data=body, content_type=content_type)


def assert_json_object(response):
    assert response.mimetype == "application/json"
    assert response.get_data(as_text=True).lstrip().startswith("{")
    assert isinstance(response.get_json(), dict)


def test_health_and_alias(client):
    for path in ("/v1/health", "/healthz"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}


def test_version(client):
    body = client.get("/v1/version").get_json()
    assert body["service"] == "schemify"
    assert {"version", "schema_version", "commit"} <= set(body)


def test_happy_path(client):
    response = post(client, {
        "data": {"UserID": "123", "Name": "Frenzo"},
        "schema": {"user_id": "number", "name": "string", "active": "boolean"},
    })
    assert response.status_code == 200
    assert response.get_json()["normalized"] == {"name": "Frenzo", "user_id": 123}


def test_functional_probe_bytes_are_deterministic(client):
    response = post(client, {"data": {"user_id": "123"}, "schema": {"user_id": "number"}})
    assert response.get_data(as_text=True) == (
        '{"changes":["\'user_id\': coerced string to number"],"errors":[],"normalized":{"user_id":123}}\n'
    )


@pytest.mark.parametrize("raw", ["{not json", "", b"\xff\xfe\x00", "[1,2", '{"data": NaN, "schema": {}}'])
def test_malformed_json_is_400(client, raw):
    response = post(client, raw)
    assert response.status_code == 400
    assert_json_object(response)
    assert response.get_json()["code"] == "invalid_json"


def test_deeply_nested_json_is_400_not_500(client):
    response = post(client, "[" * 100000 + "]" * 100000)
    assert response.status_code == 400
    assert_json_object(response)


@pytest.mark.parametrize("payload", [
    [1, 2, 3],
    {"schema": {"a": "string"}},
    {"data": {"a": 1}},
    {"data": [1], "schema": {"a": "string"}},
    {"data": {"a": 1}, "schema": "string"},
    {"data": None, "schema": {}},
])
def test_invalid_request_shapes_are_400(client, payload):
    response = post(client, payload)
    assert response.status_code == 400
    assert_json_object(response)


def test_wrong_content_type_is_415(client):
    response = post(client, '{"data": {}, "schema": {}}', content_type="text/plain")
    assert response.status_code == 415
    assert_json_object(response)


def test_unsupported_schema_type_is_422(client):
    response = post(client, {"data": {"a": 1}, "schema": {"a": "float"}})
    assert response.status_code == 422
    assert_json_object(response)
    assert response.get_json()["code"] == "unsupported_schema"


def test_oversized_body_is_413(client):
    big = {"data": {"a": "x" * (MAX_BODY_BYTES + 10)}, "schema": {"a": "string"}}
    response = post(client, big)
    assert response.status_code == 413
    assert_json_object(response)


def test_404_and_405_are_json_objects(client):
    missing = client.get("/nope")
    assert missing.status_code == 404
    assert_json_object(missing)
    wrong_method = client.get("/v1/normalize")
    assert wrong_method.status_code == 405
    assert_json_object(wrong_method)
    assert "POST" in wrong_method.headers["Allow"]


def test_unexpected_errors_do_not_leak_details(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret-internal-detail /srv/path")

    monkeypatch.setattr(app_module, "normalize_compiled", boom)
    response = post(client, {"data": {"a": 1}, "schema": {"a": "number"}})
    assert response.status_code == 500
    assert_json_object(response)
    text = response.get_data(as_text=True)
    assert "secret-internal-detail" not in text
    assert "/srv/path" not in text
    assert "Traceback" not in text


def test_root_returns_200_for_get_and_head(client):
    assert client.get("/").status_code == 200
    assert client.get("/").get_json() == {"service": "schemify", "status": "ok"}
    assert client.head("/").status_code == 200


# ------------------------------------------------------------- rich schema over HTTP

def test_rich_schema_over_http(client):
    response = post(client, {
        "data": {"Price": "$1,200", "when": "23 Oct 2026", "status": " OPEN "},
        "schema": {"price": "money", "when": "date",
                   "status": {"type": "string", "enum": ["open", "closed"]},
                   "retries": {"type": "integer", "default": 3}},
    })
    assert response.status_code == 200
    assert response.get_json()["normalized"] == {
        "price": 1200, "when": "2026-10-23", "status": "open", "retries": 3}


def test_bad_rich_schema_is_422(client):
    response = post(client, {"data": {}, "schema": {"a": {"type": "string", "enum": []}}})
    assert response.status_code == 422
    assert response.get_json()["code"] == "unsupported_schema"


# ------------------------------------------------------------- /v1/batch

def test_batch_happy_path(client):
    response = post_to(client, "/v1/batch", {
        "schema": {"id": "integer", "name": "string"},
        "records": [{"ID": "1", "name": "a"}, {"id": "x"}, "not an object"],
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"] == {"records": 3, "records_with_errors": 2}
    assert [r["index"] for r in body["results"]] == [0, 1, 2]
    assert body["results"][0]["normalized"] == {"id": 1, "name": "a"}
    assert body["results"][1]["errors"] == [
        "'id': could not coerce string to integer", "'name': required field missing entirely"]
    assert body["results"][2] == {"index": 2, "normalized": {}, "changes": [], "errors": ["record is not an object"]}


def test_batch_empty_list_is_fine(client):
    body = post_to(client, "/v1/batch", {"schema": {"a": "string"}, "records": []}).get_json()
    assert body == {"results": [], "summary": {"records": 0, "records_with_errors": 0}}


@pytest.mark.parametrize("payload", [
    {"records": []}, {"schema": {}}, {"schema": [], "records": []}, {"schema": {}, "records": {}},
    {"schema": {}, "records": None},
])
def test_batch_bad_shapes_are_400(client, payload):
    response = post_to(client, "/v1/batch", payload)
    assert response.status_code == 400
    assert_json_object(response)


def test_batch_limit_is_enforced(client):
    response = post_to(client, "/v1/batch", {"schema": {"a": "string"}, "records": [{"a": "x"}] * 101})
    assert response.status_code == 400
    assert "at most 100" in response.get_json()["error"]


def test_batch_bad_schema_is_422(client):
    response = post_to(client, "/v1/batch", {"schema": {"a": "float"}, "records": [{}]})
    assert response.status_code == 422


# ------------------------------------------------------------- /v1/repair

def test_repair_happy_path(client):
    response = post_to(client, "/v1/repair", {"text": "```json\n{'a': 1,}\n```"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["parsed"] == {"a": 1}
    assert body["fixes"] == [
        "removed markdown code fence", "converted single quotes to double quotes", "removed trailing comma"]


def test_repair_valid_json_has_no_fixes(client):
    assert post_to(client, "/v1/repair", {"text": '{"a": 1}'}).get_json() == {"fixes": [], "parsed": {"a": 1}}


def test_repair_then_normalize_in_one_call(client):
    response = post_to(client, "/v1/repair", {
        "text": "Result: {'UserID': '42', active: True,}",
        "schema": {"user_id": "integer", "active": "boolean"},
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["normalized"] == {"user_id": 42, "active": True}
    assert body["parsed"] == {"UserID": "42", "active": True}
    assert body["errors"] == []


def test_repair_unrepairable_is_422(client):
    response = post_to(client, "/v1/repair", {"text": "no json here"})
    assert response.status_code == 422
    assert response.get_json()["code"] == "unrepairable"


def test_repair_with_schema_needs_an_object(client):
    response = post_to(client, "/v1/repair", {"text": "[1, 2]", "schema": {"a": "string"}})
    assert response.status_code == 422
    assert response.get_json()["code"] == "not_an_object"


@pytest.mark.parametrize("payload", [{}, {"text": 5}, {"text": None}, {"text": "{}", "schema": "x"}])
def test_repair_bad_shapes_are_400(client, payload):
    response = post_to(client, "/v1/repair", payload)
    assert response.status_code == 400
    assert_json_object(response)


def test_repair_bad_schema_is_422(client):
    response = post_to(client, "/v1/repair", {"text": "{}", "schema": {"a": "float"}})
    assert response.status_code == 422


def test_repair_deeply_nested_text_is_a_clean_422(client):
    response = post_to(client, "/v1/repair", {"text": "[" * 5000})
    assert response.status_code == 422
    assert_json_object(response)


def test_repair_oversized_body_is_413(client):
    response = post_to(client, "/v1/repair", {"text": "x" * (MAX_BODY_BYTES + 10)})
    assert response.status_code == 413
    assert_json_object(response)


def test_new_endpoints_reject_wrong_content_type(client):
    for path in ("/v1/repair", "/v1/batch"):
        assert client.post(path, data="{}", content_type="text/plain").status_code == 415


@pytest.mark.parametrize("path,payload", [
    ("/v1/normalize", '{"data": {"a": 1e999}, "schema": {"a": "object"}}'),
    ("/v1/batch", '{"schema": {"a": "object"}, "records": [{"a": -1e999}]}'),
    ("/v1/repair", '{"text": "{}", "schema": {"a": 1e999}}'),
])
def test_infinite_numbers_in_requests_are_400(client, path, payload):
    response = post_to(client, path, payload)
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_json"
