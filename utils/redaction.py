"""Central redaction helpers for logs, audit details and admin output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)
REDACTED = "<redacted>"
_MAX_STRING = 240


def is_secret_key(key: object) -> bool:
    """Return True when a mapping key likely contains a secret."""
    key_lc = str(key or "").lower()
    return any(part in key_lc for part in SECRET_KEY_PARTS)


def redact_url(value: str) -> str:
    """Return a URL with credentials removed, preserving the rest."""
    try:
        parsed = urlsplit(value)
    except Exception:
        return value
    if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
        return value
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def _truncate(text: str, *, max_length: int = _MAX_STRING) -> str:
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."


def redact_value(value: Any, *, key: object | None = None, max_string: int = _MAX_STRING) -> Any:
    """Redact nested data for logs/audit/admin output.

    The function is intentionally conservative for keys and URL credentials,
    but otherwise preserves value shape so existing formatting stays useful.
    """
    if key is not None and is_secret_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {k: redact_value(v, key=k, max_string=max_string) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_value(v, max_string=max_string) for v in value)
    if isinstance(value, list):
        return [redact_value(v, max_string=max_string) for v in value]
    if isinstance(value, set):
        return sorted(redact_value(v, max_string=max_string) for v in value)
    if isinstance(value, str):
        return _truncate(redact_url(value), max_length=max_string)
    return value


def redact_named(name: object, value: Any, *, max_string: int = _MAX_STRING) -> Any:
    """Redact a value using an explicit field name."""
    return redact_value(value, key=name, max_string=max_string)


def redact_text(text: object, *, max_length: int = _MAX_STRING) -> str:
    """Return a compact redacted text value for log/audit strings."""
    return _truncate(redact_url(str(text)), max_length=max_length)
