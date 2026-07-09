"""Read-only command registry helpers used by docs/help/diagnostics."""

from __future__ import annotations

from typing import Any

from utils.command import COMMANDS, Role


def command_records() -> list[dict[str, Any]]:
    """Return stable command metadata records from the live registry."""
    records: list[dict[str, Any]] = []
    for tokens, cmd in sorted(COMMANDS.items(), key=lambda item: item[0]):
        registered_name = " ".join(tokens)
        primary_name = getattr(cmd, "name", registered_name)
        records.append(
            {
                "registered_name": registered_name,
                "primary_name": primary_name,
                "is_alias": registered_name != primary_name,
                "role": getattr(cmd, "role", Role.NONE),
                "handler": getattr(getattr(cmd, "handler", None), "__name__", "unknown"),
                "short": getattr(cmd, "short", ""),
                "usage": getattr(cmd, "usage", ""),
                "examples": list(getattr(cmd, "examples", []) or []),
                "category": getattr(cmd, "category", "") or "other",
                "context": getattr(cmd, "context", "any") or "any",
            }
        )
    return records


def primary_command_records() -> list[dict[str, Any]]:
    """Return only primary command records."""
    return [record for record in command_records() if not record["is_alias"]]
