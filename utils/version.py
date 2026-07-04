"""Project version helpers."""

from __future__ import annotations

__version__ = "1.3.1"


def normalized_version(version: str | None = None) -> str:
    """Return a display-safe version string without a leading ``v``."""
    raw = __version__ if version is None else str(version)
    normalized = raw.strip().lstrip("v")
    return normalized or "unknown"


def display_version(version: str | None = None) -> str:
    """Return a display version with a leading ``v`` when known."""
    normalized = normalized_version(version)
    if normalized == "unknown":
        return normalized
    return f"v{normalized}"
