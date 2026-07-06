"""Split module for core_plugins/users.py: formatting."""

import logging
import asyncio
import inspect
from functools import partial
from datetime import datetime, timezone
from slixmpp import JID
from utils.config import config
from utils.command import command, Role, role_from_int
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event


async def _send_user_info(bot, msg, user: dict):
    """
    Format and send user info.

    Includes:
    - JID
    - nickname
    - role
    - creation date
    - last seen
    """
    try:
        role = _role_from_user(user)

        created = user.get("created_at") or user.get("created")
        last_seen = user.get("last_seen")

        lines = [
            "👤 User Info:",
            f"- JID: {user['jid']}",
            f"- Nickname: {user.get('nickname') or '—'}",
            f"- Role: {role.name.lower()}",
        ]

        if created:
            lines.append(f"- Created: {created}")

        if last_seen:
            lines.append(f"- Last seen: {last_seen}")

        log.debug(f"[USERS] 📄 Sending user info: {user['jid']}")
        bot.reply(msg, "\n".join(lines))

    except Exception:
        log.exception("[USERS] 🔴  Failed to format user info")
        bot.reply(msg, "🟡️ Failed to format user info.")


async def _write_user_audit(bot, event: str, *, actor=None, target=None, details=None) -> None:
    """Write a users audit event without letting audit failures break commands."""
    try:
        await audit_event(
            bot,
            event,
            actor=actor,
            target=target,
            details={"plugin": "users", **(details or {})},
        )
    except Exception:
        log.debug("[USERS] Failed to write audit event", exc_info=True)


def _audit_reason(reason: str) -> str:
    """Return a compact reason string for audit details."""
    return str(reason).replace("⛔", "").replace("🟡️", "").strip()


def _yes_no(value: bool | None) -> str:
    """Return a compact yes/no/unknown label."""
    if value is None:
        return "unknown"
    return "yes" if value else "no"
