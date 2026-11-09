"""Repair almost-JSON text, typically model output, into real JSON.

Handles: markdown code fences, text around the JSON, comments, trailing and
extra commas, single quotes, unquoted keys, Python and JavaScript literals
(True, None, undefined), NaN and Infinity, raw newlines inside strings, and
output cut off before the brackets were closed.

Pure and deterministic. It never guesses a missing value: if the text cannot
be repaired safely it raises RepairError.
"""
import json
import math
import re

MAX_DEPTH = 100

_FENCE_BLOCK = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.S)
_FENCE_INLINE = re.compile(r"```(.*?)```", re.S)
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_KEY = re.compile(r"[A-Za-z_$][A-Za-z0-9_$-]*")
_WORD = re.compile(r"[A-Za-z_]+")
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "'": "'"}
_LITERALS = {
    "true": True, "True": True, "TRUE": True,
    "false": False, "False": False, "FALSE": False,
    "null": None, "None": None, "NULL": None, "nil": None, "undefined": None,
}


class RepairError(ValueError):
    """Raised when the text cannot be repaired safely."""


class _Fixes:
    def __init__(self):
        self._counts = {}

    def add(self, message, count=1):
        self._counts[message] = self._counts.get(message, 0) + count

    def render(self):
        return [m if n == 1 else f"{m} ({n})" for m, n in self._counts.items()]


def _reject_constant(name):
    raise ValueError("invalid JSON constant")


def _checked_float(text):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("number out of range")
    return number


def _strict(text):
    try:
        return True, json.loads(text, parse_constant=_reject_constant, parse_float=_checked_float)
    except (ValueError, RecursionError):
        return False, None


def _unfence(text):
    match = _FENCE_BLOCK.search(text)
    if match:
        return match.group(1).strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        if len(parts) == 2:
            return parts[1].strip().rstrip("`").strip()
    match = _FENCE_INLINE.search(text)
    if match:
        return match.group(1).strip()
    return None


def _find_span(text, begin=0):
    """Return (start, end) of the next JSON-looking value at or after begin, or None."""
    start = None
    for index in range(begin, len(text)):
        if text[index] in "{[":
            start = index
            break
    if start is None:
        return None
    depth = 0
    quote = None
    i = start
    n = len(text)
    while i < n:
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return start, n


class _Parser:
    def __init__(self, text, fixes):
        self.s = text
        self.n = len(text)
        self.i = 0
        self.fixes = fixes
        self.depth = 0

    def fail(self, message):
        raise RepairError(f"{message} at position {self.i}")

    def skip(self):
        s, n = self.s, self.n
        while self.i < n:
            char = s[self.i]
            if char.isspace() or char == "\ufeff":
                self.i += 1
            elif s.startswith("//", self.i) or char == "#":
                end = s.find("\n", self.i)
                self.i = n if end < 0 else end + 1
                self.fixes.add("removed comments")
            elif s.startswith("/*", self.i):
                end = s.find("*/", self.i + 2)
                self.i = n if end < 0 else end + 2
                self.fixes.add("removed comments")
            else:
                break

    def parse(self):
        self.skip()
        value = self.value()
        self.skip()
        if self.i < self.n:
            self.fail("unexpected text after the JSON")
        return value

    def value(self):
        self.skip()
        if self.i >= self.n:
            self.fail("unexpected end of text")
        char = self.s[self.i]
        if char == "{":
            return self.container(self.parse_object)
        if char == "[":
            return self.container(self.parse_array)
        if char in "\"'":
            return self.string()
        if char in "-+.0123456789":
            return self.number()
        return self.word()

    def container(self, parser):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.fail("JSON is nested too deeply")
        try:
            return parser()
        finally:
            self.depth -= 1

    def parse_object(self):
        self.i += 1
        result = {}
        while True:
            self.skip()
            if self.i >= self.n:
                self.fixes.add("closed unclosed brackets")
                return result
            char = self.s[self.i]
            if char == "}":
                self.i += 1
                return result
            if char == ",":
                self.i += 1
                self.fixes.add("removed extra comma")
                continue
            if char in "\"'":
                key = self.string()
            else:
                match = _KEY.match(self.s, self.i)
                if not match:
                    self.fail("expected a key")
                key = match.group()
                self.i = match.end()
                self.fixes.add("quoted unquoted keys")
            self.skip()
            if self.i >= self.n or self.s[self.i] != ":":
                self.fail("expected ':' after key")
            self.i += 1
            result[key] = self.value()
            self.skip()
            if self.i >= self.n:
                continue
            char = self.s[self.i]
            if char == ",":
                self.i += 1
                self.skip()
                if self.i >= self.n or self.s[self.i] == "}":
                    self.fixes.add("removed trailing comma")
            elif char != "}":
                self.fail("expected ',' or '}'")

    def parse_array(self):
        self.i += 1
        result = []
        while True:
            self.skip()
            if self.i >= self.n:
                self.fixes.add("closed unclosed brackets")
                return result
            char = self.s[self.i]
            if char == "]":
                self.i += 1
                return result
            if char == ",":
                self.i += 1
                self.fixes.add("removed extra comma")
                continue
            result.append(self.value())
            self.skip()
            if self.i >= self.n:
                continue
            char = self.s[self.i]
            if char == ",":
                self.i += 1
                self.skip()
                if self.i >= self.n or self.s[self.i] == "]":
                    self.fixes.add("removed trailing comma")
            elif char != "]":
                self.fail("expected ',' or ']'")

    def string(self):
        quote = self.s[self.i]
        if quote == "'":
            self.fixes.add("converted single quotes to double quotes")
        self.i += 1
        out = []
        s, n = self.s, self.n
        while True:
            if self.i >= n:
                self.fail("unterminated string")
            char = s[self.i]
            if char == quote:
                self.i += 1
                return "".join(out)
            if char == "\\":
                self.i += 1
                if self.i >= n:
                    self.fail("unterminated string")
                esc = s[self.i]
                if esc == "u":
                    hex_digits = s[self.i + 1:self.i + 5]
                    if len(hex_digits) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hex_digits):
                        self.fail("bad unicode escape")
                    code = int(hex_digits, 16)
                    self.i += 5
                    if 0xD800 <= code < 0xDC00 and s.startswith("\\u", self.i):
                        low_digits = s[self.i + 2:self.i + 6]
                        if re.fullmatch(r"[dD][c-fC-F][0-9a-fA-F]{2}", low_digits):
                            code = 0x10000 + ((code - 0xD800) << 10) + (int(low_digits, 16) - 0xDC00)
                            self.i += 6
                    out.append(chr(code))
                elif esc in _ESCAPES:
                    out.append(_ESCAPES[esc])
                    self.i += 1
                else:
                    out.append("\\" + esc)
                    self.i += 1
                    self.fixes.add("kept invalid escape sequences as text")
                continue
            if char < " ":
                self.fixes.add("escaped control characters inside strings")
            out.append(char)
            self.i += 1

    def number(self):
        match = _NUMBER.match(self.s, self.i)
        if not match:
            return self.word()
        text = match.group()
        self.i = match.end()
        canonical = re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
        if not canonical:
            self.fixes.add("normalized number format")
        if re.search(r"[.eE]", text):
            number = float(text)
            if not math.isfinite(number):
                self.fail("number out of range")
            return number
        try:
            return int(text)
        except ValueError:
            self.fail("number out of range")

    def word(self):
        negative = self.s.startswith("-", self.i)
        start = self.i + 1 if negative else self.i
        match = _WORD.match(self.s, start)
        if not match:
            self.fail("unexpected character")
        word = match.group()
        if word in ("NaN", "Infinity"):
            self.i = match.end()
            self.fixes.add("replaced NaN or Infinity with null")
            return None
        if not negative and word in _LITERALS:
            self.i = match.end()
            if word not in ("true", "false", "null"):
                self.fixes.add("converted Python or JavaScript literals to JSON")
            return _LITERALS[word]
        self.fail("unexpected text")


MAX_CANDIDATES = 12


def _candidates(text):
    """Find every value in the text that parses. Returns (found, first_error).

    found is a list of (start, end, value, fixes_list).
    """
    found = []
    first_error = None
    position = 0
    tries = 0
    while tries < MAX_CANDIDATES:
        span = _find_span(text, position)
        if span is None:
            break
        tries += 1
        begin, finish = span
        piece = text[begin:finish]
        ok, value = _strict(piece)
        if ok:
            found.append((begin, finish, value, []))
            position = finish
            continue
        local = _Fixes()
        try:
            value = _Parser(piece, local).parse()
        except RepairError as exc:
            if first_error is None:
                first_error = exc
            position = begin + 1
            continue
        found.append((begin, finish, value, local.render()))
        position = finish
    return found, first_error


def repair_json(text):
    """Return (value, fixes). Raises RepairError if the text cannot be repaired safely."""
    fixes = _Fixes()
    s = text
    if s.startswith("\ufeff"):
        s = s[1:]
        fixes.add("removed byte order mark")
    s = s.strip()
    if not s:
        raise RepairError("text is empty")

    ok, value = _strict(s)
    if ok:
        return value, fixes.render()

    unfenced = _unfence(s)
    if unfenced:
        s = unfenced
        fixes.add("removed markdown code fence")
        ok, value = _strict(s)
        if ok:
            return value, fixes.render()

    found, first_error = _candidates(s)
    if not found:
        if first_error is not None:
            raise first_error
        value = _Parser(s, fixes).parse()
        return value, fixes.render()

    objects = [item for item in found if isinstance(item[2], dict)]
    if len(objects) > 1:
        raise RepairError("more than one JSON object found, send only one")
    if objects:
        chosen = objects[0]
    elif len(found) == 1:
        chosen = found[0]
    else:
        raise RepairError("more than one JSON value found, send only one")

    begin, finish, value, local_fixes = chosen
    if (begin, finish) != (0, len(s)):
        fixes.add("extracted JSON from surrounding text")
    result = fixes.render()
    for message in local_fixes:
        result.append(message)
    return value, result
