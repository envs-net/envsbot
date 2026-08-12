"""Small helpers for structured command help metadata."""

from __future__ import annotations

from collections.abc import Iterable

from utils.command import Role


def help_example(command: str, description: str) -> dict[str, str]:
    """Return one described command example."""
    return {"command": command, "description": description}


def help_subcommand(
    name: str,
    usage: str,
    short: str,
    *,
    aliases: Iterable[str] = (),
    examples: Iterable[dict[str, str] | tuple[str, str]] = (),
    role: Role | None = None,
    context: str = "",
    section: str = "",
) -> dict[str, object]:
    """Return one normalized-friendly structured subcommand mapping."""
    return {
        "name": name,
        "usage": usage,
        "short": short,
        "aliases": list(aliases),
        "examples": list(examples),
        "role": role,
        "context": context,
        "section": section,
    }


def room_toggle_subcommands(
    command_name: str,
    feature_label: str,
    *,
    status_name: str = "status",
    context: str = "room or MUC PM",
    section: str = "",
) -> list[dict[str, object]]:
    """Return standard on/off/status metadata for a room-scoped plugin."""
    return [
        help_subcommand(
            "on",
            f"{{prefix}}{command_name} on",
            f"Enable {feature_label} in the current room.",
            examples=[
                help_example(
                    f"{{prefix}}{command_name} on",
                    f"Enable {feature_label} for the current room or MUC PM.",
                )
            ],
            context=context,
            section=section,
        ),
        help_subcommand(
            "off",
            f"{{prefix}}{command_name} off",
            f"Disable {feature_label} in the current room.",
            examples=[
                help_example(
                    f"{{prefix}}{command_name} off",
                    f"Disable {feature_label} for the current room or MUC PM.",
                )
            ],
            context=context,
            section=section,
        ),
        help_subcommand(
            status_name,
            f"{{prefix}}{command_name} {status_name}",
            f"Show whether {feature_label} is enabled in the current room.",
            examples=[
                help_example(
                    f"{{prefix}}{command_name} {status_name}",
                    f"Inspect the current room setting for {feature_label}.",
                )
            ],
            context=context,
            section=section,
        ),
    ]
