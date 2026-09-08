"""Helpers for sending notifications to XMPP users or MUC rooms."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from envs_xmpp_core.xmpp.messaging import (
    MUC_FEATURE,
    disco_muc_status,
)
from envs_xmpp_core.xmpp.messaging import (
    looks_like_bare_room_jid as _looks_like_bare_room_jid,
)
from envs_xmpp_core.xmpp.messaging import (
    maybe_await as _maybe_await,
)
from envs_xmpp_core.xmpp.messaging import (
    target_is_muc_room as _core_target_is_muc_room,
)
from envs_xmpp_core.xmpp.messaging import (
    target_text as _target_text,
)

_MUC_FEATURE = MUC_FEATURE

from utils.config import config

log = logging.getLogger(__name__)

_NOTIFICATION_ROOM_JOIN_TIMEOUT_SECONDS = 30.0


def is_configured_notification_target(bot: Any, target: str) -> bool:
    """Return whether *target* is one of the configured notification JIDs."""
    target_bare = _target_text(target).split("/", 1)[0].lower()
    if not target_bare:
        return False

    config_obj = getattr(bot, "config", {}) or {}
    for key in (
        "admin_report_jid",
        "version_check_notify_jid",
        "room_invite_notify_jid",
        "owner",
    ):
        configured = _target_text(config_obj.get(key)).split("/", 1)[0].lower()
        if configured and configured == target_bare:
            return True
    return False


def joined_room_nick(bot: Any, room_jid: str) -> str | None:
    """Return the bot nick for an already joined room, if known."""
    room_jid = _target_text(room_jid)
    if not room_jid:
        return None

    try:
        joined = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
        nick = joined.get(room_jid)
        if nick:
            return str(nick)
    except Exception:
        log.debug("Could not inspect presence joined rooms", exc_info=True)

    try:
        from bot.room_state import JOINED_ROOMS

        room = JOINED_ROOMS.get(room_jid) or {}
        nick = room.get("nick")
        if nick:
            return str(nick)
    except Exception:
        log.debug("Could not inspect rooms runtime state", exc_info=True)

    return None


def notification_message_type(bot: Any, target: str) -> str:
    """Return ``groupchat`` when *target* is a known joined room, else ``chat``."""
    return "groupchat" if joined_room_nick(bot, target) else "chat"


async def _disco_muc_status(bot: Any, target: str) -> bool | None:
    """Return True/False from shared disco parsing, or None when unavailable."""
    disco = None
    plugin = getattr(bot, "plugin", None)
    if isinstance(plugin, dict):
        disco = plugin.get("xep_0030")
    if disco is None:
        try:
            disco = bot["xep_0030"]
        except Exception:
            disco = None
    status = await disco_muc_status(disco, target)
    if status is None and disco is not None:
        log.debug("Could not discover whether notification target is a MUC: %s", target)
    return status


async def target_is_muc_room(bot: Any, target: str) -> bool:
    """Return True if *target* is known or discovered as a MUC room."""
    target = _target_text(target)
    if not _looks_like_bare_room_jid(target):
        return False

    joined = bool(joined_room_nick(bot, target))
    stored = False
    try:
        rooms = getattr(getattr(bot, "db", None), "rooms", None)
        get_room = getattr(rooms, "get", None)
        stored = bool(callable(get_room) and await _maybe_await(get_room(target)))
    except Exception:
        log.debug("Could not inspect stored rooms for notification target", exc_info=True)

    disco = None
    plugin = getattr(bot, "plugin", None)
    if isinstance(plugin, dict):
        disco = plugin.get("xep_0030")
    if disco is None:
        try:
            disco = bot["xep_0030"]
        except Exception:
            disco = None
    return await _core_target_is_muc_room(
        target,
        joined=joined,
        stored=stored,
        disco=disco,
    )


async def ensure_room_joined(bot: Any, room_jid: str, *, nick: str | None = None) -> bool:
    """Join *room_jid* if the bot is not already in the room."""
    room_jid = _target_text(room_jid)
    if joined_room_nick(bot, room_jid):
        return True

    plugin = getattr(bot, "plugin", None)
    muc = plugin.get("xep_0045") if isinstance(plugin, dict) else None
    if muc is None:
        try:
            muc = bot["xep_0045"]
        except Exception:
            muc = None
    if muc is None or not hasattr(muc, "join_muc"):
        log.warning("Cannot join notification room %s: XEP-0045 plugin unavailable", room_jid)
        return False

    nick = nick or str(
        config.get("nick")
        or getattr(getattr(bot, "boundjid", None), "resource", None)
        or "EnvsBot"
    )
    presence = getattr(bot, "presence", None)
    status = getattr(presence, "status", {}) or {}

    try:
        await asyncio.wait_for(
            _maybe_await(
                muc.join_muc(
                    room_jid,
                    nick,
                    pshow=status.get("show"),
                    pstatus=status.get("status"),
                )
            ),
            timeout=_NOTIFICATION_ROOM_JOIN_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        leave_muc = getattr(muc, "leave_muc", None)
        if callable(leave_muc):
            try:
                await _maybe_await(leave_muc(room_jid, nick))
            except Exception:
                log.debug(
                    "Could not clean up timed-out notification room join for %s",
                    room_jid,
                    exc_info=True,
                )
        log.warning(
            "Timed out joining notification room %s after %.1fs",
            room_jid,
            _NOTIFICATION_ROOM_JOIN_TIMEOUT_SECONDS,
        )
        return False
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to join notification room %s", room_jid)
        return False

    try:
        from bot.room_state import JOINED_ROOMS

        JOINED_ROOMS.setdefault(
            room_jid,
            {
                "nick": nick,
                "autojoin": False,
                "status": None,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {},
            },
        )
    except Exception:
        log.debug("Could not update joined room state for notification room", exc_info=True)

    try:
        if presence is not None:
            presence.joined_rooms[room_jid] = nick
        broadcast = getattr(presence, "broadcast", None)
        if callable(broadcast):
            broadcast()
    except Exception:
        log.debug("Could not update presence joined room state", exc_info=True)

    log.info("Joined notification room %s as %s", room_jid, nick)
    return True


async def ensure_notification_target_joined(bot: Any, target: str) -> bool:
    """Join *target* when it is a MUC room notification target."""
    target = _target_text(target)
    if not target:
        return False
    if await target_is_muc_room(bot, target):
        return await ensure_room_joined(bot, target)
    return False


async def prepare_notification_target(
    bot: Any,
    target: str,
    *,
    joined: bool | None = None,
) -> str | None:
    """Return the safe message type, joining MUC targets before use.

    ``None`` means a known MUC target is currently unavailable and callers
    must not fall back to a direct-chat stanza.
    """
    target = _target_text(target)
    if not target:
        return None
    if not await target_is_muc_room(bot, target):
        return "chat"
    if joined is None:
        joined = await ensure_room_joined(bot, target)
    return "groupchat" if joined else None
