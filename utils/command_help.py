"""Compatibility facade for command metadata.

Command decorator metadata is now the single source of truth.  This module is
kept only for older imports/tests that still ask for ``metadata_for()`` or
``COMMAND_HELP``; both are generated from decorated command records instead of
being maintained manually.  ``COMMAND_HELP`` is exposed lazily via
``__getattr__`` so the registry remains the only concrete metadata store.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict


class CommandMetadata(TypedDict, total=False):
    short: str
    usage: str
    examples: list[str]
    context: str
    category: str


@lru_cache(maxsize=1)
def _metadata_map() -> dict[str, CommandMetadata]:
    """Return command metadata generated from decorated command records."""
    from utils.command_registry import decorated_command_records

    metadata: dict[str, CommandMetadata] = {}
    for _plugin, _plugin_meta, cmd in decorated_command_records():
        name = str(getattr(cmd, "name", "")).lower()
        if not name:
            continue
        metadata[name] = {
            "short": str(getattr(cmd, "short", "")),
            "usage": str(getattr(cmd, "usage", "")),
            "examples": list(getattr(cmd, "examples", []) or []),
            "context": str(getattr(cmd, "context", "any") or "any"),
            "category": str(getattr(cmd, "category", "")),
        }
    return metadata


def metadata_for(name: str) -> CommandMetadata | None:
    """Return structured metadata for a primary command name, or None."""
    return _metadata_map().get(name.lower())


class _CommandHelpView(dict[str, CommandMetadata]):
    """Read-through mapping view backed by decorator metadata."""

    def _data(self) -> dict[str, CommandMetadata]:
        return _metadata_map()

    def __getitem__(self, key: str) -> CommandMetadata:
        return self._data()[key]

    def get(self, key: str, default=None):  # type: ignore[override]
        return self._data().get(key, default)

    def items(self):  # type: ignore[override]
        return self._data().items()

    def keys(self):  # type: ignore[override]
        return self._data().keys()

    def values(self):  # type: ignore[override]
        return self._data().values()

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def __contains__(self, key: object) -> bool:
        return key in self._data()


def __getattr__(name: str):
    """Return lazily generated compatibility attributes."""
    if name == "COMMAND_HELP":
        return _CommandHelpView()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

