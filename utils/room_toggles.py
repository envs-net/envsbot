"""Shared room-scoped plugin toggle command helper."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from utils.xmpp_identity import muc_pm_sender_can_manage_room

log = logging.getLogger(__name__)

StoreGetter = Callable[[Any], Awaitable[Any]]
_CONTROL_COMMANDS = {"on", "off", "status"}


def _format_status(label: str, enabled: bool) -> str:
    state = "enabled" if enabled else "disabled"
    icon = "✅" if enabled else "ℹ️"
    return f"{icon} {label} is **{state}** in this room."


def _format_enabled(label: str) -> str:
    return f"✅ {label} enabled in this room."


def _format_disabled(label: str) -> str:
    return f"ℹ️ {label} disabled in this room."


def _format_already_enabled(label: str) -> str:
    return f"ℹ️ {label} already enabled."


def _format_already_disabled(label: str) -> str:
    return f"ℹ️ {label} already disabled."


async def handle_room_toggle_command(
    bot,
    msg,
    is_room: bool,
    args: list[str],
    *,
    store_getter: StoreGetter,
    key: str,
    label: str,
    storage: str = "dict",
    list_field: str = "rooms",
    log_prefix: str = "[PLUGIN]",
) -> bool:
    """Shared handler for `{plugin} on|off|status` commands.

    ``list_field`` is reserved for backward compatibility with the old
    signature. This dict-backed implementation intentionally ignores it.
    """
    if not args:
        return False
    subcmd = str(args[0]).lower()
    if subcmd not in _CONTROL_COMMANDS:
        return False

    allowed, room_jid, reason = await muc_pm_sender_can_manage_room(bot, msg, is_room)
    if not allowed:
        bot.reply(msg, reason)
        return True

    store = await store_getter(bot)
    if storage != "dict":
        raise ValueError(f"Unsupported room-toggle storage: {storage}")

    state = await store.get_global(key, default={})
    if not isinstance(state, dict):
        state = {}
    enabled = bool(state.get(room_jid))

    if subcmd == "status":
        bot.reply(msg, _format_status(label, enabled))
        return True
    if subcmd == "on":
        if enabled:
            bot.reply(msg, _format_already_enabled(label))
            return True
        state[room_jid] = True
        await store.set_global(key, state)
        bot.reply(msg, _format_enabled(label))
        log.info("%s Room %s enabled", log_prefix, room_jid)
        return True

    if not enabled:
        bot.reply(msg, _format_already_disabled(label))
        return True
    state.pop(room_jid, None)
    await store.set_global(key, state)
    bot.reply(msg, _format_disabled(label))
    log.info("%s Room %s disabled", log_prefix, room_jid)
    return True
