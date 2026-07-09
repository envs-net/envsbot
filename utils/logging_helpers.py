"""Small helpers for consistent key=value log messages."""

from __future__ import annotations

from typing import Any

from utils.redaction import redact_value


def _format_value(value: Any) -> str:
    text = str(redact_value(value))
    if not text:
        return "-"
    if any(ch.isspace() for ch in text):
        return repr(text)
    return text


def kv(**fields: Any) -> str:
    """Return fields formatted as stable key=value pairs."""
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)
