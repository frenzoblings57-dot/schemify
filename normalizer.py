"""Schemify core logic.

Normalize a JSON object against a schema and report every change.

Simple schema (unchanged since 0.1): {"user_id": "number", "name": "string"}

Rich schema (0.3): a field may be an object with these options.
    type        required. One of SUPPORTED_TYPES.
    required    false = a missing field is not an error (default true).
    default     value used when the field is missing or null.
    enum        (type string) allowed values, matched ignoring case and spaces.
    properties  (type object) schema for the fields inside the object.
    items       (type array) schema for every item in the list.

Everything here is a pure function: no network, no clock, no randomness.
The same input always gives the same output.
"""
import copy
import datetime
import json
import math
import re

SUPPORTED_TYPES = (
    "string", "number", "integer", "boolean", "array", "object",
    "date", "money", "percent",
)
MAX_SCHEMA_DEPTH = 6
MAX_REPORT_ITEMS = 200

_OPTIONS = ("type", "required", "default", "enum", "properties", "items")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_MAX_NUMBER_TEXT = 64
_SAFE_INT = 2 ** 53
_TRUE_WORDS = {"true", "1", "yes"}
_FALSE_WORDS = {"false", "0", "no"}

_LEAD_CURRENCY = re.compile(r"^(?:[A-Za-z]{3}\s+|[$\u20ac\u00a3\u00a5\u20a6]\s*)")
_TRAIL_CURRENCY = re.compile(r"(?:\s*[$\u20ac\u00a3\u00a5\u20a6]|\s+[A-Za-z]{3})$")
_MONEY_NUMBER = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^\.\d+$")

_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
)
_ISO_DATE = re.compile(
    r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DAY_MONTH_NAME = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})\.?,?[\s-]+(\d{4})$")
_MONTH_NAME_DAY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


class SchemaError(ValueError):
    """Raised when the schema itself is invalid."""


class Spec:
    __slots__ = ("type", "required", "has_default", "default", "enum", "properties", "items")

    def __init__(self, type_name):
        self.type = type_name
        self.required = True
        self.has_default = False
        self.default = None
        self.enum = None
        self.properties = None
        self.items = None


class _Report:
    """Collects changes and errors. Output is capped so responses stay small."""

    def __init__(self):
        self.changes = []
        self.errors = []
        self.more_changes = 0
        self.more_errors = 0
        self.error_count = 0

    def change(self, message):
        if len(self.changes) < MAX_REPORT_ITEMS:
            self.changes.append(message)
        else:
            self.more_changes += 1

    def error(self, message):
        self.error_count += 1
        if len(self.errors) < MAX_REPORT_ITEMS:
            self.errors.append(message)
        else:
            self.more_errors += 1

    def finish(self):
        changes, errors = list(self.changes), list(self.errors)
        if self.more_changes:
            changes.append(f"{self.more_changes} more changes omitted")
        if self.more_errors:
            errors.append(f"{self.more_errors} more errors omitted")
        return changes, errors


def normalize_key(key):
    """Compare keys ignoring case, underscores and hyphens."""
    return key.lower().replace("_", "").replace("-", "")


def _kind(value):
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


# ---------------------------------------------------------------- parsing helpers

def _number_from_text(text, noun="number"):
    """Parse a numeric string. Returns (number, error_message)."""
    text = text.strip()
    if len(text) > _MAX_NUMBER_TEXT:
        return None, "numeric string is too long"
    if _INT_RE.match(text):
        return int(text), None
    if not _NUMBER_RE.match(text):
        return None, f"could not coerce string to {noun}"
    number = float(text)
    if not math.isfinite(number):
        return None, "number out of range"
    if number.is_integer() and abs(number) < _SAFE_INT:
        number = int(number)
    return number, None


def _parse_money(text):
    """'$1,200.50', 'USD 1,200', '(1,200)', '-$5' become numbers. Returns (number, error)."""
    s = text.strip()
    if len(s) > _MAX_NUMBER_TEXT:
        return None, "numeric string is too long"
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.startswith("-"):
        if negative:
            return None, "could not coerce string to money"
        negative, s = True, s[1:].strip()
    s = _LEAD_CURRENCY.sub("", s, count=1).strip()
    if s.startswith("-"):
        if negative:
            return None, "could not coerce string to money"
        negative, s = True, s[1:].strip()
    s = _TRAIL_CURRENCY.sub("", s, count=1).strip()
    if not _MONEY_NUMBER.match(s):
        return None, "could not coerce string to money"
    plain = s.replace(",", "")
    number = float(plain) if "." in plain else int(plain)
    if isinstance(number, float):
        if not math.isfinite(number):
            return None, "number out of range"
        if number.is_integer() and abs(number) < _SAFE_INT:
            number = int(number)
    return (-number if negative else number), None


def _month_number(word):
    w = word.lower().rstrip(".")
    if len(w) < 3:
        return None
    for index, name in enumerate(_MONTH_NAMES, start=1):
        if name.startswith(w):
            return index
    return None


def _build_date(year, month, day, original, time_dropped=False):
    try:
        iso = datetime.date(year, month, day).isoformat()
    except ValueError:
        return None, "not a valid calendar date"
    if iso == original:
        return iso, None
    note = "converted date to ISO 8601"
    if time_dropped:
        note += " (time dropped)"
    return iso, note


def _parse_date(text):
    """Returns (iso_date, note) or (None, error_message). Never guesses day vs month."""
    s = text.strip()
    if not s or len(s) > 40:
        return None, "could not coerce string to date"
    m = _ISO_DATE.match(s)
    if m:
        return _build_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), s,
                           time_dropped=m.group(4) is not None)
    m = _COMPACT_DATE.match(s)
    if m:
        return _build_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), s)
    m = _DAY_MONTH_NAME.match(s)
    if m and _month_number(m.group(2)):
        return _build_date(int(m.group(3)), _month_number(m.group(2)), int(m.group(1)), s)
    m = _MONTH_NAME_DAY.match(s)
    if m and _month_number(m.group(1)):
        return _build_date(int(m.group(3)), _month_number(m.group(1)), int(m.group(2)), s)
    m = _NUMERIC_DATE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            return _build_date(year, b, a, s)
        if b > 12 and a <= 12:
            return _build_date(year, a, b, s)
        if a == b and a <= 12:
            return _build_date(year, a, b, s)
        if a <= 12 and b <= 12:
            return None, "ambiguous date, day and month could be swapped"
        return None, "not a valid calendar date"
    return None, "could not coerce string to date"


# ---------------------------------------------------------------- type coercion

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
            number, problem = _number_from_text(value)
            if problem:
                return None, False, problem
            return number, True, "coerced string to number"
        return None, False, f"cannot coerce {_kind(value)} to number"

    if target_type == "integer":
        if isinstance(value, bool):
            return None, False, "boolean cannot become integer"
        if isinstance(value, int):
            return value, True, None
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, False, "number is not finite"
            if value.is_integer():
                return int(value), True, "coerced number to integer"
            return None, False, "number is not a whole number"
        if isinstance(value, str):
            number, problem = _number_from_text(value, "integer")
            if problem:
                return None, False, problem
            if isinstance(number, float):
                return None, False, "number is not a whole number"
            return number, True, "coerced string to integer"
        return None, False, f"cannot coerce {_kind(value)} to integer"

    if target_type == "percent":
        if isinstance(value, bool):
            return None, False, "boolean cannot become percent"
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                return None, False, "number is not finite"
            return value, True, None
        if isinstance(value, str):
            text = value.strip()
            had_sign = text.endswith("%")
            if had_sign:
                text = text[:-1]
            number, problem = _number_from_text(text, "percent")
            if problem:
                return None, False, problem
            return number, True, ("converted percent string to number" if had_sign
                                  else "coerced string to number")
        return None, False, f"cannot coerce {_kind(value)} to percent"

    if target_type == "money":
        if isinstance(value, bool):
            return None, False, "boolean cannot become money"
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                return None, False, "number is not finite"
            return value, True, None
        if isinstance(value, str):
            number, problem = _parse_money(value)
            if problem:
                return None, False, problem
            return number, True, "coerced money string to number"
        return None, False, f"cannot coerce {_kind(value)} to money"

    if target_type == "date":
        if isinstance(value, str):
            iso, detail = _parse_date(value)
            if iso is None:
                return None, False, detail
            return iso, True, detail
        return None, False, f"cannot coerce {_kind(value)} to date"

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


# ---------------------------------------------------------------- schema compiling

def _shown(value):
    return json.dumps(value, sort_keys=True)[:40]


def _compile_spec(raw, label, depth, problems):
    if depth > MAX_SCHEMA_DEPTH:
        problems.append(f"'{label}': schema nested too deeply")
        return None
    if isinstance(raw, str):
        raw = {"type": raw}
    elif not isinstance(raw, dict):
        problems.append(f"'{label}': unsupported type {_shown(raw)}")
        return None

    before = len(problems)
    for key in sorted(k for k in raw if k not in _OPTIONS):
        problems.append(f"'{label}': unknown option {_shown(key)}")
    if "type" not in raw:
        problems.append(f"'{label}': missing type")
        return None
    declared = raw["type"]
    if not isinstance(declared, str) or declared not in SUPPORTED_TYPES:
        problems.append(f"'{label}': unsupported type {_shown(declared)}")
        return None

    spec = Spec(declared)
    if "required" in raw:
        if not isinstance(raw["required"], bool):
            problems.append(f"'{label}': required must be true or false")
        else:
            spec.required = raw["required"]

    if "enum" in raw:
        values = raw["enum"]
        if declared != "string":
            problems.append(f"'{label}': enum is only supported for type string")
        elif not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
            problems.append(f"'{label}': enum must be a non-empty list of strings")
        else:
            keys = [v.strip().casefold() for v in values]
            if len(set(keys)) != len(keys):
                problems.append(f"'{label}': enum has duplicate values")
            else:
                spec.enum = dict(zip(keys, values))

    if "properties" in raw:
        if declared != "object":
            problems.append(f"'{label}': properties is only supported for type object")
        elif not isinstance(raw["properties"], dict) or not raw["properties"]:
            problems.append(f"'{label}': properties must be a non-empty object")
        else:
            spec.properties = _compile_properties(raw["properties"], label, depth + 1, problems)

    if "items" in raw:
        if declared != "array":
            problems.append(f"'{label}': items is only supported for type array")
        else:
            raw_item = raw["items"]
            if isinstance(raw_item, dict) and ("default" in raw_item or "required" in raw_item):
                problems.append(f"'{label}[]': default and required are not supported for list items")
            else:
                item = _compile_spec(raw_item, f"{label}[]", depth + 1, problems)
                if item is not None:
                    spec.items = item

    if "default" in raw and raw["default"] is None:
        problems.append(f"'{label}': default cannot be null")

    if len(problems) > before:
        return None

    if "default" in raw:
        trial = _Report()
        ok, converted = _normalize_value(raw["default"], spec, label, trial)
        if not ok or trial.error_count:
            problems.append(f"'{label}': default does not match the declared type")
            return None
        spec.has_default = True
        spec.default = converted
    return spec


def _compile_properties(raw_props, path, depth, problems):
    props = {}
    for name in sorted(raw_props):
        label = f"{path}.{name}" if path else name
        spec = _compile_spec(raw_props[name], label, depth, problems)
        if spec is not None:
            props[name] = spec
    return props


def compile_schema(schema):
    """Validate a schema once and return a reusable compiled form. Raises SchemaError."""
    problems = []
    props = _compile_properties(schema, "", 1, problems)
    if problems:
        raise SchemaError("; ".join(sorted(problems)))
    return props


def validate_schema(schema):
    compile_schema(schema)


# ---------------------------------------------------------------- normalizing

def _handle_missing(spec, name, label, out, report):
    if spec.has_default:
        out[name] = copy.deepcopy(spec.default)
        report.change(f"'{label}': used default value")
    elif spec.required:
        report.error(f"'{label}': required field missing entirely")


def _normalize_value(value, spec, label, report):
    """Return (ok, converted). A failed value is left out and reported."""
    if value is None:
        if spec.has_default:
            report.change(f"'{label}': null replaced with default value")
            return True, copy.deepcopy(spec.default)
        if not spec.required:
            report.change(f"'{label}': null omitted (field is optional)")
            return False, None
        report.error(f"'{label}': value is null")
        return False, None

    if spec.type == "object" and spec.properties is not None:
        if not isinstance(value, dict):
            report.error(f"'{label}': expected object, got {_kind(value)}")
            return False, None
        return True, _normalize_object(value, spec.properties, label, report)

    if spec.type == "array" and spec.items is not None:
        if not isinstance(value, list):
            value = [value]
            report.change(f"'{label}': wrapped single value in array")
        results = []
        failed = False
        for index, element in enumerate(value):
            before = report.error_count
            ok, converted = _normalize_value(element, spec.items, f"{label}[{index}]", report)
            if not ok or report.error_count > before:
                failed = True
            else:
                results.append(converted)
        if failed:
            return False, None
        return True, results

    converted, ok, note = coerce_type(value, spec.type)
    if not ok:
        report.error(f"'{label}': {note}")
        return False, None
    if note:
        report.change(f"'{label}': {note}")
    if spec.enum is not None:
        canonical = spec.enum.get(converted.strip().casefold())
        if canonical is None:
            report.error(f"'{label}': value is not one of the allowed values")
            return False, None
        if canonical != converted:
            report.change(f"'{label}': matched allowed value")
        converted = canonical
    return True, converted


def _normalize_object(data, props, path, report):
    groups = {}
    for key in data:
        groups.setdefault(normalize_key(key), []).append(key)

    out = {}
    # Sorted so the same request gives the same bytes whatever the key order.
    for name in sorted(props):
        spec = props[name]
        label = f"{path}.{name}" if path else name
        keys = groups.get(normalize_key(name))
        if not keys:
            _handle_missing(spec, name, label, out, report)
            continue
        if len(keys) > 1:
            names = ", ".join(f"'{k}'" for k in sorted(keys))
            report.error(f"'{label}': ambiguous input keys {names}")
            continue
        actual = keys[0]
        if actual != name:
            actual_label = f"{path}.{actual}" if path else actual
            report.change(f"mapped key '{actual_label}' -> '{label}'")
        ok, converted = _normalize_value(data[actual], spec, label, report)
        if ok:
            out[name] = converted
    return out


def normalize_compiled(raw_data, props):
    report = _Report()
    normalized = _normalize_object(raw_data, props, "", report)
    changes, errors = report.finish()
    return {"normalized": normalized, "changes": changes, "errors": errors}


def normalize(raw_data, schema):
    """Return {"normalized": {...}, "changes": [...], "errors": [...]}.

    Unknown input fields are ignored. If two input keys collapse to the same
    schema field (for example "user_id" and "UserID") the field is reported as
    ambiguous instead of silently picking one.
    """
    return normalize_compiled(raw_data, compile_schema(schema))
