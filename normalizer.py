"""Schemify core logic.

Normalize a JSON object against a simple type schema and report every change.

Schema format (intentionally simple, not full JSON Schema):
    {"user_id": "number", "name": "string", "active": "boolean"}

Supported types: "string", "number", "boolean", "array", "object".
Unknown schema types are rejected with SchemaError (HTTP 422 in the API).
"""
import json
import math
import re

SUPPORTED_TYPES = ("string", "number", "boolean", "array", "object")

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_MAX_NUMBER_TEXT = 64
_SAFE_INT = 2 ** 53
_TRUE_WORDS = {"true", "1", "yes"}
_FALSE_WORDS = {"false", "0", "no"}


class SchemaError(ValueError):
    """Raised when the schema itself is invalid."""


def normalize_key(key):
    """Compare keys ignoring case, underscores and hyphens."""
    return key.lower().replace("_", "").replace("-", "")


def _kind(value):
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def validate_schema(schema):
    problems = []
    for field in sorted(schema):
        declared = schema[field]
        if not isinstance(declared, str) or declared not in SUPPORTED_TYPES:
            shown = json.dumps(declared, sort_keys=True)[:40]
            problems.append(f"'{field}': unsupported type {shown}")
    if problems:
        raise SchemaError("; ".join(problems))


def coerce_type(value, target_type):
    """Return (converted_value, ok, note). Error notes never echo input values."""
    if value is None:
        return None, False, "value is null"

    if target_type == "string":
        if isinstance(value, str):
            return value, True, None
        if isinstance(value, bool):
            return ("true" if value else "false"), True, "coerced boolean to string"
        if isinstance(value, int):
            return str(value), True, "coerced number to string"
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, False, "number is not finite"
            return repr(value), True, "coerced number to string"
        return None, False, f"cannot coerce {_kind(value)} to string"

    if target_type == "number":
        if isinstance(value, bool):
            return None, False, "boolean cannot become number"
        if isinstance(value, int):
            return value, True, None
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, False, "number is not finite"
            return value, True, None
        if isinstance(value, str):
            text = value.strip()
            if len(text) > _MAX_NUMBER_TEXT:
                return None, False, "numeric string is too long"
            if _INT_RE.match(text):
                return int(text), True, "coerced string to number"
            if not _NUMBER_RE.match(text):
                return None, False, "could not coerce string to number"
            number = float(text)
            if not math.isfinite(number):
                return None, False, "number out of range"
            if number.is_integer() and abs(number) < _SAFE_INT:
                number = int(number)
            return number, True, "coerced string to number"
        return None, False, f"cannot coerce {_kind(value)} to number"

    if target_type == "boolean":
        if isinstance(value, bool):
            return value, True, None
        if isinstance(value, str):
            word = value.strip().lower()
            if word in _TRUE_WORDS:
                return True, True, "coerced string to boolean"
            if word in _FALSE_WORDS:
                return False, True, "coerced string to boolean"
            return None, False, "could not coerce string to boolean"
        if isinstance(value, (int, float)):
            if value == 0 or value == 1:
                return bool(value), True, "coerced number to boolean"
            return None, False, "number is not 0 or 1"
        return None, False, f"cannot coerce {_kind(value)} to boolean"

    if target_type == "array":
        if isinstance(value, list):
            return value, True, None
        return [value], True, "wrapped single value in array"

    if target_type == "object":
        if isinstance(value, dict):
            return value, True, None
        return None, False, f"expected object, got {_kind(value)}"

    return None, False, "unsupported type"


def normalize(raw_data, schema):
    """Return {"normalized": {...}, "changes": [...], "errors": [...]}.

    Unknown input fields are ignored. If two input keys collapse to the same
    schema field (for example "user_id" and "UserID") the field is reported as
    ambiguous instead of silently picking one.
    """
    validate_schema(schema)

    groups = {}
    for key in raw_data:
        groups.setdefault(normalize_key(key), []).append(key)

    result = {}
    changes = []
    errors = []

    # Sorted so the same request always produces the same bytes, whatever the key order.
    for target_key in sorted(schema):
        target_type = schema[target_key]
        keys = groups.get(normalize_key(target_key))
        if not keys:
            errors.append(f"'{target_key}': required field missing entirely")
            continue
        if len(keys) > 1:
            names = ", ".join(f"'{k}'" for k in sorted(keys))
            errors.append(f"'{target_key}': ambiguous input keys {names}")
            continue

        actual_key = keys[0]
        if actual_key != target_key:
            changes.append(f"mapped key '{actual_key}' -> '{target_key}'")

        converted, ok, note = coerce_type(raw_data[actual_key], target_type)
        if ok:
            result[target_key] = converted
            if note:
                changes.append(f"'{target_key}': {note}")
        else:
            errors.append(f"'{target_key}': {note}")

    return {"normalized": result, "changes": changes, "errors": errors}
