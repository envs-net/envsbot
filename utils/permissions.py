"""Central permission decisions for command and room management paths."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from utils.command import Role, check_permission
from utils.command_context import CommandContext


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Result of one permission check."""

    allowed: bool
    reason: str = ""


def can_use_admin_command(
    context: CommandContext,
    cmd_obj: Any,
    *,
    permission_checker: Callable[[Role, Any], bool] = check_permission,
) -> PermissionDecision:
    """Return whether the sender's role may execute ``cmd_obj`` at all."""
    if permission_checker(context.role, cmd_obj):
        return PermissionDecision(True)
    return PermissionDecision(False, "🔴 You are not allowed to use this command.")


def command_requires_muc_pm(cmd_obj: Any) -> bool:
    """Return True when a privileged command must not run in public MUC chat."""
    required_role = getattr(cmd_obj, "role", Role.NONE)
    return required_role <= Role.MODERATOR


def can_execute_in_message_context(
    context: CommandContext,
    cmd_obj: Any,
    *,
    room_invite_admin_rooms: set[str] | None = None,
) -> PermissionDecision:
    """Return whether a command may run from the current chat context.

    Privileged commands are allowed in private chat and MUC private messages,
    but blocked in public room messages.  ``rooms invite`` keeps its historical
    public-room exception for configured invite admin rooms.
    """
    if not context.is_room:
        return PermissionDecision(True)
    if not command_requires_muc_pm(cmd_obj):
        return PermissionDecision(True)
    if getattr(cmd_obj, "name", "") == "rooms invite" and context.room:
        if str(context.room).lower() in (room_invite_admin_rooms or set()):
            return PermissionDecision(True)
    return PermissionDecision(False, "🔴 Use this command in MUC Direct Message only.")


def can_execute_command(
    context: CommandContext,
    cmd_obj: Any,
    *,
    room_invite_admin_rooms: set[str] | None = None,
    permission_checker: Callable[[Role, Any], bool] = check_permission,
) -> PermissionDecision:
    """Return the final command execution decision for a resolved context."""
    role_decision = can_use_admin_command(context, cmd_obj, permission_checker=permission_checker)
    if not role_decision.allowed:
        return role_decision
    return can_execute_in_message_context(
        context,
        cmd_obj,
        room_invite_admin_rooms=room_invite_admin_rooms,
    )


def can_manage_room_role(role: Role) -> bool:
    """Return whether a bot role is globally trusted to manage room settings."""
    return role <= Role.MODERATOR
