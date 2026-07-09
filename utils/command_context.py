"""Command context objects shared by dispatch, execution and audit."""

from __future__ import annotations

from dataclasses import dataclass

from utils.command import Role


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Resolved command invocation context."""

    command_name: str
    sender_jid: str
    nick: str | None
    room: str | None
    is_room: bool
    is_muc_pm: bool
    role: Role
    args: tuple[str, ...]
    raw_body: str = ""
