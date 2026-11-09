import pytest

from repair import RepairError, repair_json


def test_valid_json_needs_no_fixes():
    assert repair_json('{"a": [1, 2]}') == ({"a": [1, 2]}, [])


@pytest.mark.parametrize("text,expected,fixes", [
    ('```json\n{"a": 1}\n```', {"a": 1}, ["removed markdown code fence"]),
    ('```\n{"a": 1}\n```', {"a": 1}, ["removed markdown code fence"]),
    ('```json\n{"a": 1}', {"a": 1}, ["removed markdown code fence"]),
    ('Sure! Here you go: {"a": 1} Hope that helps.', {"a": 1}, ["extracted JSON from surrounding text"]),
    ('{"a": 1,}', {"a": 1}, ["removed trailing comma"]),
    ('[1, 2, 3,]', [1, 2, 3], ["removed trailing comma"]),
    ('{"a": 1,, "b": 2}', {"a": 1, "b": 2}, ["removed extra comma"]),
    ("{'a': 'x'}", {"a": "x"}, ["converted single quotes to double quotes (2)"]),
    ('{a: 1, b_2: 2}', {"a": 1, "b_2": 2}, ["quoted unquoted keys (2)"]),
    ('{"a": True, "b": None, "c": undefined}', {"a": True, "b": None, "c": None},
     ["converted Python or JavaScript literals to JSON (3)"]),
    ('{"a": NaN, "b": -Infinity}', {"a": None, "b": None}, ["replaced NaN or Infinity with null (2)"]),
    ('{"a": 1, // note\n"b": 2}', {"a": 1, "b": 2}, ["removed comments"]),
    ('{"a": /* x */ 1}', {"a": 1}, ["removed comments"]),
    ('{"a": [1, 2, {"b": 3', {"a": [1, 2, {"b": 3}]}, ["closed unclosed brackets (3)"]),
    ('{"a": "x\ny"}', {"a": "x\ny"}, ["escaped control characters inside strings"]),
    ('{"a": +5, "b": .5, "c": 007}', {"a": 5, "b": 0.5, "c": 7}, ["normalized number format (3)"]),
    ('{"a": "\\d"}', {"a": "\\d"}, ["kept invalid escape sequences as text"]),
    ("\ufeff" + '{"a": 1}', {"a": 1}, ["removed byte order mark"]),
])
def test_repairs(text, expected, fixes):
    value, reported = repair_json(text)
    assert value == expected
    assert reported == fixes


def test_several_fixes_at_once_in_a_fixed_order():
    text = "Here is the result:\n```json\n{'name': 'Frenzo', active: True, tags: ['a', 'b',],}\n```\nDone."
    value, fixes = repair_json(text)
    assert value == {"name": "Frenzo", "active": True, "tags": ["a", "b"]}
    assert fixes == [
        "removed markdown code fence",
        "converted single quotes to double quotes (4)",
        "quoted unquoted keys (2)",
        "converted Python or JavaScript literals to JSON",
        "removed trailing comma (2)",
    ]


def test_unicode_and_surrogate_pairs():
    assert repair_json(r"{'a': '\u00e9 \ud83d\ude00'}")[0] == {"a": "\u00e9 \U0001f600"}


def test_apostrophes_in_prose_before_the_json_are_fine():
    assert repair_json("Here's the data: {\"a\": 1,}")[0] == {"a": 1}


def test_top_level_values():
    assert repair_json("[1, 2,]")[0] == [1, 2]
    assert repair_json("'hello'")[0] == "hello"
    assert repair_json("True")[0] is True


@pytest.mark.parametrize("text", [
    "", "   ", "no json here", '{"a": }', '{"a": "unterminated', '{"a" 1}', '{"a": 1 "b": 2}',
    '[1 2]', '{"a": ok}', '{"a": 1} {"b": 2}', "{" * 500, "[" * 500, '{"a": 1e999}', '{"a": "\\u12"}',
])
def test_text_that_cannot_be_repaired_raises(text):
    with pytest.raises(RepairError):
        repair_json(text)


def test_error_messages_do_not_echo_the_input():
    with pytest.raises(RepairError) as info:
        repair_json('{"secret-key": SECRET-VALUE}')
    assert "SECRET" not in str(info.value)


def test_repair_is_deterministic():
    text = "```json\n{'a': True, b: [1,2,],}\n```"
    assert repair_json(text) == repair_json(text)


def test_prose_with_brackets_before_the_object():
    text = "Here are the 3 items [see note]: {\"a\": 1}"
    assert repair_json(text) == ({"a": 1}, ["extracted JSON from surrounding text"])


def test_prose_with_a_bracket_citation_after_the_object():
    assert repair_json('{"a": 1} (see [1])')[0] == {"a": 1}


def test_braces_in_prose_that_are_not_json_are_skipped():
    assert repair_json('Use {name} here: {"a": 1}')[0] == {"a": 1}


def test_two_objects_are_refused_not_silently_truncated():
    with pytest.raises(RepairError) as info:
        repair_json('{"a": 1} and also {"b": 2}')
    assert "more than one JSON object" in str(info.value)


def test_two_arrays_are_refused():
    with pytest.raises(RepairError):
        repair_json("first [1, 2] then [3, 4]")


def test_huge_integers_do_not_crash():
    with pytest.raises(RepairError):
        repair_json('{"a": ' + "9" * 5000 + "}")


def test_infinite_numbers_never_come_out():
    for text in ('{"a": 1e999}', '[1e999]', '{"a": -1e999}'):
        with pytest.raises(RepairError):
            repair_json(text)
