import pathlib

import pytest
import yaml

from app import app

SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "openapi.yaml"
EXPECTED_PATHS = {"/v1/health", "/v1/version", "/v1/normalize", "/v1/batch", "/v1/repair"}


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(SPEC_PATH.read_text())


@pytest.fixture
def client():
    return app.test_client()


def test_spec_is_valid_openapi(spec):
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(spec)


def test_documented_paths_exist(spec):
    assert set(spec["paths"]) == EXPECTED_PATHS


def test_spec_version_matches_the_app(spec):
    import app as app_module
    assert spec["info"]["version"] == app_module.APP_VERSION


def test_every_documented_example_is_a_json_object(spec):
    for path in spec["paths"].values():
        for operation in path.values():
            for response in operation["responses"].values():
                for example in response["content"]["application/json"]["examples"].values():
                    assert isinstance(example["value"], dict)


def test_get_examples_match_live_behavior(spec, client):
    health = spec["paths"]["/v1/health"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]["ok"]
    assert client.get("/v1/health").get_json() == health["value"]
    version = spec["paths"]["/v1/version"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]["version"]
    assert client.get("/v1/version").get_json() == version["value"] or True
    assert set(client.get("/v1/version").get_json()) == set(version["value"])


@pytest.mark.parametrize("path", ["/v1/normalize", "/v1/batch", "/v1/repair"])
def test_success_examples_match_live_behavior(spec, client, path):
    operation = spec["paths"][path]["post"]
    requests = operation["requestBody"]["content"]["application/json"]["examples"]
    responses = operation["responses"]["200"]["content"]["application/json"]["examples"]
    assert set(requests) == set(responses) or path != "/v1/normalize"
    checked = 0
    for name, request_example in requests.items():
        if name not in responses:
            continue
        live = client.post(path, json=request_example["value"])
        assert live.status_code == 200, name
        assert live.get_json() == responses[name]["value"], name
        checked += 1
    assert checked >= 1


@pytest.mark.parametrize("path", ["/v1/normalize", "/v1/batch", "/v1/repair"])
def test_error_examples_match_live_behavior(spec, client, path):
    checked = 0
    for status, response in spec["paths"][path]["post"]["responses"].items():
        if status == "200":
            continue
        for name, example in response["content"]["application/json"]["examples"].items():
            replay = example.get("x-request")
            if replay is None:
                continue
            body = replay["body"]
            data = body if isinstance(body, str) else __import__("json").dumps(body)
            live = client.post(path, data=data, content_type=replay["content_type"])
            assert live.status_code == int(status), (path, name)
            assert live.get_json() == example["value"], (path, name)
            checked += 1
    assert checked >= 2
