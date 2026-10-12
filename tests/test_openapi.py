import pathlib

import pytest
import yaml

from app import app

SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "openapi.yaml"


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(SPEC_PATH.read_text())


def test_spec_is_valid_openapi(spec):
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(spec)


def test_documented_paths_exist(spec):
    assert set(spec["paths"]) == {"/v1/health", "/v1/version", "/v1/normalize"}


def test_every_documented_example_is_a_json_object(spec):
    for path in spec["paths"].values():
        for operation in path.values():
            for response in operation["responses"].values():
                for example in response["content"]["application/json"]["examples"].values():
                    assert isinstance(example["value"], dict)


def test_normalize_examples_match_live_behavior(spec):
    client = app.test_client()
    operation = spec["paths"]["/v1/normalize"]["post"]
    requests = operation["requestBody"]["content"]["application/json"]["examples"]
    responses = operation["responses"]["200"]["content"]["application/json"]["examples"]
    assert requests
    for name, request_example in requests.items():
        live = client.post("/v1/normalize", json=request_example["value"])
        assert live.status_code == 200
        assert live.get_json() == responses[name]["value"], name


def test_get_examples_match_live_behavior(spec):
    client = app.test_client()
    health = spec["paths"]["/v1/health"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]["ok"]
    assert client.get("/v1/health").get_json() == health["value"]
    version = spec["paths"]["/v1/version"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]["version"]
    live = client.get("/v1/version").get_json()
    assert live["service"] == version["value"]["service"]
    assert set(live) == set(version["value"])


def test_error_examples_match_live_behavior(spec):
    client = app.test_client()
    errors = {
        "400": client.post("/v1/normalize", data="{bad", content_type="application/json"),
        "415": client.post("/v1/normalize", data="{}", content_type="text/plain"),
        "422": client.post("/v1/normalize", json={"data": {"age": 1}, "schema": {"age": "integer"}}),
    }
    responses = spec["paths"]["/v1/normalize"]["post"]["responses"]
    for status, live in errors.items():
        documented = next(iter(responses[status]["content"]["application/json"]["examples"].values()))
        assert live.status_code == int(status)
        assert live.get_json() == documented["value"], status
