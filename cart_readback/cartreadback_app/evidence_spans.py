"""Mechanical source coordinates, never judgments or repaired model output."""

from cartreadback_app.validation import canonical

MAX_HINTS = 16
MAX_QUOTE_POINTS = 1000
MAX_HINT_BYTES = 8192
_LINE_ENDINGS = (
    "\r\n",
    "\n",
    "\r",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)


def evidence_span_hints(source):
    """Derive bounded exact slices from already validated original source.

    Offsets count decoded Unicode code points, never encoded bytes or graphemes.
    Line delimiters advance the original cursor but are not part of line quotes.
    A segment is only a copying aid; it does not establish relevance or truth.
    """
    text = source["text"]
    spans = []
    result = {
        "coordinate_system": "unicode-codepoint-half-open",
        "truncated": False,
        "spans": spans,
    }
    cursor = 0
    for line in text.splitlines(keepends=True):
        content = line
        for ending in _LINE_ENDINGS:
            if content.endswith(ending):
                content = content[: -len(ending)]
                break
        for offset in range(0, len(content), MAX_QUOTE_POINTS):
            start = cursor + offset
            end = min(cursor + len(content), start + MAX_QUOTE_POINTS)
            hint = {
                "source_id": source["source_id"],
                "start": start,
                "end": end,
                "quote": text[start:end],
            }
            if len(spans) >= MAX_HINTS:
                result["truncated"] = True
                return result if spans else None
            spans.append(hint)
            if len(canonical(result).encode("utf-8")) > MAX_HINT_BYTES:
                spans.pop()
                result["truncated"] = True
                return result if spans else None
        cursor += len(line)
    return result if spans else None
