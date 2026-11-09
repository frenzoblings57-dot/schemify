"""Random-input tests. They must never crash, never emit invalid JSON, and be deterministic."""
import json
import random

from normalizer import SchemaError, SUPPORTED_TYPES, normalize
from repair import RepairError, repair_json

TOKENS = [
    "{", "}", "[", "]", ":", ",", '"a"', "'b'", "1", "-2.5e3", "true", "None", "NaN", "Infinity",
    "//c\n", "/*x*/", "```json\n", "```", "\n", " ", "abc", "\\", '"', "'", "\u00e9", "1e999", "9" * 40,
    "#", "\\u00", "\\ud83d", "undefined", ".5", "007", "+3", "\ufeff", "\t", "{'k': 'v'}", '{"a": [1,]}',
]


def dumps_strict(value):
    return json.dumps(value, allow_nan=False)


def test_repair_never_crashes_on_random_token_soup():
    rng = random.Random(1234)
    for _ in range(4000):
        text = "".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 30)))
        try:
            value, fixes = repair_json(text)
        except RepairError:
            continue
        dumps_strict(value)
        assert all(isinstance(f, str) for f in fixes)
        assert repair_json(text) == (value, fixes)


def test_repair_never_crashes_on_mutated_valid_json():
    rng = random.Random(99)
    base = json.dumps({"name": "Frenzo", "tags": ["a", "b"], "n": [1, 2.5, None, True], "o": {"x": {"y": "z"}}})
    for _ in range(4000):
        chars = list(base)
        for _ in range(rng.randint(1, 4)):
            op = rng.choice(["delete", "insert", "swap"])
            index = rng.randrange(len(chars))
            if op == "delete":
                del chars[index]
            elif op == "insert":
                chars.insert(index, rng.choice('{}[]:,"\' \n/#\\'))
            else:
                other = rng.randrange(len(chars))
                chars[index], chars[other] = chars[other], chars[index]
            if not chars:
                chars = list("{}")
        text = "".join(chars)
        try:
            value, _ = repair_json(text)
        except RepairError:
            continue
        dumps_strict(value)


def random_spec(rng, depth=0):
    kind = rng.choice(SUPPORTED_TYPES + ("bogus",))
    if rng.random() < 0.4 and depth < 3:
        spec = {"type": kind}
        if kind == "object" and rng.random() < 0.7:
            spec["properties"] = {f"f{i}": random_spec(rng, depth + 1) for i in range(rng.randint(1, 3))}
        if kind == "array" and rng.random() < 0.7:
            spec["items"] = random_spec(rng, depth + 1)
        if kind == "string" and rng.random() < 0.5:
            spec["enum"] = rng.sample(["a", "B", "c", "D"], rng.randint(1, 3))
        if rng.random() < 0.3:
            spec["required"] = rng.random() < 0.5
        if rng.random() < 0.3:
            spec["default"] = rng.choice([1, "x", [1], {"a": 1}, "2026-01-01", True])
        return spec
    return kind


def random_value(rng, depth=0):
    choices = [None, True, False, 0, 1, -7, 3.5, "", "42", "$1,200", "12%", "23 Oct 2026", "yes", "ABC", "a",
               "03/04/2026", "nan", "1e3"]
    if depth < 3:
        choices += ["obj", "list"]
    pick = rng.choice(choices)
    if pick == "obj":
        return {rng.choice(["f0", "F1", "f_2", "f-0", "x"]): random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))}
    if pick == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return pick


def test_normalize_never_crashes_and_stays_deterministic():
    rng = random.Random(7)
    ok = 0
    for _ in range(4000):
        schema = {f"f{i}": random_spec(rng) for i in range(rng.randint(1, 4))}
        data = {rng.choice(["f0", "F1", "f_2", "f-3", "x"]): random_value(rng) for _ in range(rng.randint(0, 4))}
        try:
            first = normalize(data, schema)
        except SchemaError:
            continue
        ok += 1
        dumps_strict(first)
        assert first == normalize(data, schema)
        assert set(first) == {"normalized", "changes", "errors"}
    assert ok > 500
