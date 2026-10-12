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
    response = post(client, {"data": {"a": 1}, "schema": {"a": "integer"}})
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

    monkeypatch.setattr(app_module, "normalize", boom)
    response = post(client, {"data": {"a": 1}, "schema": {"a": "number"}})
    assert response.status_code == 500
    assert_json_object(response)
    text = response.get_data(as_text=True)
    assert "secret-internal-detail" not in text
    assert "/srv/path" not in text
    assert "Traceback" not in text
