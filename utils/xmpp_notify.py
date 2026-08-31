"""Helpers for sending notifications to XMPP users or MUC rooms."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from utils.config import config

log = logging.getLogger(__name__)

_MUC_FEATURE = "http://jabber.org/protocol/muc"
_NOTIFICATION_ROOM_JOIN_TIMEOUT_SECONDS = 30.0


def _target_text(target: str | None) -> str:
    """Return a stripped notification target string."""
    return str(target or "").strip()


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


def _stanza_interfaces(value: Any) -> set[str] | None:
    """Return declared stanza interfaces, or ``None`` for non-stanza objects."""
    interfaces = getattr(value, "interfaces", None)
    if interfaces is None:
        return None
    try:
        return {str(item) for item in interfaces}
    except TypeError:
        return set()


def _safe_get_stanza_plugin(stanza: Any, plugin_name: str) -> Any:
    """Return a registered stanza plugin without probing unknown interfaces."""
    get_plugin = getattr(stanza, "get_plugin", None)
    if not callable(get_plugin):
        return None
    try:
        return get_plugin(plugin_name, check=True)
    except TypeError:
        try:
            return get_plugin(plugin_name)
        except Exception:
            return None
    except Exception:
        return None


def _disco_field(candidate: Any, key: str) -> Any:
    """Read a disco field without probing unsupported Slixmpp interfaces."""
    if isinstance(candidate, dict):
        return candidate.get(key)

    interfaces = _stanza_interfaces(candidate)
    if interfaces is not None:
        if key not in interfaces:
            return None
        try:
            return candidate[key]
        except Exception:
            return None

    return getattr(candidate, key, None)


def _disco_payloads(info: Any):
    """Yield disco#info payloads from mapping, stanza and test-double shapes."""
    if isinstance(info, dict):
        nested = info.get("disco_info")
        if nested is not None:
            yield nested
        if "features" in info or "identities" in info:
            yield info
        return

    interfaces = _stanza_interfaces(info)
    if interfaces is not None:
        # A local XEP-0030 lookup may already return the DiscoInfo stanza.
        if {"features", "identities"} & interfaces:
            yield info
            return

        # A remote lookup returns an IQ stanza. Use Slixmpp's plugin getter
        # instead of probing ``info["features"]``/``info["identities"]``;
        # unsupported IQ interfaces otherwise produce noisy root warnings.
        disco_info = _safe_get_stanza_plugin(info, "disco_info")
        if disco_info is not None:
            yield disco_info
        return

    # Lightweight test doubles and compatibility objects may expose the
    # DiscoInfo payload or its fields as normal Python attributes.
    nested = getattr(info, "disco_info", None)
    if nested is not None:
        yield nested
    if _disco_field(info, "features") or _disco_field(info, "identities"):
        yield info


def _iter_disco_features(info: Any):
    """Yield disco features from supported response payloads only."""
    for candidate in _disco_payloads(info):
        features = _disco_field(candidate, "features")
        if features:
            for feature in features:
                yield str(feature)


def _iter_disco_identities(info: Any):
    """Yield disco identities from supported response payloads only."""
    for candidate in _disco_payloads(info):
        identities = _disco_field(candidate, "identities")
        if identities:
            yield from identities


def _identity_is_muc(identity: Any) -> bool:
    """Return True when a disco identity has the XEP-0030 conference category."""
    if isinstance(identity, dict):
        category = identity.get("category")
    elif isinstance(identity, (tuple, list)):
        category = identity[0] if identity else None
    else:
        category = getattr(identity, "category", None)
    return str(category or "").strip().lower() == "conference"


def _legacy_muc_domain_hint(target: str) -> bool:
    """Recognize conventional MUC service domains when disco is unavailable."""
    if not _looks_like_bare_room_jid(target):
        return False
    domain = target.split("@", 1)[1].strip().lower()
    return domain.startswith("conference.") or domain.startswith("muc.")


async def _disco_muc_status(bot: Any, target: str) -> bool | None:
    """Return True/False from disco, or None when discovery is unavailable."""
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
        return None

    try:
        info = await _maybe_await(disco.get_info(jid=target))
    except Exception:
        log.debug(
            "Could not discover whether notification target is a MUC: %s",
            target,
            exc_info=True,
        )
        return None

    if any(feature == _MUC_FEATURE for feature in _iter_disco_features(info)):
        return True
    return any(_identity_is_muc(identity) for identity in _iter_disco_identities(info))


async def target_is_muc_room(bot: Any, target: str) -> bool:
    """Return True if *target* is known or discovered as a MUC room."""
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

    disco_status = await _disco_muc_status(bot, target)
    if disco_status is not None:
        return disco_status
    return _legacy_muc_domain_hint(target)


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
