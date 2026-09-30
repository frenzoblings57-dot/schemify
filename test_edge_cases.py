import requests
import json

URL = "http://127.0.0.1:8080/v1/normalize"

schema = {
    "user_id": "number",
    "name": "string",
    "active": "boolean",
    "tags": "array",
}

test_cases = [
    ("Empty data object", {}, schema),
    ("Everything wrong type", {
        "user_id": "not-a-number",
        "name": 12345,
        "active": "maybe",
        "tags": "not-an-array",
    }, schema),
    ("Boolean written as yes/no", {
        "user_id": 7,
        "name": "Test",
        "active": "yes",
        "tags": ["a", "b"],
    }, schema),
    ("Single value where array expected", {
        "user_id": 7,
        "name": "Test",
        "active": True,
        "tags": "solo-tag",
    }, schema),
    ("Null values", {
        "user_id": None,
        "name": None,
        "active": None,
        "tags": None,
    }, schema),
    ("Extra unexpected fields, some missing", {
        "user_id": 42,
        "extra_field": "should be ignored",
        "another_extra": 999,
    }, schema),
    ("Already perfectly correct", {
        "user_id": 1,
        "name": "Perfect",
        "active": False,
        "tags": ["x"],
    }, schema),
    ("Numeric string with decimal", {
        "user_id": "42.0",
        "name": "Decimal test",
        "active": 1,
        "tags": [],
    }, schema),
]

for label, data, sch in test_cases:
    resp = requests.post(URL, json={"data": data, "schema": sch})
    print(f"=== {label} ===")
    print(f"status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    print()
