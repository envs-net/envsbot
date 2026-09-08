"""Compatibility facade for shared diagnostic redaction helpers."""

from envs_xmpp_core.security.redaction import (
    REDACTED,
    SECRET_KEY_PARTS,
    is_secret_key,
    redact_named,
    redact_text,
    redact_url,
    redact_value,
)

__all__ = [
    "REDACTED",
    "SECRET_KEY_PARTS",
    "is_secret_key",
    "redact_named",
    "redact_text",
    "redact_url",
    "redact_value",
]
