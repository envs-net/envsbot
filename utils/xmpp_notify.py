"""Helpers for sending notifications to XMPP users or MUC rooms."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from utils.config import config

log = logging.getLogger(__name__)

_MUC_FEATURE = "http://jabber.org/protocol/muc"


def _target_text(target: str | None) -> str:
    """Return a stripped notification target string."""
    return str(target or "").strip()


def _looks_like_bare_room_jid(target: str) -> bool:
    """Return True for a bare JID shape that can represent a room."""
    return bool(target and "@" in target and "/" not in target)


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


async def _maybe_await(value: Any) -> Any:
    """Await value when needed and return the final result."""
    if inspect.isawaitable(value):
        return await value
    return value


def _iter_disco_features(info: Any):
    """Yield disco features from different Slixmpp response shapes."""
    for candidate in (
        info,
        _safe_get(info, "disco_info"),
        _safe_get(info, "features"),
    ):
        if candidate is None:
            continue
        try:
            features = candidate["features"]
        except Exception:
            features = getattr(candidate, "features", None)
        if features:
            for feature in features:
                yield str(feature)


def _iter_disco_identities(info: Any):
    """Yield disco identities from different Slixmpp response shapes."""
    for candidate in (info, _safe_get(info, "disco_info")):
        if candidate is None:
            continue
        try:
            identities = candidate["identities"]
        except Exception:
            identities = getattr(candidate, "identities", None)
        if identities:
            yield from identities


def _identity_is_muc(identity: Any) -> bool:
    """Return True when a disco identity describes a MUC service/room."""
    if isinstance(identity, (tuple, list)):
        text = "/".join(str(part).lower() for part in identity)
    elif isinstance(identity, dict):
        text = "/".join(str(value).lower() for value in identity.values())
    else:
        text = str(identity).lower()
    return "conference" in text or "muc" in text


def _safe_get(value: Any, key: str) -> Any:
    """Best-effort mapping/plugin getter."""
    try:
        return value[key]
    except Exception:
        return getattr(value, key, None)


async def target_is_muc_room(bot: Any, target: str) -> bool:
    """Return True if *target* looks like or discovers as a MUC room."""
    target = _target_text(target)
    if not _looks_like_bare_room_jid(target):
        return False
    if joined_room_nick(bot, target):
        return True

    try:
        rooms = getattr(getattr(bot, "db", None), "rooms", None)
        get_room = getattr(rooms, "get", None)
        if callable(get_room) and await _maybe_await(get_room(target)):
            return True
    except Exception:
        log.debug("Could not inspect stored rooms for notification target", exc_info=True)

    try:
        disco = None
        plugin = getattr(bot, "plugin", None)
        if isinstance(plugin, dict):
            disco = plugin.get("xep_0030")
        if disco is None:
            try:
                disco = bot["xep_0030"]
            except Exception:
                disco = None
        if disco is None or not hasattr(disco, "get_info"):
            return False

        info = await _maybe_await(disco.get_info(jid=target))
        if any(feature == _MUC_FEATURE for feature in _iter_disco_features(info)):
            return True
        return any(_identity_is_muc(identity) for identity in _iter_disco_identities(info))
    except Exception:
        log.debug("Could not discover whether notification target is a MUC: %s", target, exc_info=True)
        return False


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

    nick = nick or str(config.get("nick") or getattr(getattr(bot, "boundjid", None), "resource", None) or "EnvsBot")
    presence = getattr(bot, "presence", None)
    status = getattr(presence, "status", {}) or {}

    try:
        await _maybe_await(
            muc.join_muc(
                room_jid,
                nick,
                pshow=status.get("show"),
                pstatus=status.get("status"),
            )
        )
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
