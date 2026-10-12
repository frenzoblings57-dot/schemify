import pytest

from normalizer import SchemaError, coerce_type, normalize


def test_messy_user_example():
    out = normalize(
        {"UserID": "123", "Name": "Frenzo"},
        {"user_id": "number", "name": "string", "active": "boolean"},
    )
    assert out["normalized"] == {"user_id": 123, "name": "Frenzo"}
    assert out["changes"] == [
        "mapped key 'Name' -> 'name'",
        "mapped key 'UserID' -> 'user_id'",
        "'user_id': coerced string to number",
    ]
    assert out["errors"] == ["'active': required field missing entirely"]


def test_bool_is_not_a_number():
    assert coerce_type(True, "number") == (None, False, "boolean cannot become number")


def test_null_is_a_clear_error():
    assert coerce_type(None, "string") == (None, False, "value is null")
    out = normalize({"a": None}, {"a": "number"})
    assert out["errors"] == ["'a': value is null"]
    assert out["normalized"] == {}


@pytest.mark.parametrize(
    "text,expected",
    [("42.0", 42), ("42.5", 42.5), (" 7 ", 7), ("1e3", 1000), ("-3", -3), ("12345678901234567890", 12345678901234567890)],
)
def test_numeric_strings(text, expected):
    value, ok, _ = coerce_type(text, "number")
    assert ok and value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-Infinity", "1_000", "0x10", "", "abc", "1e999", "9" * 65])
def test_bad_numeric_strings_are_rejected(text):
    _, ok, _ = coerce_type(text, "number")
    assert not ok


@pytest.mark.parametrize("text", ["true", "TRUE", " Yes ", "1"])
def test_true_strings(text):
    assert coerce_type(text, "boolean")[:2] == (True, True)


@pytest.mark.parametrize("text", ["false", "False", "NO", "0"])
def test_false_strings(text):
    assert coerce_type(text, "boolean")[:2] == (False, True)


def test_bad_boolean_values():
    assert not coerce_type("maybe", "boolean")[1]
    assert not coerce_type(2, "boolean")[1]
    assert coerce_type(1, "boolean")[:2] == (True, True)
    assert not coerce_type([1], "boolean")[1]


def test_duplicate_normalized_keys_are_a_collision_not_a_guess():
    out = normalize({"user_id": 1, "UserID": 2}, {"user_id": "number"})
    assert out["normalized"] == {}
    assert out["errors"] == ["'user_id': ambiguous input keys 'UserID', 'user_id'"]


def test_unsupported_schema_type_raises():
    with pytest.raises(SchemaError) as info:
        normalize({"a": 1}, {"a": "integer", "b": 5})
    assert "'a': unsupported type" in str(info.value)
    assert "'b': unsupported type 5" in str(info.value)


def test_array_and_object_rules():
    assert coerce_type("x", "array") == (["x"], True, "wrapped single value in array")
    assert coerce_type(["x"], "array") == (["x"], True, None)
    assert coerce_type({"a": 1}, "object") == ({"a": 1}, True, None)
    assert not coerce_type("x", "object")[1]


def test_string_coercion_rules():
    assert coerce_type(5, "string")[:2] == ("5", True)
    assert coerce_type(True, "string")[:2] == ("true", True)
    assert not coerce_type({"a": 1}, "string")[1]
    assert not coerce_type([1], "string")[1]


def test_unknown_input_fields_are_ignored():
    out = normalize({"a": "1", "extra": "x"}, {"a": "number"})
    assert out["normalized"] == {"a": 1}


def test_error_messages_do_not_echo_input_values():
    out = normalize({"a": "SECRET-VALUE"}, {"a": "number"})
    assert "SECRET-VALUE" not in "".join(out["errors"])


def test_deterministic():
    args = ({"UserID": "5", "Name": 3}, {"user_id": "number", "name": "string"})
    assert normalize(*args) == normalize(*args)


def test_output_does_not_depend_on_schema_key_order():
    data = {"UserID": "5", "Name": 3}
    one = normalize(data, {"user_id": "number", "name": "string"})
    two = normalize(data, {"name": "string", "user_id": "number"})
    assert one == two
