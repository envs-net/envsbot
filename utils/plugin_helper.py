"""Shared helpers for room-scoped plugin on/off/status commands."""

import logging
from typing import Any, Awaitable, Callable, Optional

from utils.command import Role
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

StoreGetter = Callable[[Any], Awaitable[Any]]

_CONTROL_COMMANDS = {"on", "off", "status"}
_ADMIN_AFFILIATIONS = {"admin", "owner"}


def _room_and_nick_from_muc_pm(msg):
    """Return (room_jid, nick) for a MUC private message."""
    from_jid = msg["from"]
    return str(from_jid.bare), str(from_jid.resource or "")


def _get_muc_occupant(room_jid: str, nick: str) -> Optional[dict]:
    """Return cached occupant info from JOINED_ROOMS, if available."""
    room_data = JOINED_ROOMS.get(room_jid)

    if not room_data:
        return None

    return room_data.get("nicks", {}).get(nick)


async def muc_pm_sender_can_manage_room(
    bot,
    msg,
    is_room: bool,
) -> tuple[bool, str, Optional[str]]:
    """Check whether the sender may manage room-scoped plugin settings.

    Returns:
        (allowed, room_jid, reason)
    """
    if is_room:
        return False, "", "ℹ️ This command can only be used in a MUC DM."

    room_jid, nick = _room_and_nick_from_muc_pm(msg)

    if room_jid not in JOINED_ROOMS:
        return False, room_jid, "ℹ️ This command can only be used in a MUC DM."

    occupant = _get_muc_occupant(room_jid, nick)

    if not occupant:
        return False, room_jid, "⛔ Could not verify your room permissions."

    affiliation = str(occupant.get("affiliation") or "").lower()

    if affiliation in _ADMIN_AFFILIATIONS:
        return True, room_jid, None

    real_jid = occupant.get("jid")

    if real_jid:
        try:
            role = await bot.get_user_role(str(real_jid), room_jid)

            if role <= Role.MODERATOR:
                return True, room_jid, None

        except Exception:
            log.exception("[PLUGIN_HELPER] Failed to resolve user role")

    return False, room_jid, "⛔ Only room admins/owners can use on/off/status here."


def _format_status(label: str, enabled: bool) -> str:
    state = "enabled" if enabled else "disabled"
    icon = "✅" if enabled else "ℹ️"
    return f"{icon} {label} is **{state}** in this room."


def _format_enabled(label: str) -> str:
    return f"✅ {label} enabled in this room."


def _format_disabled(label: str) -> str:
    return f"✅ {label} disabled in this room."


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

    Returns True when args[0] is one of on/off/status and the command was fully
    handled. Returns False for all other subcommands so the plugin can continue
    normal handling.

    Supported storage formats:
    - storage="dict": {room_jid: True}
    - storage="list": {list_field: [room_jid, ...]}
    """
    if not args:
        return False

    subcmd = str(args[0]).lower()

    if subcmd not in _CONTROL_COMMANDS:
        return False

    allowed, room_jid, reason = await muc_pm_sender_can_manage_room(
        bot,
        msg,
        is_room,
    )

    if not allowed:
        bot.reply(msg, reason)
        return True

    store = await store_getter(bot)

    if storage == "dict":
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

    if storage == "list":
        state = await store.get_global(key, default={list_field: []})

        if not isinstance(state, dict):
            state = {list_field: []}

        rooms = state.get(list_field, [])

        if not isinstance(rooms, list):
            rooms = []

        enabled = room_jid in rooms

        if subcmd == "status":
            bot.reply(msg, _format_status(label, enabled))
            return True

        if subcmd == "on":
            if enabled:
                bot.reply(msg, _format_already_enabled(label))
                return True

            rooms.append(room_jid)
            state[list_field] = rooms
            await store.set_global(key, state)

            bot.reply(msg, _format_enabled(label))
            log.info("%s Room %s enabled", log_prefix, room_jid)
            return True

        if not enabled:
            bot.reply(msg, _format_already_disabled(label))
            return True

        rooms.remove(room_jid)
        state[list_field] = rooms
        await store.set_global(key, state)

        bot.reply(msg, _format_disabled(label))
        log.info("%s Room %s disabled", log_prefix, room_jid)
        return True

    raise ValueError(f"Unsupported room-toggle storage: {storage}")
