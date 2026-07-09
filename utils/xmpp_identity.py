"""Shared XMPP identity and room-permission helpers."""

from __future__ import annotations

import datetime
import logging
from typing import Any, Awaitable, Callable, Optional

import pytz
from slixmpp import JID

from core_plugins.rooms import JOINED_ROOMS
from utils.command import Role

log = logging.getLogger(__name__)

StoreGetter = Callable[[Any], Awaitable[Any]]


def _is_muc_pm(msg, joined_rooms=None):
    """Return True if message is a MUC private message."""
    if not joined_rooms:
        joined_rooms = JOINED_ROOMS
    muc_from = getattr(msg["from"], "bare", None)
    return (
        msg["type"] in ("chat", "normal")
        and muc_from in joined_rooms
        and getattr(msg["from"], "resource", None) is not None
    )


def _is_public_muc(msg, is_room: bool) -> bool:
    """Return True for public groupchat messages."""
    return is_room and msg.get("type") == "groupchat"


def _normalize_bare_jid(value) -> str | None:
    """Normalize a JID-like value to a bare JID string."""
    if not value:
        return None
    try:
        return str(JID(str(value)).bare)
    except Exception:
        value = str(value)
        return value.split("/", 1)[0]


async def get_jids_from_nick_index(bot, nick):
    """Look up the real JID of a nick from the UserManager's _nick_index."""
    idx = getattr(bot.db.users, "_nick_index", {})
    value = idx.get(nick)
    if isinstance(value, set):
        return next(iter(value), None)
    if isinstance(value, list):
        return value
    return value or None


async def get_real_jid(bot, msg):
    """Resolve the real sender JID in groupchat, MUC PM or direct chat."""
    jid = None
    is_muc_private = False
    is_muc_groupchat = False
    result = None

    muc = bot.plugin.get("xep_0045", None)
    if muc:
        room = getattr(msg["from"], "bare", None)
        nick = getattr(msg["from"], "resource", None)
        try:
            result = JOINED_ROOMS.get(room, {}).get("nicks", {}).get(nick, {}).get("jid", None)
        except Exception:
            result = None
        if result is None and nick:
            result = await get_jids_from_nick_index(bot, nick)

    if result is not None and _is_muc_pm(msg):
        jid = result
        is_muc_private = True
    elif result is not None and msg["type"] == "groupchat":
        jid = result
        is_muc_groupchat = True
    elif msg["to"].bare == bot.boundjid.bare:
        jid = msg["from"].bare
    else:
        jid = None
    return _normalize_bare_jid(jid), is_muc_private, is_muc_groupchat


async def _ensure_user_exists(bot, user_jid: str, nickname: str | None = None):
    """Ensure a user row exists."""
    user_jid = str(user_jid)
    existing = await bot.db.users.get(user_jid)
    if existing is not None:
        return
    try:
        await bot.db.users.create(user_jid, nickname)
        log.debug("[CORE] Created user row for %s", user_jid)
    except Exception:
        existing = await bot.db.users.get(user_jid)
        if existing is None:
            raise


async def _get_user_timezone(bot, timezone_jid: str | None) -> str:
    """Return the user's vCard TIMEZONE or UTC as fallback."""
    if not timezone_jid:
        return str(pytz.timezone("UTC"))
    try:
        store = bot.db.users.plugin("vcard")
        timezone_name = await store.get(str(timezone_jid), "TIMEZONE")
        if timezone_name and timezone_name in pytz.all_timezones:
            return str(pytz.timezone(timezone_name))
        if timezone_name:
            log.warning("[CORE] Invalid vCard TIMEZONE for %s: %s; falling back to UTC", timezone_jid, timezone_name)
    except Exception as exc:
        log.warning("[CORE] Could not read vCard TIMEZONE for %s: %s; falling back to UTC", timezone_jid, exc)
    return str(pytz.timezone("UTC"))


async def get_user_tzinfo(bot, timezone_jid: str) -> datetime.tzinfo:
    """Return the user's timezone as a tzinfo object, or UTC."""
    tzname = await _get_user_timezone(bot, timezone_jid)
    try:
        return pytz.timezone(tzname)
    except Exception:
        log.warning("[CORE] Invalid timezone for %s: %s; falling back to UTC", timezone_jid, tzname)
        return pytz.timezone("UTC")


async def get_plugin_store(bot, plugin):
    """Return the user runtime plugin store."""
    return bot.db.users.plugin(plugin)


async def _get_enabled_rooms(bot, key, plugin) -> dict:
    """Return a dict of {room_jid: True} for enabled rooms."""
    store = await get_plugin_store(bot, plugin)
    data = await store.get_global(key, default={})
    return data if isinstance(data, dict) else {}


async def _is_enabled_for_room(bot, key, plugin, room_jid: str) -> bool:
    """Return whether a plugin feature is enabled in a room."""
    enabled = await _get_enabled_rooms(bot, key, plugin)
    return bool(enabled.get(room_jid))


async def is_plugin_enabled_for_room(bot, store_getter: StoreGetter, key: str, room_jid: str) -> bool:
    """Return True if {key} enabled for room_jid in the plugin's global store."""
    store = await store_getter(bot)
    state = await store.get_global(key, default={})
    return isinstance(state, dict) and bool(state.get(room_jid))


async def get_real_jid_from_occupant(bot, msg, nick=None):
    """Look up the real JID of a nick from cached room occupants."""
    try:
        nicks = JOINED_ROOMS.get(msg["from"].bare, {}).get("nicks", {})
        if nick is None:
            jid = nicks.get(msg["from"].resource, {}).get("jid", None)
        else:
            jid = nicks.get(nick, {}).get("jid", None)
    except Exception as exc:
        log.warning("[CORE] 🟡 Error resolving real JID from occupant for %s in %s: %s", msg["from"].resource, msg["from"].bare, exc)
        jid = None
    return jid


async def get_nicks_from_jid(bot, jid):
    """Look up all nicknames of a JID from the UserManager's _nick_index."""
    idx = getattr(bot.db.users, "_nick_index", {})
    nicks = []
    for nick, value in idx.items():
        if isinstance(value, set) and jid in value:
            nicks.append(nick)
        elif isinstance(value, list) and jid in value:
            nicks.append(nick)
        elif value == jid:
            nicks.append(nick)
    return nicks


async def _check_user_exists(bot, sender_jid, msg):
    """Check if the user exists in the database and reply on failure."""
    jid = str(sender_jid)
    user = await bot.db.users.get(jid)
    if not user:
        log.warning("[CORE] 🔴  Unregistered user tried to access: %s", jid)
        bot.reply(msg, "🔴  You are not a registered user.")
        return False
    return True


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


async def is_room_moderator_or_admin(bot, room_jid: str, nick: str) -> bool:
    """Return True if a MUC occupant can moderate a room."""
    occupant = _get_muc_occupant(room_jid, nick)
    if not occupant:
        return False
    affiliation = str(occupant.get("affiliation") or "").lower()
    if affiliation in _ADMIN_AFFILIATIONS:
        return True
    real_jid = occupant.get("jid")
    if real_jid:
        try:
            role = await bot.get_user_role(str(real_jid), room_jid)
            return role <= Role.MODERATOR
        except Exception:
            log.exception("[CORE] Failed to resolve user room role")
    return False


async def muc_pm_sender_can_manage_room(bot, msg, is_room: bool) -> tuple[bool, str, Optional[str]]:
    """Check whether the sender may manage room-scoped plugin settings."""
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
            log.exception("[CORE] Failed to resolve user role")
    return False, room_jid, "⛔ Only room admins/owners can use on/off/status here."
