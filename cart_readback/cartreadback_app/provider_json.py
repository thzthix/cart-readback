"""Strict provider-only JSON bounds, separate from inbound HTTP policy."""

import json
import math
from typing import Any

from cartreadback_app.validation import AppError

PARSER_VERSION = "provider-strict-json-v1"


def _invalid() -> AppError:
    return AppError("INVALID_PROPOSAL", "Invalid provider JSON.", 422)


def _pairs(items: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise _invalid()


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise _invalid()
    return result


def strict_provider_json(raw: bytes, *, max_bytes: int, max_depth: int) -> dict:
    """Parse one bounded object without repair or Unicode normalization.

    Escaped LF/TAB are allowed for exact multiline quotations. Field validators
    reject these in explanations/identifiers. All other C0 controls and lone
    surrogates are rejected everywhere, including otherwise ignored envelope
    fields. Raw unescaped controls remain invalid JSON.
    """
    if type(raw) is not bytes or len(raw) > max_bytes:
        raise _invalid()
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
                if depth > max_depth:
                    raise _invalid()
            elif char in "]}":
                depth -= 1
        value = json.loads(
            decoded,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
        pending = [value]
        while pending:
            item = pending.pop()
            if type(item) is dict:
                pending.extend(item.keys())
                pending.extend(item.values())
            elif type(item) is list:
                pending.extend(item)
            elif type(item) is str and any(
                (ord(char) < 32 and char not in "\n\t")
                or 0xD800 <= ord(char) <= 0xDFFF
                for char in item
            ):
                raise _invalid()
    except (UnicodeError, ValueError, RecursionError) as error:
        raise _invalid() from error
    if type(value) is not dict:
        raise _invalid()
    return value
