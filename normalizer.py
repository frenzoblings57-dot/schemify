"""
Core logic: given messy JSON and a simple schema, return normalized JSON
plus a report of what was changed.

Schema format (kept intentionally simple, not full JSON Schema):
{
    "user_id": "number",
    "name": "string",
    "active": "boolean"
}

Supported types: "string", "number", "boolean", "array", "object"
"""

# Common key-name variants people use for the same field.
# This lets us match "userId", "user_id", "UserID" etc to one target key.
def normalize_key(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def coerce_type(value, target_type: str):
    """Try to convert value to target_type. Return (converted_value, ok, note)."""
    if value is None:
        return None, False, "missing value"

    if target_type == "string":
        if isinstance(value, str):
            return value, True, None
        return str(value), True, f"coerced {type(value).__name__} to string"

    if target_type == "number":
        if isinstance(value, bool):
            return None, False, "boolean cannot become number"
        if isinstance(value, (int, float)):
            return value, True, None
        try:
            num = float(value)
            if num.is_integer():
                num = int(num)
            return num, True, f"coerced string to number"
        except (ValueError, TypeError):
            return None, False, f"could not coerce '{value}' to number"

    if target_type == "boolean":
        if isinstance(value, bool):
            return value, True, None
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True, True, "coerced string to boolean"
            if value.lower() in ("false", "0", "no"):
                return False, True, "coerced string to boolean"
        if isinstance(value, (int, float)):
            return bool(value), True, "coerced number to boolean"
        return None, False, f"could not coerce '{value}' to boolean"

    if target_type == "array":
        if isinstance(value, list):
            return value, True, None
        return [value], True, "wrapped single value in array"

    if target_type == "object":
        if isinstance(value, dict):
            return value, True, None
        return None, False, f"expected object, got {type(value).__name__}"

    return value, True, None


def normalize(raw_data: dict, schema: dict) -> dict:
    """
    raw_data: the messy JSON payload
    schema: dict of field_name -> type_string

    Returns:
    {
        "normalized": {...},       # the cleaned data
        "changes": [...],          # human-readable list of what was fixed
        "errors": [...]            # fields that couldn't be fixed
    }
    """
    result = {}
    changes = []
    errors = []

    # Build a lookup of normalized-key -> actual-key from the raw data,
    # so we can match "UserID" in the input to "user_id" in the schema.
    raw_key_lookup = {normalize_key(k): k for k in raw_data.keys()}

    for target_key, target_type in schema.items():
        lookup_key = normalize_key(target_key)

        if lookup_key in raw_key_lookup:
            actual_key = raw_key_lookup[lookup_key]
            raw_value = raw_data[actual_key]

            if actual_key != target_key:
                changes.append(f"mapped key '{actual_key}' -> '{target_key}'")

            converted, ok, note = coerce_type(raw_value, target_type)
            if ok:
                result[target_key] = converted
                if note:
                    changes.append(f"'{target_key}': {note}")
            else:
                errors.append(f"'{target_key}': {note}")
        else:
            errors.append(f"'{target_key}': required field missing entirely")

    return {
        "normalized": result,
        "changes": changes,
        "errors": errors,
    }


if __name__ == "__main__":
    # Quick smoke test with a deliberately messy payload
    schema = {
        "user_id": "number",
        "name": "string",
        "active": "boolean",
    }

    messy_input = {
        "UserID": "123",
        "Name": "Frenzo",
        # "active" is missing entirely
    }

    import json
    output = normalize(messy_input, schema)
    print(json.dumps(output, indent=2))
