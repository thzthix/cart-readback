"""Bounded input validation and canonical hashing, independent of inference."""

import hashlib
import json
import re
from typing import Any

MAX_BODY_BYTES = 16_384
MAX_JSON_DEPTH = 4
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


class AppError(Exception):
    """An expected fail-closed API error with a safe public description."""

    def __init__(self, code: str, message: str, status: int = 400):
        """Initialize a public error; never include secrets in its message."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def canonical(value: Any) -> str:
    """Return a stable JSON representation, rejecting non-finite numbers."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    """Hash canonical UTF-8 JSON, not an assertion of semantic truth."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    """Hash exact source bytes with no Unicode normalization."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def object_fields(value: Any, required: set[str]) -> dict:
    """Require an object with exactly the declared fields."""
    if type(value) is not dict or set(value) != required:
        raise AppError("INVALID_FIELDS", "Unexpected or missing JSON fields.")
    return value


def string(
    value: Any,
    name: str,
    maximum: int = 160,
    multiline: bool = False,
) -> str:
    """Require a nonempty bounded Unicode string without control codes."""
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(
            (ord(char) < 32 and not (multiline and char in "\n\t"))
            or 0xD800 <= ord(char) <= 0xDFFF
            for char in value
        )
    ):
        raise AppError("INVALID_TYPE", f"{name} must be a bounded string.")
    return value


def integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    """Require a real integer, excluding Python's bool/int subtype overlap."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise AppError("INVALID_TYPE", f"{name} must be an integer in range.")
    return value


def token(value: Any) -> str:
    """Require a bounded ASCII operation/CSRF token before comparisons."""
    if type(value) is not str or not TOKEN.fullmatch(value):
        raise AppError("INVALID_TOKEN", "Invalid ASCII token.")
    return value


def identifiers(value: Any, name: str) -> list[str]:
    """Require up to two unique condition identifiers."""
    if type(value) is not list or len(value) > 2:
        raise AppError("INVALID_TYPE", f"{name} must be a short array.")
    result = [string(item, name) for item in value]
    if len(set(result)) != len(result):
        raise AppError("DUPLICATE_IDS", "Condition IDs must be unique.")
    return result


def conditions(value: Any) -> list[dict]:
    """Validate explicit buyer choices; never infer a missing preference."""
    allowed = {
        "layout": {"UK_QWERTY", "DE_QWERTZ", "US_QWERTY"},
        "included_cable": {
            "USB-C to USB-C",
            "USB-A to USB-C",
            "any cable",
        },
    }
    if type(value) is not list or not 1 <= len(value) <= 2:
        raise AppError("INVALID_CONDITIONS", "Choose one or two conditions.")
    result = []
    for item in value:
        object_fields(item, {"kind", "value"})
        kind = string(item["kind"], "kind")
        choice = string(item["value"], "value")
        if kind not in allowed or choice not in allowed[kind]:
            raise AppError("INVALID_CONDITIONS", "Unsupported condition.")
        result.append({"kind": kind, "value": choice})
    if len({item["kind"] for item in result}) != len(result):
        raise AppError("DUPLICATE_CONDITIONS", "Condition kinds must differ.")
    return result


def _pairs(items: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise AppError("DUPLICATE_JSON_KEY", "Duplicate JSON key.")
        result[key] = value
    return result


def parse_json(raw: bytes) -> dict:
    """Decode bounded strict JSON after a nonrecursive nesting preflight.

    The preflight prevents json.loads RecursionError on malicious nesting.
    Escaped brackets in strings do not count as structure.
    """
    if len(raw) > MAX_BODY_BYTES:
        raise AppError("BODY_TOO_LARGE", "Request body too large.", 413)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        depth = 0
        in_string = False
        escaped = False
        for char in decoded:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    raise AppError("JSON_TOO_DEEP", "JSON nesting too deep.")
            elif char in "]}":
                depth -= 1

        def reject_constant(_value: str) -> None:
            raise AppError("INVALID_JSON", "Non-finite JSON number.")

        value = json.loads(
            decoded,
            object_pairs_hook=_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise AppError("INVALID_JSON", "Malformed UTF-8 JSON.") from error
    if type(value) is not dict:
        raise AppError("INVALID_JSON", "Top-level JSON must be an object.")
    return value
