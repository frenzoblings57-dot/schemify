import pytest

from normalizer import SchemaError, coerce_type, compile_schema, normalize


# ----------------------------------------------------------------- new types

@pytest.mark.parametrize("value,expected", [("42", 42), ("42.0", 42), (7.0, 7), (" 9 ", 9), (5, 5)])
def test_integer_accepts_whole_numbers(value, expected):
    converted, ok, _ = coerce_type(value, "integer")
    assert ok and converted == expected and type(converted) is int


@pytest.mark.parametrize("value", ["42.5", 4.5, True, "abc", [1], {"a": 1}, "nan"])
def test_integer_rejects_the_rest(value):
    assert not coerce_type(value, "integer")[1]


@pytest.mark.parametrize("text,expected", [
    ("$1,200", 1200), ("$1,200.50", 1200.5), ("USD 1,200", 1200), ("1,200 USD", 1200),
    ("(1,200)", -1200), ("-$5", -5), ("$-5", -5), ("\u20a61,000,000", 1000000),
    ("12.00", 12), ("0.5", 0.5), (".5", 0.5), ("1200", 1200),
])
def test_money_strings(text, expected):
    converted, ok, _ = coerce_type(text, "money")
    assert ok and converted == expected


@pytest.mark.parametrize("text", ["1.200,50", "$", "abc", "1,20", "12,3456", "$$5", "(-5)", "1e3", "", "5 5", "--5"])
def test_money_rejects_ambiguous_or_bad_text(text):
    assert not coerce_type(text, "money")[1]


@pytest.mark.parametrize("text,expected", [("12%", 12), ("12.5 %", 12.5), ("-3%", -3), ("40", 40)])
def test_percent_strings(text, expected):
    converted, ok, _ = coerce_type(text, "percent")
    assert ok and converted == expected


def test_percent_rejects_garbage():
    assert not coerce_type("12%%", "percent")[1]
    assert not coerce_type("abc%", "percent")[1]
    assert not coerce_type(True, "percent")[1]


@pytest.mark.parametrize("text", [
    "2026-10-23", "2026/10/23", "2026.10.23", "20261023", "23 Oct 2026", "23 October 2026",
    "October 23, 2026", "Oct 23 2026", "Oct. 23, 2026", "23-Oct-2026", "23rd October 2026",
    "2026-10-23T14:30:00Z", "2026-10-23 14:30", "23/10/2026", "10/23/2026", "23.10.2026",
])
def test_dates_become_iso(text):
    assert coerce_type(text, "date")[:2] == ("2026-10-23", True)


def test_ambiguous_dates_are_rejected_not_guessed():
    value, ok, note = coerce_type("03/04/2026", "date")
    assert not ok and "ambiguous" in note
    assert coerce_type("05/05/2026", "date")[:2] == ("2026-05-05", True)


@pytest.mark.parametrize("text", ["2026-02-30", "31/04/2026", "13/13/2026", "yesterday", "26-10-23", "99 Oct 2026", "", "Octember 5 2026"])
def test_bad_dates_are_rejected(text):
    assert not coerce_type(text, "date")[1]


def test_dates_only_from_strings():
    assert not coerce_type(1700000000, "date")[1]


def test_iso_date_input_is_unchanged_and_silent():
    out = normalize({"d": "2026-10-23"}, {"d": "date"})
    assert out["normalized"] == {"d": "2026-10-23"} and out["changes"] == []


# ----------------------------------------------------------------- required, default, enum

def test_optional_field_may_be_missing():
    out = normalize({}, {"nick": {"type": "string", "required": False}})
    assert out == {"normalized": {}, "changes": [], "errors": []}


def test_default_is_used_for_missing_and_null():
    schema = {"retries": {"type": "integer", "default": 3}}
    missing = normalize({}, schema)
    assert missing["normalized"] == {"retries": 3}
    assert missing["changes"] == ["'retries': used default value"]
    null = normalize({"retries": None}, schema)
    assert null["normalized"] == {"retries": 3}
    assert null["changes"] == ["'retries': null replaced with default value"]


def test_default_is_normalized_and_not_shared():
    schema = {"tags": {"type": "array", "default": ["a"]}}
    first = normalize({}, schema)["normalized"]["tags"]
    first.append("mutated")
    assert normalize({}, schema)["normalized"]["tags"] == ["a"]


def test_optional_null_is_omitted_with_a_note():
    out = normalize({"nick": None}, {"nick": {"type": "string", "required": False}})
    assert out["normalized"] == {} and out["errors"] == []
    assert out["changes"] == ["'nick': null omitted (field is optional)"]


def test_enum_matches_ignoring_case_and_spaces():
    schema = {"status": {"type": "string", "enum": ["active", "closed"]}}
    out = normalize({"status": " ACTIVE "}, schema)
    assert out["normalized"] == {"status": "active"}
    assert out["changes"] == ["'status': matched allowed value"]


def test_enum_rejects_unknown_values_without_echoing_them():
    schema = {"status": {"type": "string", "enum": ["active", "closed"]}}
    out = normalize({"status": "SECRET-VALUE"}, schema)
    assert out["normalized"] == {}
    assert out["errors"] == ["'status': value is not one of the allowed values"]


# ----------------------------------------------------------------- nested data

NESTED = {
    "user": {"type": "object", "properties": {
        "id": "integer",
        "address": {"type": "object", "properties": {"zip": "string", "city": "string"}},
    }},
    "orders": {"type": "array", "items": {"type": "object", "properties": {
        "price": "money", "date": "date",
    }}},
}


def test_nested_objects_and_lists_of_objects():
    out = normalize({
        "User": {"ID": "7", "Address": {"Zip": 12345, "city": "Uyo"}},
        "orders": [{"price": "$1,200", "Date": "23 Oct 2026"}, {"price": 5, "date": "2026-01-02"}],
    }, NESTED)
    assert out["errors"] == []
    assert out["normalized"] == {
        "user": {"id": 7, "address": {"zip": "12345", "city": "Uyo"}},
        "orders": [{"price": 1200, "date": "2026-10-23"}, {"price": 5, "date": "2026-01-02"}],
    }
    assert "mapped key 'User' -> 'user'" in out["changes"]
    assert "mapped key 'user.Address' -> 'user.address'" in out["changes"]
    assert "'user.address.zip': coerced number to string" in out["changes"]
    assert "'orders[0].price': coerced money string to number" in out["changes"]


def test_nested_object_keeps_good_fields_and_reports_paths():
    out = normalize({"user": {"id": "x", "address": {"zip": "1", "city": "Uyo"}}, "orders": []}, NESTED)
    assert out["normalized"]["user"] == {"address": {"zip": "1", "city": "Uyo"}}
    assert out["errors"] == ["'user.id': could not coerce string to integer"]


def test_list_with_a_bad_item_is_left_out_and_every_bad_item_is_reported():
    out = normalize({
        "user": {"id": 1, "address": {"zip": "1", "city": "x"}},
        "orders": [{"price": "oops", "date": "2026-01-01"}, {"price": 1, "date": "nope"}],
    }, NESTED)
    assert "orders" not in out["normalized"]
    assert out["errors"] == [
        "'orders[0].price': could not coerce string to money",
        "'orders[1].date': could not coerce string to date",
    ]


def test_list_of_scalars_and_single_value_wrapping():
    schema = {"scores": {"type": "array", "items": "integer"}}
    assert normalize({"scores": ["1", 2.0]}, schema)["normalized"] == {"scores": [1, 2]}
    out = normalize({"scores": "5"}, schema)
    assert out["normalized"] == {"scores": [5]}
    assert "'scores': wrapped single value in array" in out["changes"]
    assert normalize({"scores": [1, None]}, schema)["errors"] == ["'scores[1]': value is null"]


def test_nested_object_defaults_and_optional_fields():
    schema = {"cfg": {"type": "object", "properties": {
        "mode": {"type": "string", "default": "fast"},
        "note": {"type": "string", "required": False},
    }}}
    out = normalize({"cfg": {}}, schema)
    assert out["normalized"] == {"cfg": {"mode": "fast"}}
    assert out["changes"] == ["'cfg.mode': used default value"]


def test_nested_key_collisions_are_reported():
    out = normalize({"a": {"x_y": 1, "XY": 2}}, {"a": {"type": "object", "properties": {"x_y": "number"}}})
    assert out["errors"] == ["'a.x_y': ambiguous input keys 'XY', 'x_y'"]


def test_object_field_given_a_non_object():
    out = normalize({"user": "bob"}, {"user": {"type": "object", "properties": {"id": "integer"}}})
    assert out["errors"] == ["'user': expected object, got str"]


# ----------------------------------------------------------------- schema validation

@pytest.mark.parametrize("schema,fragment", [
    ({"a": {"type": "float"}}, "'a': unsupported type \"float\""),
    ({"a": {}}, "'a': missing type"),
    ({"a": {"type": "string", "colour": 1}}, "'a': unknown option \"colour\""),
    ({"a": {"type": "string", "required": "yes"}}, "'a': required must be true or false"),
    ({"a": {"type": "number", "enum": ["x"]}}, "'a': enum is only supported for type string"),
    ({"a": {"type": "string", "enum": []}}, "'a': enum must be a non-empty list of strings"),
    ({"a": {"type": "string", "enum": ["X", " x "]}}, "'a': enum has duplicate values"),
    ({"a": {"type": "string", "properties": {"b": "string"}}}, "'a': properties is only supported for type object"),
    ({"a": {"type": "object", "properties": {}}}, "'a': properties must be a non-empty object"),
    ({"a": {"type": "string", "items": "string"}}, "'a': items is only supported for type array"),
    ({"a": {"type": "array", "items": {"type": "string", "default": "x"}}}, "'a[]': default and required are not supported"),
    ({"a": {"type": "string", "default": None}}, "'a': default cannot be null"),
    ({"a": {"type": "integer", "default": "abc"}}, "'a': default does not match the declared type"),
    ({"a": {"type": "string", "enum": ["x"], "default": "y"}}, "'a': default does not match the declared type"),
    ({"o": {"type": "object", "properties": {"b": {"type": "float"}}}}, "'o.b': unsupported type"),
])
def test_bad_schemas_raise_schema_error(schema, fragment):
    with pytest.raises(SchemaError) as info:
        compile_schema(schema)
    assert fragment in str(info.value)


def test_schema_depth_is_limited():
    schema = {"a": "string"}
    for _ in range(8):
        schema = {"n": {"type": "object", "properties": schema}}
    with pytest.raises(SchemaError) as info:
        compile_schema(schema)
    assert "nested too deeply" in str(info.value)


def test_simple_string_schemas_still_work_exactly_as_before():
    out = normalize({"UserID": "123", "Name": "Frenzo"},
                    {"user_id": "number", "name": "string", "active": "boolean"})
    assert out["normalized"] == {"user_id": 123, "name": "Frenzo"}
    assert out["errors"] == ["'active': required field missing entirely"]


def test_reports_are_capped():
    schema = {"items": {"type": "array", "items": "integer"}}
    out = normalize({"items": ["x"] * 500}, schema)
    assert len(out["errors"]) == 201
    assert out["errors"][-1] == "300 more errors omitted"


def test_rich_output_is_deterministic_and_order_independent():
    data = {"orders": [{"date": "23 Oct 2026", "price": "$5"}], "user": {"address": {"zip": 1, "city": "a"}, "id": "2"}}
    reordered = dict(reversed(list(NESTED.items())))
    assert normalize(data, NESTED) == normalize(data, NESTED)
    assert normalize(data, NESTED) == normalize(data, reordered)
