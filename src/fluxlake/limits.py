"""Bounded JSON validation shared by the HTTP boundary and durable event contract."""

from __future__ import annotations

from typing import Any

MAX_DEPTH = 32
MAX_NODES = 20_000
MAX_STRING_BYTES = 4096
MAX_EVENT_BYTES = 65_536
MAX_ATTRIBUTES = 32
MAX_SCHEMA_ATTRIBUTES = 256


def validate_shape(value: Any, *, max_nodes: int = MAX_NODES) -> None:
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > max_nodes or depth > MAX_DEPTH:
            raise ValueError("JSON structure exceeds configured limits")
        if isinstance(item, str):
            # Surrogates are quarantined by UTF-8 validation; their escaped raw form
            # remains safe archive evidence. Valid strings still have a strict byte cap.
            if (
                len(item) > MAX_STRING_BYTES
                or len(item.encode("utf-8", errors="surrogatepass")) > MAX_STRING_BYTES
            ):
                raise ValueError("JSON string exceeds 4096 bytes")
        elif isinstance(item, dict):
            if len(item) > 128:
                raise ValueError("JSON object exceeds 128 fields")
            if count + len(pending) + 2 * len(item) > max_nodes:
                raise ValueError("JSON structure exceeds configured limits")
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif isinstance(item, (list, tuple)):
            if count + len(pending) + len(item) > max_nodes:
                raise ValueError("JSON structure exceeds configured limits")
            pending.extend((part, depth + 1) for part in item)


def check_json_depth(raw: bytes) -> None:
    """Reject deep nesting before recursive JSON parsing; ignore braces in strings."""
    depth = 0
    quoted = escaped = False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
        elif value in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("JSON nesting exceeds 32 levels")
        elif value in (93, 125):
            depth -= 1
