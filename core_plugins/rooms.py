"""
Room management and persistence.

This plugin provides administrative commands for managing XMPP
multi-user chat rooms stored in the bot database. Administrators
can add rooms, update their configuration, remove them, view the
current list of rooms, and control whether the bot joins or leaves
rooms at runtime.

Newly created rooms will be created with the plugin defaults (on/off)
defined in the "rooms" plugin.

You can set the rooms plugins back to the defaults with the following command:
    {prefix}room set_plugin_defaults

Rooms can optionally be configured with an *autojoin* flag so the
bot automatically joins them when it starts.
"""

import asyncio
import inspect
import logging
import time
from xml.etree import ElementTree as ET

from functools import partial

from slixmpp import JID

from utils.command import command, Role
from utils.config import config
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event
from utils.xmpp_notify import (
    ensure_notification_target_joined,
    notification_message_type,
)
from utils.room_features import (
    format_room_feature_line,
    get_room_feature,
    list_room_features,
    set_room_feature,
)

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "rooms",
    "version": "0.3.0",
    "description": "Database-backed room management",
    "category": "core",
}

# joined rooms module global
JOINED_ROOMS = {}

# Rooms we intentionally left/deleted. Delayed MUC presence from those
# rooms must not recreate JOINED_ROOMS entries after the command finished.
_LEAVING_ROOMS: set[str] = set()

_DIRECT_INVITE_NS = "jabber:x:conference"
_MUC_USER_NS = "http://jabber.org/protocol/muc#user"

# ------------------------------------------------
# Default Plugin Setup for rooms
#
# IMPORTANT NOTE: This only works for "type": "dict"
# ------------------------------------------------
INTERNAL_PLUGIN_DEFAULTS = {
    "help": False,
    "birthday_notify": False,
    "ducks": False,
    "karma": False,
    "pin": True,
    "poll": False,
    "information": True,
    "dice": True,
    "tell": True,
    "tools": True,
    "reminder": True,
    "sed": True,
    "presence": True,
    "urlcheck": True,
    "vcard": True,
    "weather": True,
    "xkcd": False,
    "xmpp": True,
}
# Backwards-compatible name for tests/imports. Runtime code should use
# get_room_plugin_defaults() so config.py overrides are applied.
PLUGIN_DEFAULTS = INTERNAL_PLUGIN_DEFAULTS
PLUGIN_STORE_CONFIG = {
    "help": {"type": "dict", "key": "HELP"},
    "birthday_notify": {"type": "dict", "key": "birthday_notify"},
    "ducks": {"type": "dict", "key": "DUCKS"},
    "karma": {"type": "dict", "key": "KARMA"},
    "pin": {"type": "dict", "key": "PIN"},
    "poll": {"type": "dict", "key": "POLL"},
    "information": {"type": "dict", "key": "INFORMATION"},
    "dice": {"type": "dict", "key": "DICE"},
    "tell": {"type": "dict", "key": "TELL"},
    "tools": {"type": "dict", "key": "TOOLS"},
    "reminder": {"type": "dict", "key": "REMINDER"},
    "sed": {"type": "dict", "key": "SED"},
    "presence": {"type": "dict", "key": "PRESENCE"},
    "urlcheck": {"type": "dict", "key": "URLCHECK"},
    "vcard": {"type": "dict", "key": "VCARD"},
    "weather": {"type": "dict", "key": "WEATHER"},
    "xkcd": {"type": "dict", "key": "XKCD"},
    "xmpp": {"type": "dict", "key": "XMPP"},
}
ROOM_TOGGLE_STORES = tuple(
    (plugin_name, spec["key"])
    for plugin_name, spec in PLUGIN_STORE_CONFIG.items()
    if spec.get("type") == "dict"
)
_WARNED_ROOM_PLUGIN_DEFAULT_KEYS: set[str] = set()


def _normalize_room_plugin_default_name(name: object) -> str:
    """Return the canonical room plugin default name used internally."""
    value = str(name).strip().lower()
    aliases = {
        "info": "information",
        "infos": "information",
        "roominfo": "information",
    }
    return aliases.get(value, value)


def _coerce_room_plugin_default(value: object, fallback: bool) -> bool:
    """Return a boolean room default with a safe fallback for bad values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False

    log.warning(
        "[ROOMS] Ignoring invalid ROOM_PLUGIN_DEFAULTS value %r; "
        "using fallback %s",
        value,
        fallback,
    )
    return fallback


def get_room_plugin_defaults() -> dict[str, bool]:
    """Return effective room plugin defaults with config.py overrides merged in.

    INTERNAL_PLUGIN_DEFAULTS keeps the historic behavior. config.py may override
    selected values through ROOM_PLUGIN_DEFAULTS. Missing keys keep their
    internal defaults and unknown keys are ignored with a warning.
    """
    defaults = INTERNAL_PLUGIN_DEFAULTS.copy()
    configured = config.get("room_plugin_defaults", {})
    if configured in (None, ""):
        return defaults
    if not isinstance(configured, dict):
        log.warning(
            "[ROOMS] Ignoring ROOM_PLUGIN_DEFAULTS because it is %s, not dict",
            type(configured).__name__,
        )
        return defaults

    for raw_name, raw_value in configured.items():
        plugin = _normalize_room_plugin_default_name(raw_name)
        if plugin not in defaults:
            warning_key = str(raw_name)
            if warning_key not in _WARNED_ROOM_PLUGIN_DEFAULT_KEYS:
                _WARNED_ROOM_PLUGIN_DEFAULT_KEYS.add(warning_key)
                log.warning(
                    "[ROOMS] Ignoring unknown ROOM_PLUGIN_DEFAULTS entry: %s",
                    raw_name,
                )
            continue
        defaults[plugin] = _coerce_room_plugin_default(raw_value, defaults[plugin])

    return defaults
# ------------------------------------------------



# -------------------------------------------------
# Room Invite Helpers
# -------------------------------------------------


def room_invites_enabled() -> bool:
    """Return whether incoming MUC invite handling is enabled."""
    return bool(config.get("room_invites_enabled", True))


def room_invite_notify_target() -> str | None:
    """Return the invite notification target.

    Priority:
    1. ROOM_INVITE_NOTIFY_JID
    2. VERSION_CHECK_NOTIFY_JID
    3. OWNER
    """
    for key in ("room_invite_notify_jid", "version_check_notify_jid", "owner"):
        target = str(config.get(key) or "").strip()
        if target:
            return target
    return None


def room_invite_admin_rooms() -> set[str]:
    """Return configured rooms that may run invite commands publicly."""
    rooms = set()
    for key in ("room_invite_notify_jid", "version_check_notify_jid"):
        target = str(config.get(key) or "").strip().lower()
        if target and "@" in target and "/" not in target:
            rooms.add(target)
    return rooms


def _room_invite_max_age_days() -> int:
    """Return configured pending invite max age in days."""
    try:
        return max(0, int(config.get("room_invite_max_age_days", 30) or 0))
    except (TypeError, ValueError):
        return 30


def _room_invite_is_expired(invite: dict, now: int | None = None) -> bool:
    """Return True when a pending invite exceeded the configured max age."""
    max_age_days = _room_invite_max_age_days()
    if max_age_days <= 0:
        return False
    try:
        created_at = int(invite.get("created_at", 0) or 0)
    except (TypeError, ValueError):
        created_at = 0
    if created_at <= 0:
        return False
    now = int(time.time()) if now is None else int(now)
    return created_at < now - (max_age_days * 86400)


def _jid_bare(value) -> str:
    """Return a best-effort lower-case bare JID string."""
    if value is None:
        return ""
    bare = getattr(value, "bare", None)
    if bare:
        return str(bare).lower()
    try:
        return str(JID(str(value)).bare).lower()
    except Exception:
        return str(value).split("/", 1)[0].lower()


def _looks_like_room_jid(value: object) -> bool:
    """Return True if a value looks like a bare MUC JID argument."""
    raw = str(value or "").strip()
    room_jid = _jid_bare(raw)
    if not raw or "/" in raw or "@" not in room_jid:
        return False
    node, domain = room_jid.split("@", 1)
    return bool(node and domain)


def _message_context_room(msg, is_room: bool) -> str:
    """Return the implicit room for public room messages or MUC PMs."""
    try:
        from_jid = msg["from"]
        room_jid = _jid_bare(from_jid)
        nick = getattr(from_jid, "resource", None)
    except Exception:
        return ""

    if is_room:
        return room_jid
    if nick and room_jid in JOINED_ROOMS:
        return room_jid
    return ""


async def _maybe_get_user_role(bot, sender_jid: str, room_jid: str) -> Role:
    """Return the sender role for a room without assuming async mocks."""
    get_user_role = getattr(bot, "get_user_role", None)
    if not callable(get_user_role):
        return Role.NONE
    try:
        result = get_user_role(sender_jid, room_jid)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, Role) else Role.NONE
    except Exception:
        log.debug("[ROOMS] Could not resolve role for %s in %s", sender_jid, room_jid, exc_info=True)
        return Role.NONE


def _sender_has_room_affiliation(sender_jid: str, room_jid: str) -> bool:
    """Return True if sender is visible as room admin/owner in JOINED_ROOMS."""
    sender_bare = _jid_bare(sender_jid)
    if not sender_bare:
        return False
    room_data = JOINED_ROOMS.get(room_jid) or {}
    nicks = room_data.get("nicks") or {}
    if not isinstance(nicks, dict):
        return False
    for occupant in tuple(nicks.values()):
        if not isinstance(occupant, dict):
            continue
        occupant_jid = _jid_bare(occupant.get("jid"))
        affiliation = str(occupant.get("affiliation") or "").lower()
        if occupant_jid == sender_bare and affiliation in {"admin", "owner"}:
            return True
    return False


async def _sender_can_manage_room_settings(bot, sender_jid: str, room_jid: str) -> bool:
    """Return True when sender may manage room-scoped bot settings."""
    sender_bare = _jid_bare(sender_jid)
    if not sender_bare:
        return False
    role = await _maybe_get_user_role(bot, sender_bare, room_jid)
    if role <= Role.MODERATOR:
        return True
    return _sender_has_room_affiliation(sender_bare, room_jid)


async def _room_is_known(bot, room_jid: str) -> bool:
    """Return True if the room is joined or stored in the room database."""
    if room_jid in JOINED_ROOMS:
        return True
    rooms_db = getattr(getattr(bot, "db", None), "rooms", None)
    get_room = getattr(rooms_db, "get", None)
    if not callable(get_room):
        return False
    try:
        result = get_room(room_jid)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)
    except Exception:
        log.debug("[ROOMS] Could not look up room %s", room_jid, exc_info=True)
        return False


async def _resolve_room_settings_target(bot, msg, is_room: bool, args: list[str], sender_jid: str, usage: str):
    """Resolve and authorize the target room for room setting commands."""
    remaining = list(args)
    explicit = False
    if remaining and _looks_like_room_jid(remaining[0]):
        room_jid = _jid_bare(remaining.pop(0))
        explicit = True
    else:
        room_jid = _message_context_room(msg, is_room)

    if not room_jid:
        bot.reply_usage(msg, usage)
        bot.reply_info(
            msg,
            "Use a MUC PM, run the command in the room, or pass <room_jid> when using a normal DM/admin room.",
        )
        return None

    if not explicit and not is_room and room_jid not in JOINED_ROOMS:
        bot.reply_error(msg, "This command can only infer a room from MUC PMs or room messages.")
        return None

    if not await _room_is_known(bot, room_jid):
        bot.reply_error(msg, f"Room '{room_jid}' is not currently joined or stored.")
        return None

    if not await _sender_can_manage_room_settings(bot, sender_jid, room_jid):
        bot.reply_error(
            msg,
            f"Only room admins/owners or bot moderators can manage room settings for '{room_jid}'.",
        )
        return None

    return room_jid, remaining


def _invite_inviter_from_attr(value: str | None, room_jid: str = "") -> str:
    """Return the best available inviter identity."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    bare = _jid_bare(raw)
    if room_jid and bare == room_jid and "/" in raw:
        return raw.lower()
    return bare or raw.lower()


def _safe_get_plugin(stanza, plugin_name: str):
    """Return a stanza plugin without noisy unknown-interface warnings."""
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


def _safe_plugin_value(plugin, key: str) -> str:
    """Return a string value from a stanza plugin."""
    if plugin is None:
        return ""
    try:
        value = plugin.get(key)
    except Exception:
        try:
            value = plugin[key]
        except Exception:
            return ""
    return "" if value is None else str(value).strip()


def _room_invite_reason_from_invite(invite_el: ET.Element) -> str:
    """Extract an optional mediated invite reason."""
    reason_el = invite_el.find(f"{{{_MUC_USER_NS}}}reason")
    if reason_el is not None and reason_el.text:
        return reason_el.text.strip()
    return ""


def _room_invite_from_muc_plugin(msg) -> dict[str, str] | None:
    """Extract mediated MUC invites from Slixmpp stanza plugins."""
    muc = _safe_get_plugin(msg, "muc")
    if muc is None:
        return None
    invite = _safe_get_plugin(muc, "invite")
    if invite is None:
        return None
    room_jid = _jid_bare(msg["from"])
    if not room_jid:
        return None
    inviter = _invite_inviter_from_attr(_safe_plugin_value(invite, "from"), room_jid)
    return {
        "room_jid": room_jid,
        "inviter": inviter or "unknown",
        "reason": _safe_plugin_value(invite, "reason"),
    }


def _room_invite_from_direct_plugin(msg) -> dict[str, str] | None:
    """Extract XEP-0249 direct invites from Slixmpp stanza plugins."""
    direct = _safe_get_plugin(msg, "groupchat_invite")
    if direct is None:
        direct = _safe_get_plugin(msg, "conference")
    if direct is None:
        return None
    room_jid = (
        _safe_plugin_value(direct, "jid")
        or _safe_plugin_value(direct, "room")
        or _safe_plugin_value(direct, "to")
    ).lower()
    if not room_jid:
        return None
    return {
        "room_jid": room_jid,
        "inviter": _jid_bare(msg["from"]) or "unknown",
        "reason": _safe_plugin_value(direct, "reason"),
    }


def extract_room_invite(msg) -> dict[str, str] | None:
    """Extract room, inviter and reason from direct or mediated MUC invites."""
    xml = getattr(msg, "xml", None)
    if xml is None:
        return _room_invite_from_muc_plugin(msg) or _room_invite_from_direct_plugin(msg)

    for direct in xml.findall(f".//{{{_DIRECT_INVITE_NS}}}x"):
        room_jid = (direct.attrib.get("jid") or "").strip().lower()
        if not room_jid:
            continue
        return {
            "room_jid": room_jid,
            "inviter": _jid_bare(msg["from"]) or "unknown",
            "reason": (direct.attrib.get("reason") or "").strip(),
        }

    for invite in xml.findall(f".//{{{_MUC_USER_NS}}}invite"):
        room_jid = _jid_bare(msg["from"])
        if not room_jid:
            continue
        inviter = _invite_inviter_from_attr(invite.attrib.get("from"), room_jid)
        return {
            "room_jid": room_jid,
            "inviter": inviter or "unknown",
            "reason": _room_invite_reason_from_invite(invite),
        }

    return _room_invite_from_muc_plugin(msg) or _room_invite_from_direct_plugin(msg)


async def setup_room_invites_db(bot) -> None:
    """Create the persistent pending room invite table when needed."""
    conn = getattr(getattr(bot, "db", None), "conn", None)
    if conn is None:
        return
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS room_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_jid TEXT NOT NULL,
            inviter TEXT NOT NULL,
            reason TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            UNIQUE(room_jid, inviter)
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at "
        "ON room_invites(created_at)"
    )
    await conn.commit()


async def load_pending_room_invites(bot) -> dict[int, dict]:
    """Load pending room invites from SQLite into bot runtime state."""
    await setup_room_invites_db(bot)
    conn = getattr(getattr(bot, "db", None), "conn", None)
    if conn is None:
        pending = getattr(bot, "pending_room_invites", {})
        if not isinstance(pending, dict):
            pending = {}
        bot.pending_room_invites = dict(pending)
        bot.pending_room_invite_index = {
            (str(invite["room_jid"]), str(invite["inviter"])): invite_id
            for invite_id, invite in bot.pending_room_invites.items()
        }
        return bot.pending_room_invites

    bot.pending_room_invites = {}
    bot.pending_room_invite_index = {}

    async with conn.execute(
        """
        SELECT id, room_jid, inviter, reason, created_at
        FROM room_invites
        ORDER BY id ASC
        """
    ) as cursor:
        rows = await cursor.fetchall()

    expired_ids = []
    now = int(time.time())
    for invite_id, room_jid, inviter, reason, created_at in rows:
        invite = {
            "id": int(invite_id),
            "room_jid": str(room_jid).lower(),
            "inviter": str(inviter).lower(),
            "reason": reason or "",
            "created_at": int(created_at or 0),
        }
        if _room_invite_is_expired(invite, now=now):
            expired_ids.append(int(invite_id))
            continue
        bot.pending_room_invites[int(invite_id)] = invite
        bot.pending_room_invite_index[(invite["room_jid"], invite["inviter"])] = int(invite_id)

    if expired_ids:
        placeholders = ",".join("?" for _ in expired_ids)
        await conn.execute(f"DELETE FROM room_invites WHERE id IN ({placeholders})", expired_ids)
        await conn.commit()
        log.info("Expired %d pending room invite(s)", len(expired_ids))

    return bot.pending_room_invites


async def _store_pending_room_invite(bot, room_jid: str, inviter: str, reason: str = "") -> dict | None:
    """Persist a pending room invite and add it to runtime state."""
    await setup_room_invites_db(bot)
    pending = getattr(bot, "pending_room_invites", {})
    index = getattr(bot, "pending_room_invite_index", {})
    if not isinstance(pending, dict):
        pending = {}
    if not isinstance(index, dict):
        index = {}
    bot.pending_room_invites = pending
    bot.pending_room_invite_index = index

    key = (room_jid, inviter)
    existing_id = index.get(key)
    if existing_id is not None and existing_id in pending:
        invite = pending[existing_id]
        if not _room_invite_is_expired(invite):
            return invite
        await _delete_pending_room_invite(bot, existing_id)

    conn = getattr(getattr(bot, "db", None), "conn", None)
    created_at = int(time.time())
    if conn is None:
        invite_id = max(pending.keys(), default=0) + 1
        invite = {
            "id": invite_id,
            "room_jid": room_jid,
            "inviter": inviter,
            "reason": reason or "",
            "created_at": created_at,
        }
        pending[invite_id] = invite
        index[key] = invite_id
        return invite

    try:
        cur = await conn.execute(
            """
            INSERT INTO room_invites (room_jid, inviter, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (room_jid, inviter, reason or "", created_at),
        )
        await conn.commit()
        invite_id = int(cur.lastrowid)
    except Exception:
        await load_pending_room_invites(bot)
        return bot.pending_room_invites.get(bot.pending_room_invite_index.get(key))

    invite = {
        "id": invite_id,
        "room_jid": room_jid,
        "inviter": inviter,
        "reason": reason or "",
        "created_at": created_at,
    }
    pending[invite_id] = invite
    index[key] = invite_id
    return invite


async def _delete_pending_room_invite(bot, invite_id: int) -> dict | None:
    """Delete and return one pending room invite."""
    pending = getattr(bot, "pending_room_invites", {})
    index = getattr(bot, "pending_room_invite_index", {})
    if not isinstance(pending, dict):
        pending = {}
    if not isinstance(index, dict):
        index = {}
    bot.pending_room_invites = pending
    bot.pending_room_invite_index = index
    invite = pending.pop(invite_id, None)

    conn = getattr(getattr(bot, "db", None), "conn", None)
    if conn is not None:
        if invite is None:
            async with conn.execute(
                "SELECT id, room_jid, inviter, reason, created_at FROM room_invites WHERE id = ?",
                (invite_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                invite = {
                    "id": int(row[0]),
                    "room_jid": str(row[1]).lower(),
                    "inviter": str(row[2]).lower(),
                    "reason": row[3] or "",
                    "created_at": int(row[4] or 0),
                }
        await conn.execute("DELETE FROM room_invites WHERE id = ?", (invite_id,))
        await conn.commit()

    if invite:
        index.pop((str(invite["room_jid"]), str(invite["inviter"])), None)
    return invite


async def cleanup_expired_room_invites(bot) -> int:
    """Delete expired pending room invites and return the number removed."""
    await load_pending_room_invites(bot)
    max_age_days = _room_invite_max_age_days()
    if max_age_days <= 0:
        return 0

    now = int(time.time())
    expired = [
        invite_id
        for invite_id, invite in tuple(getattr(bot, "pending_room_invites", {}).items())
        if _room_invite_is_expired(invite, now=now)
    ]
    for invite_id in expired:
        await _delete_pending_room_invite(bot, invite_id)
    return len(expired)


async def cleanup_all_room_invites(bot) -> int:
    """Delete all pending room invites and return the number removed."""
    await load_pending_room_invites(bot)
    count = len(getattr(bot, "pending_room_invites", {}) or {})
    conn = getattr(getattr(bot, "db", None), "conn", None)
    if conn is not None:
        cur = await conn.execute("DELETE FROM room_invites")
        await conn.commit()
        if cur.rowcount is not None and cur.rowcount >= 0:
            count = cur.rowcount
    bot.pending_room_invites = {}
    bot.pending_room_invite_index = {}
    return count


async def _notify_room_invite(bot, body: str) -> None:
    """Send an invite workflow notification to owner or admin room."""
    target = room_invite_notify_target()
    if not target:
        log.warning("Room invite notification skipped: no target configured")
        return
    await ensure_notification_target_joined(bot, target)
    message = bot.make_message(
        mto=target,
        mbody=body,
        mtype=notification_message_type(bot, target),
    )
    await bot._safe_send_message(message)


async def handle_room_invite(bot, msg) -> bool:
    """Handle a MUC invite stanza when present. Return True when consumed."""
    invite = extract_room_invite(msg)
    if not invite:
        return False

    room_jid = (invite.get("room_jid") or "").strip().lower()
    inviter = (invite.get("inviter") or "unknown").strip().lower()
    reason = (invite.get("reason") or "").strip()

    if not room_invites_enabled():
        log.info("Room invites disabled; ignoring invite for %s from %s", room_jid, inviter)
        return True

    if not room_jid or "/" in room_jid or "@" not in room_jid:
        await _notify_room_invite(
            bot,
            "⚠️ Ignored invalid room invite.\n"
            f"Room: {room_jid or '<missing>'}\n"
            f"Invited by: {inviter}",
        )
        return True

    if room_jid in JOINED_ROOMS:
        log.info("Ignoring invite for already joined room %s from %s", room_jid, inviter)
        return True

    stored = await bot.db.rooms.get(room_jid) if getattr(bot.db, "rooms", None) else None
    if stored and stored[2]:
        log.info("Ignoring invite for already stored autojoin room %s from %s", room_jid, inviter)
        return True

    pending = await _store_pending_room_invite(bot, room_jid, inviter, reason)
    if not pending:
        return True

    reason_line = f"\nReason: {reason}" if reason else ""
    await _notify_room_invite(
        bot,
        "📨 New EnvsBot room invite\n"
        f"ID: {pending['id']}\n"
        f"Room: {room_jid}\n"
        f"Invited by: {inviter}"
        f"{reason_line}\n\n"
        f"Accept: {bot.prefix}rooms invite accept {pending['id']}\n"
        f"Decline: {bot.prefix}rooms invite decline {pending['id']}",
    )
    await audit_event(
        bot,
        "room_invite_received",
        actor=inviter,
        target=room_jid,
        details={"invite_id": pending["id"], "reason": reason},
    )
    return True


async def on_room_invite_message(bot, msg) -> None:
    """Inspect chat/normal message stanzas for MUC invite payloads."""
    try:
        msg_type = msg["type"]
    except Exception:
        msg_type = msg.get("type", "")
    if msg_type not in ("chat", "normal"):
        return
    await handle_room_invite(bot, msg)


async def on_room_invite(bot, msg) -> None:
    """Handle Slixmpp MUC invite events."""
    handled = await handle_room_invite(bot, msg)
    if not handled:
        log.warning("Room invite event received without an extractable room JID")


async def _join_invited_room(bot, room_jid: str, room_nick: str) -> None:
    """Join a room and store it with autojoin enabled."""
    _LEAVING_ROOMS.discard(room_jid)
    muc = bot.plugin["xep_0045"]
    await muc.join_muc(
        room_jid,
        room_nick,
        pshow=bot.presence.status["show"],
        pstatus=bot.presence.status["status"],
    )

    db_room = await bot.db.rooms.get(room_jid)
    if db_room:
        await bot.db.rooms.update(room_jid, nick=room_nick, autojoin=True)
    else:
        await bot.db.rooms.add(room_jid, room_nick, True)

    JOINED_ROOMS[room_jid] = {
        "nick": room_nick,
        "autojoin": True,
        "status": None,
        "affiliation": "unknown",
        "role": "unknown",
        "nicks": {},
    }
    bot.presence.joined_rooms[room_jid] = room_nick
    bot.presence.broadcast()
    await set_room_control_defaults(bot, room_jid)


async def on_ready(bot):
    """Load pending room invites after the database is ready."""
    await load_pending_room_invites(bot)
    await cleanup_expired_room_invites(bot)

# -------------------------------------------------
# Event Handlers
# -------------------------------------------------

# Handlers
def is_nick_change(pres):
    # Looks for <status code="303"/> (nick change)
    search = './/{http://jabber.org/protocol/muc#user}status'
    for stat in pres.xml.findall(search):
        if stat.attrib.get("code") == "303":
            return True
    return False


async def _maybe_await_result(result):
    """Await result when a slixmpp helper returns an awaitable."""
    if inspect.isawaitable(result):
        return await result
    return result


def _get_plugin_store(bot, plugin_name: str):
    """Return a plugin runtime store, or None when unavailable."""
    users = getattr(getattr(bot, "db", None), "users", None)
    plugin_getter = getattr(users, "plugin", None)
    if not callable(plugin_getter):
        return None
    try:
        return plugin_getter(plugin_name)
    except Exception:
        log.debug(
            "[ROOMS] Could not open plugin store %s",
            plugin_name,
            exc_info=True,
        )
        return None


async def _store_get_global(store, key: str, default=None):
    """Read a plugin-global key from a runtime store."""
    getter = getattr(store, "get_global", None)
    if not callable(getter):
        return default
    result = getter(key, default=default)
    result = await _maybe_await_result(result)
    return default if result is None else result


async def _store_set_global(store, key: str, value) -> None:
    """Write a plugin-global key to a runtime store."""
    setter = getattr(store, "set_global", None)
    if not callable(setter):
        return
    await _maybe_await_result(setter(key, value))


def _room_matches(left: object, right: str) -> bool:
    """Return True when two room JID values refer to the same bare room."""
    return _jid_bare(left) == right


async def _cleanup_room_toggle_state(bot, room_jid: str) -> int:
    """Remove room-scoped on/off entries from all known plugin stores."""
    removed = 0
    for plugin_name, key in ROOM_TOGGLE_STORES:
        store = _get_plugin_store(bot, plugin_name)
        if store is None:
            continue
        try:
            state = await _store_get_global(store, key, default={})
            if not isinstance(state, dict):
                continue
            matching_key = next(
                (item for item in state if _room_matches(item, room_jid)),
                None,
            )
            if matching_key is None:
                continue
            state.pop(matching_key, None)
            await _store_set_global(store, key, state)
            removed += 1
        except Exception:
            log.warning(
                "[ROOMS] Could not clean %s room state for %s",
                plugin_name,
                room_jid,
                exc_info=True,
            )
    return removed


async def _cleanup_room_plugin_state(bot, room_jid: str) -> dict:
    """Remove persistent plugin state that targets a deleted room.

    Room toggle state is still owned by the rooms plugin because it is backed
    by the shared ``PLUGIN_STORE_CONFIG`` table.  Plugin-specific state is
    delegated to loaded plugin lifecycle hooks via
    ``PluginManager.cleanup_room_state()``.
    """
    summary = {
        "toggles": 0,
        "data": 0,
        "rss_subscriptions": 0,
        "rss_feeds": 0,
        "xkcd_legacy_rooms": 0,
        "plugin_hooks": {},
    }
    try:
        summary["toggles"] = await _cleanup_room_toggle_state(bot, room_jid)

        manager = getattr(bot, "bot_plugins", None)
        cleanup = getattr(manager, "cleanup_room_state", None)
        if callable(cleanup):
            plugin_summary = await _maybe_await_result(cleanup(room_jid))
            if isinstance(plugin_summary, dict):
                summary["plugin_hooks"] = plugin_summary
                _merge_plugin_cleanup_summary(summary, plugin_summary)
    except Exception:
        log.warning(
            "[ROOMS] Plugin cleanup failed for deleted room %s",
            room_jid,
            exc_info=True,
        )
    return summary


def _merge_plugin_cleanup_summary(summary: dict, plugin_summary: dict) -> None:
    """Update legacy summary counters from plugin cleanup hook output."""
    rss = plugin_summary.get("rss")
    if isinstance(rss, dict):
        summary["rss_subscriptions"] = int(rss.get("subscriptions") or 0)
        summary["rss_feeds"] = int(rss.get("feeds") or 0)

    xkcd = plugin_summary.get("xkcd")
    if isinstance(xkcd, dict):
        summary["xkcd_legacy_rooms"] = int(xkcd.get("legacy_rooms") or 0)

    for plugin_name, values in plugin_summary.items():
        if not isinstance(values, dict) or plugin_name in {"rss", "xkcd"}:
            continue
        for key in ("rooms", "data", "reminders"):
            try:
                summary["data"] += int(values.get(key) or 0)
            except (TypeError, ValueError):
                continue


def _plugin_cleanup_changed(summary: dict) -> bool:
    """Return True when a plugin cleanup summary removed anything."""
    for key, value in summary.items():
        if key == "plugin_hooks":
            continue
        try:
            if int(value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return _plugin_hook_cleanup_changed(summary.get("plugin_hooks"))


def _plugin_hook_cleanup_changed(plugin_hooks) -> bool:
    """Return True if any plugin hook summary contains a positive counter."""
    if not isinstance(plugin_hooks, dict):
        return False
    for values in plugin_hooks.values():
        if not isinstance(values, dict):
            continue
        for value in values.values():
            try:
                if int(value or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _room_in_runtime_state(bot, room_jid: str) -> bool:
    """Return True if the room is currently tracked as joined at runtime."""
    presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {})
    return room_jid in JOINED_ROOMS or room_jid in presence_rooms


async def _leave_runtime_room(bot, room_jid: str) -> bool:
    """Leave a room and remove all runtime state for it.

    The room may exist in JOINED_ROOMS, in the presence helper, or both.
    Mark it as intentionally leaving so delayed MUC presence cannot recreate
    stale JOINED_ROOMS entries after delete/leave/sync.
    """
    room_data = JOINED_ROOMS.get(room_jid) or {}
    presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {})
    joined = room_jid in JOINED_ROOMS or room_jid in presence_rooms
    nick_to_leave = room_data.get("nick") or presence_rooms.get(room_jid)

    if joined or nick_to_leave:
        _LEAVING_ROOMS.add(room_jid)

    if nick_to_leave:
        try:
            muc = bot.plugin["xep_0045"]
            await _maybe_await_result(muc.leave_muc(room_jid, nick_to_leave))
        except Exception:
            log.warning("[ROOMS] Error leaving room %s", room_jid, exc_info=True)

    JOINED_ROOMS.pop(room_jid, None)
    presence_rooms.pop(room_jid, None)

    if joined:
        broadcast = getattr(getattr(bot, "presence", None), "broadcast", None)
        if callable(broadcast):
            broadcast()

    return joined


async def on_muc_presence(bot, pres):
    try:
        room = pres["from"].bare
        nick = pres["from"].resource
        role = pres["muc"].get("role")
        jid = pres["muc"].get("jid")
        affiliation = pres["muc"].get("affiliation")
        jid_bare = str(jid.bare) if jid else None

        if room in _LEAVING_ROOMS and room not in JOINED_ROOMS:
            log.debug(
                "[ROOMS] Ignoring stale presence for intentionally left room %s",
                room,
            )
            return

        room_info = JOINED_ROOMS.setdefault(room, {
            "nick": "unknown", "autojoin": "unknown", "status": None,
            "affiliation": "unknown", "role": "unknown", "nicks": {}
        })

        nicks = room_info["nicks"]

        # --- Handle nick changes: remove old, add new ---
        if is_nick_change(pres) and pres["type"] == "unavailable":
            old_nick = nick
            if old_nick in nicks:
                del nicks[old_nick]
            log.debug(f"[ROOMS] Removed old nick due to nick change: {
                      old_nick} from {room}")
            return  # Don't re-add, handled by new presence

        # --- Handle leaves/disconnects/kicks/bans ---
        if pres["type"] == "unavailable":
            if nick in nicks:
                del nicks[nick]
                log.debug(f"[ROOMS] Removed nick {nick} from {room}")
            # If the bot itself left the room, remove entire entry
            if nick == room_info.get("nick"):
                JOINED_ROOMS.pop(room, None)
                log.info(f"[ROOMS] Bot left room {
                         room}, cleaned up room state.")
            return

        # --- Else: presence update or join (available) ---
        affiliation = affiliation if affiliation is not None else "unknown"
        nicks[nick] = {
            "jid": jid_bare if jid is not None else str(pres["from"]),
            "affiliation": affiliation,
            "role": role if role is not None else "unknown"
        }

        # Update bot's own state in room_info if relevant
        if jid_bare == bot.boundjid.bare:
            if affiliation is not None:
                room_info["affiliation"] = affiliation
            if role is not None:
                room_info["role"] = role
            if nick != room_info["nick"]:
                room_info["nick"] = nick

        JOINED_ROOMS[room] = room_info

    except Exception as e:
        log.exception(f"[ROOMS] Error in on_muc_presence: {e}")

# -------------------------------------------------
# ON_LOAD startup function (Module autoloadind)
# -------------------------------------------------


async def on_load(bot):

    # --- add event handlers ---
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_presence",
        partial(on_muc_presence, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "message",
        partial(on_room_invite_message, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_invite",
        partial(on_room_invite, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_direct_invite",
        partial(on_room_invite, bot))

    # get muc and rooms_db with guard
    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        log.warning("[ROOMS] 🟡️ missing dependencies: "
                    f"rooms_db={'OK' if rooms_db is not None else 'missing'} "
                    f"xep_0045={'OK' if muc is not None else 'missing'}")
        return

    # Case 1: reload → restore previous runtime state
    reload_rooms = getattr(bot, "_reload_rooms", None)

    if reload_rooms is not None:
        del bot._reload_rooms

        for room, data in tuple(reload_rooms.items()):
            # --- Get room data from DB ---
            db_room = await rooms_db.get(room)
            if db_room:
                _, db_nick, db_autojoin, db_status = db_room
            else:
                db_nick = None
                db_autojoin = None
                db_status = None

            # --- Runtime truth from slixmpp
            raw_nick = (data.get("nick")
                        or db_nick
                        or config.get("nick")
                        or "envsbot")
            nick = str(raw_nick)

            # Use runtime state if available, fallback to DB
            autojoin = data.get("autojoin")
            if autojoin is None:
                autojoin = db_autojoin

            status = data.get("status") or db_status or None

            # --- rebuild runtime state ---
            JOINED_ROOMS[room] = {
                "nick": nick,
                "autojoin": autojoin,
                "status": status,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {}
            }

            await muc.join_muc(
                room,
                nick,
                pshow=bot.presence.status["show"],
                pstatus=bot.presence.status["status"]
            )

            bot.presence.joined_rooms[room] = nick
    else:
        # Case 2: normal startup → use config
        await autojoin_rooms(bot)


# -------------------------------------------------
# ON_UNLOAD teardown function.
# -------------------------------------------------

async def on_unload(bot):
    bot._reload_rooms = dict(JOINED_ROOMS)

    for room_jid, data in tuple(JOINED_ROOMS.items()):
        bot.plugin["xep_0045"].leave_muc(room_jid, data["nick"])

    bot.presence.joined_rooms.clear()


# -------------------------------------------------
# ROOM PRIVILEGE CHECK
# -------------------------------------------------

def bot_has_privilege(room, required=("admin", "owner")):
    info = JOINED_ROOMS.get(room)
    if not info:
        return False
    return info.get("affiliation") in required


# -------------------------------------------------
# ROOM JID VALIDATION
# -------------------------------------------------

async def is_valid_muc_domain(bot, domain: str) -> bool:
    """
    Check if a domain provides a MUC service using XMPP service discovery.
    """

    try:
        info = await bot["xep_0030"].get_info(jid=domain)

        for feature in info["disco_info"]["features"]:
            if feature == "http://jabber.org/protocol/muc":
                return True

    except Exception as e:
        log.warning("[ROOMS] 🟡️ MUC discovery failed for %s: %s", domain, e)

    return False


async def is_valid_room_jid(bot, jid: str, msg) -> bool:
    """
    Validate that a string looks like a proper room JID.

    Requirements
    ------------
    - must contain node@domain
    - must not contain a resource part
    """

    if "/" in jid:
        return False

    if "@" not in jid:
        return False

    node, domain = jid.split("@", 1)

    if not node or not domain:
        return False

    try:
        async with asyncio.timeout(5):
            is_valid = await is_valid_muc_domain(bot, domain)
    except TimeoutError:
        is_valid = False
    if not is_valid:
        bot.reply(
            msg,
            f"🟡️ Domain '{domain}' does not provide muc service.")
        return False
    return True


# -------------------------------------------------
# ROOM STATUS HELPER FUNCTIONS
# -------------------------------------------------
async def room_status_get(bot, room_jid, path=None):
    return await bot.db.rooms.status_get(room_jid, path)


async def room_status_set(bot, room_jid, path, value):
    await bot.db.rooms.status_set(room_jid, path, value)


async def room_status_delete(bot, room_jid, path):
    await bot.db.rooms.status_delete(room_jid, path)


# -------------------------------------------------
# AutoJoin Rooms function
# -------------------------------------------------

async def autojoin_rooms(bot):
    """
    Join all rooms marked with autojoin in the database.
    """
    # get muc and rooms_db with guard
    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        log.warning("[ROOMS] 🟡️ missing dependencies: "
                    f"rooms_db={'OK' if rooms_db is not None else 'missing'} "
                    f"xep_0045={'OK' if muc is not None else 'missing'}")
        return

    rows = await rooms_db.list()
    for room_jid, nick, autojoin, status in rows:
        if not autojoin:
            continue
        _LEAVING_ROOMS.discard(room_jid)
        log.info("[MUC] Autojoining room %s as %s", room_jid, nick)
        try:
            await muc.join_muc(
                room_jid,
                nick,
                pshow=bot.presence.status["show"],
                pstatus=bot.presence.status["status"])

            room_info = JOINED_ROOMS.get(room_jid)

            if room_info:
                # ✅ partial update (DO NOT overwrite runtime data)
                room_info["autojoin"] = autojoin
                room_info["status"] = status

                # optional: update nick if you trust DB more
                # room_info["nick"] = nick

            else:
                # ✅ full create (first time)
                JOINED_ROOMS[room_jid] = {
                    "nick": nick,
                    "autojoin": autojoin,
                    "status": status,
                    "affiliation": "unknown",
                    "role": "unknown",
                    "nicks": {}
                }
                bot.presence.joined_rooms[room_jid] = nick
        except Exception:
            log.exception(f"[ROOMS] 🔴 Couldn't join room '{room_jid}'")


# -------------------------------------------------
# Set Room Control Defaults (for plugins that use room control)
# -------------------------------------------------
async def set_room_control_defaults(bot, room_jid, defaults=None):
    """
    Reset all plugin room controls to their configured defaults.

    Important:
    The storage key is not always the plugin name. Use the configured
    PLUGIN_STORE_CONFIG[plugin]["key"] for get_global/set_global.
    """
    if defaults is None:
        defaults = get_room_plugin_defaults()

    for plugin, should_enable in defaults.items():
        plugin = _normalize_room_plugin_default_name(plugin)
        if plugin not in PLUGIN_STORE_CONFIG:
            log.warning("[ROOMS] Ignoring unknown room plugin default: %s", plugin)
            continue
        conf = PLUGIN_STORE_CONFIG[plugin]
        typ = conf["type"]
        key = conf["key"]
        store = bot.db.users.plugin(plugin)

        if typ == "dict":
            state = await store.get_global(key, default={})
            if not isinstance(state, dict):
                state = {}

            if should_enable:
                state[room_jid] = True
            else:
                state.pop(room_jid, None)

            log.info(f"[ROOMS][DICT] Setting defaults for plugin '{
                     plugin}' key '{key}': {state}")
            await store.set_global(key, state)

        elif typ == "list":
            list_field = conf.get("list_field", "rooms")
            state = await store.get_global(key, default={list_field: []})
            if not isinstance(state, dict):
                state = {list_field: []}

            rooms = state.get(list_field, [])
            if not isinstance(rooms, list):
                rooms = []

            if should_enable:
                if room_jid not in rooms:
                    rooms.append(room_jid)
            else:
                if room_jid in rooms:
                    rooms.remove(room_jid)

            state[list_field] = rooms

            log.info(f"[ROOMS][LIST] Setting defaults for plugin '{
                     plugin}' key '{key}': {rooms}")
            await store.set_global(key, state)

        else:
            raise ValueError(f"Unsupported storage type: {
                             typ} for plugin {plugin}")


# -------------------------------------------------
# ROOMS SETDEFAULTS
# -------------------------------------------------
@command(
    "rooms set_plugin_defaults",
    role=Role.USER,
    aliases=["room set_plugin_defaults", "rooms spd", "room spd"],
)
async def cmd_room_setdefaults(bot, sender_jid, nick, args, msg, is_room):
    """Reset room plugin toggles to their defaults."""
    usage = f"{bot.prefix}rooms set_plugin_defaults [<room_jid>]"
    resolved = await _resolve_room_settings_target(bot, msg, is_room, args, sender_jid, usage)
    if resolved is None:
        return
    room_jid, remaining = resolved
    if remaining:
        bot.reply_usage(msg, usage)
        return

    try:
        await set_room_control_defaults(bot, room_jid)
        await audit_event(
            bot,
            "room_plugin_defaults_restored",
            actor=sender_jid,
            target=room_jid,
        )
        bot.reply_ok(msg, f"Restored plugin defaults for room '{room_jid}'.")
        log.info("[ROOMS] Restored plugin defaults for room %s", room_jid)
    except Exception as e:
        bot.reply_error(msg, f"Error restoring defaults: {e}")
        log.exception("[ROOMS] Error restoring defaults for room %s", room_jid)


# -------------------------------------------------
# ROOMS PLUGINS
# -------------------------------------------------
@command(
    "rooms plugins",
    role=Role.USER,
    aliases=[
        "room plugins",
        "rooms features",
        "room features",
        "rooms feature list",
        "room feature list",
    ],
)
async def cmd_room_plugins(bot, sender_jid, nick, args, msg, is_room):
    """Show plugin setup for a room."""
    usage = f"{bot.prefix}rooms plugins [<room_jid>] [all|page|last]"
    resolved = await _resolve_room_settings_target(bot, msg, is_room, args, sender_jid, usage)
    if resolved is None:
        return
    room_jid, remaining = resolved

    page = parse_page_args(remaining)
    states = await list_room_features(bot, room_jid)
    feature_lines = [format_room_feature_line(state) for state in states]
    lines = format_page(
        f"📋 Plugin settings for room '{room_jid}'",
        feature_lines,
        page_request=page,
        page_size=12,
        command_hint=f"{bot.prefix}rooms plugins {room_jid}",
    )

    log.info("[ROOMS] displaying plugin settings for room %s", room_jid)
    bot.reply(msg, lines)


async def _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, *, enabled: bool):
    """Shared implementation for rooms enable/disable."""
    action = "enable" if enabled else "disable"
    usage = f"{bot.prefix}rooms {action} [<room_jid>] <plugin>"
    resolved = await _resolve_room_settings_target(bot, msg, is_room, args, sender_jid, usage)
    if resolved is None:
        return
    room_jid, remaining = resolved
    if len(remaining) != 1:
        bot.reply_usage(msg, usage)
        return

    plugin = remaining[0].lower()
    try:
        previous = await get_room_feature(bot, room_jid, plugin)
        state = await set_room_feature(bot, room_jid, plugin, enabled)
    except KeyError:
        bot.reply_warn(
            msg,
            f"Unknown room plugin '{plugin}'. Use {bot.prefix}rooms plugins {room_jid} to list valid names.",
        )
        return

    if previous.enabled == state.enabled:
        bot.reply_info(msg, f"{state.name} is already {format_room_feature_line(state).split(': ', 1)[1]}.")
        return

    await audit_event(
        bot,
        "room_feature_changed",
        actor=sender_jid,
        target=room_jid,
        details={"plugin": state.name, "enabled": state.enabled},
    )
    bot.reply_ok(msg, f"{state.name} is now {'enabled' if state.enabled else 'disabled'} for {room_jid}.")


@command(
    "rooms enable",
    role=Role.USER,
    aliases=["room enable", "rooms feature enable", "room feature enable"],
)
async def cmd_room_enable(bot, sender_jid, nick, args, msg, is_room):
    """Enable a room-scoped plugin for a room."""
    await _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, enabled=True)


@command(
    "rooms disable",
    role=Role.USER,
    aliases=["room disable", "rooms feature disable", "room feature disable"],
)
async def cmd_room_disable(bot, sender_jid, nick, args, msg, is_room):
    """Disable a room-scoped plugin for a room."""
    await _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, enabled=False)


# -------------------------------------------------
# ROOMS ADD
# -------------------------------------------------

@command("rooms add", role=Role.ADMIN, aliases=["room add"])
async def rooms_add(bot, sender_jid, nick, args, msg, is_room):
    """
    Add a new room configuration to the database. Doesn't join immediately!

    Command
    -------
    {prefix}rooms add <room_jid> <nick> [autojoin]

    Description
    -----------
    Registers a room together with the nickname the bot should use
    when joining it.

    If the optional *autojoin* flag is enabled, the bot will join
    the room automatically during startup.

    Examples
    --------
    {prefix}rooms add dev@conference.example.org BotNick
    {prefix}rooms add dev@conference.example.org BotNick true
    """

    if len(args) < 2 or len(args) > 3:
        bot.reply(
            msg,
            (f"🟡️ Usage: {bot.prefix}rooms add <room_jid>"
             " <nick> [autojoin]"),
        )
        return

    room_jid = args[0]
    room_nick = args[1]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"🟡️ Invalid room JID: {room_jid}"
        )
        log.warning(f"[ROOMS]🟡️ Room '{room_jid}' not valid!")
        return

    autojoin = len(args) >= 3 and args[2].lower() in ("true", "1", "yes")

    db_room = await bot.db.rooms.get(room_jid)
    if not db_room:
        await bot.db.rooms.add(room_jid, room_nick, autojoin)

        log.info("[ROOMS] ➕ Added room %s nick=%s autojoin=%s",
                 room_jid, room_nick, autojoin)
        try:
            await set_room_control_defaults(bot, room_jid)
            await audit_event(
                bot,
                "room_added",
                actor=sender_jid,
                target=room_jid,
                details={"nick": room_nick, "autojoin": autojoin},
            )
            log.info(f"[ROOMS] ✅ Set plugin defaults for new room '{
                     room_jid}'.")
            bot.reply(msg, f"✅ Room added: {room_jid}. Plugin defaults set.")
        except Exception as e:
            log.exception("[ROOMS] 🔴 Error setting plugin defaults for"
                          f" new room '{room_jid}': {e}")
            bot.reply(msg, f"🔴 Error setting plugin defaults: {e}")
        return

    bot.reply(msg, f"[ROOMS] 🔴 Room already exists: {room_jid}")


# -------------------------------------------------
# ROOMS UPDATE
# -------------------------------------------------

@command("rooms update", role=Role.ADMIN, aliases=["room update"])
async def rooms_update(bot, sender_jid, nick, args, msg, is_room):
    """
    Update a configuration field of a stored room.

    Command
    -------
    {prefix}rooms update <room_jid> <field> <value>

    Supported fields
    ----------------
    nick
        Nickname the bot should use when joining the room.
    autojoin
        Controls whether the bot automatically joins the room
        when it starts.

        Allowed values:
        true, false, yes, no, 1, 0
    """

    if len(args) != 3:
        bot.reply(
            msg,
            (f"🟡️ Usage: {bot.prefix}rooms update <room_jid>"
             f" <field> <value>"),
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"🟡️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS] 🟡️ Room '{room_jid}' not valid!")
        return

    field = args[1].lower()
    value = args[2]
    if field in ["nick", "autojoin"]:

        if field == "autojoin":
            value = value.lower() in ("true", "1", "yes")

        await bot.db.rooms.update(room_jid, **{field: value})
        await audit_event(
            bot,
            "room_updated",
            actor=sender_jid,
            target=room_jid,
            details={field: value},
        )

        log.info("[ROOMS] 🔧 Updated %s: %s=%s", room_jid, field, value)

        bot.reply(
            msg,
            f"🔧 Room updated: {room_jid}",
        )
    else:
        log.info("[ROOMS] 🔧 Update failed! Invalid field '%s'", field)

        bot.reply(
            msg,
            f"🔧 Room not updated. Invalid field: '{field}'",
        )


# -------------------------------------------------
# ROOMS DELETE
# -------------------------------------------------

@command("rooms delete", role=Role.ADMIN, aliases=["room delete"])
async def rooms_delete(bot, sender_jid, nick, args, msg, is_room):
    """
    Remove a room configuration from the database.

    Command
    -------
    {prefix}rooms delete <room_jid> [force]

    Description
    -----------
    Deletes a stored room configuration.

    If the bot is currently joined to that room it will leave it
    automatically.
    """

    if len(args) < 1:
        bot.reply(
            msg,
            f"🟡️ Usage: {bot.prefix}rooms delete <room_jid>",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"🟡️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS] 🟡️ Room '{room_jid}' not valid!")
        return

    try:
        db_room = await bot.db.rooms.get(room_jid)
        runtime_room = _room_in_runtime_state(bot, room_jid)

        if not db_room and not runtime_room:
            plugin_cleanup = await _cleanup_room_plugin_state(bot, room_jid)
            if _plugin_cleanup_changed(plugin_cleanup):
                log.info(
                    "[ROOMS] 🧹 Cleaned stale plugin state for %s: %s",
                    room_jid,
                    plugin_cleanup,
                )
                await audit_event(
                    bot,
                    "room_plugin_state_cleaned",
                    actor=sender_jid,
                    target=room_jid,
                    details={"plugin_cleanup": plugin_cleanup},
                )
                bot.reply(
                    msg,
                    f"🧹 Room was not stored, but stale plugin state was cleaned: {room_jid}",
                )
                return

            bot.reply_info(
                msg,
                f"Room is not used by this bot: {room_jid}",
            )
            return

        plugin_cleanup = await _cleanup_room_plugin_state(bot, room_jid)
        if db_room:
            await bot.db.rooms.delete(room_jid)

        joined = await _leave_runtime_room(bot, room_jid)

        if joined:
            log.info("[ROOMS] 🚶 Left room %s", room_jid)

        if _plugin_cleanup_changed(plugin_cleanup):
            log.info(
                "[ROOMS] 🧹 Cleaned plugin state for %s: %s",
                room_jid,
                plugin_cleanup,
            )
        log.info("[ROOMS] 🗑️ Deleted room %s", room_jid)
        await audit_event(
            bot,
            "room_deleted",
            actor=sender_jid,
            target=room_jid,
            details={"left": joined, "plugin_cleanup": plugin_cleanup},
        )

        bot.reply(
            msg,
            f"🗑️ Room removed: {room_jid}",
        )

    except Exception:
        log.exception("[ROOMS] 🗑️ Failed to delete room %s", room_jid)

        bot.reply(
            msg,
            f"🗑️ Failed remove room: {room_jid}",
        )


# -------------------------------------------------
# ROOMS LIST
# -------------------------------------------------

@command("rooms list", role=Role.ADMIN, aliases=["room list"])
async def rooms_list(bot, sender_jid, nick, args, msg, is_room):
    """Show stored and currently joined rooms."""

    rows = await bot.db.rooms.list()
    page = parse_page_args(args)

    joined_rooms_copy = dict(JOINED_ROOMS)
    details = [
        f"Counts: stored={len(rows)} | joined={len(joined_rooms_copy)}",
        "",
    ]
    if rows:
        details.append("Stored rooms:")
        for room_jid, nick_name, autojoin, status in rows:
            autojoin_flag = "yes" if autojoin else "no"
            joined_flag = "yes" if room_jid in JOINED_ROOMS else "no"
            status_display = status if status and status != "{}" else ""
            details.append(
                f"• {room_jid} | nick={nick_name} | autojoin={autojoin_flag} "
                f"| joined={joined_flag} | status={status_display or '—'}"
            )
    else:
        details.append("Stored rooms: —")

    details.append("")
    details.append("Joined rooms:")
    if joined_rooms_copy:
        for room, data in sorted(tuple(joined_rooms_copy.items())):
            try:
                nick_name = data.get("nick", "unknown")
                affiliation = data.get("affiliation", "unknown")
                role = data.get("role", "unknown")
                autojoin = "yes" if data.get("autojoin", False) else "no"
                status = data.get("status") or "—"
                if status == "{}":
                    status = "—"
                details.append(
                    f"• {room} | nick={nick_name} | affiliation={affiliation} "
                    f"| role={role} | autojoin={autojoin} | status={status}"
                )
            except Exception as e:
                log.debug("[ROOMS] Error formatting room info for %s: %s", room, e)
    else:
        details.append("Joined rooms: —")

    bot.reply(
        msg,
        format_page(
            "📋 Rooms",
            details,
            page_request=page,
            page_size=12,
            command_hint=f"{bot.prefix}rooms list",
        ),
    )


# -------------------------------------------------
# ROOMS JOIN
# -------------------------------------------------

@command("rooms join", role=Role.ADMIN, aliases=["room join"])
async def rooms_join(bot, sender_jid, nick, args, msg, is_room):
    """
    Join a room immediately, add it to JOINED ROOMS and DB.

    Command
    -------
    {prefix}rooms join <room_jid> [nick]
    """

    if len(args) < 1 or len(args) > 2:
        bot.reply(
            msg,
            f"🟡️ Usage: {bot.prefix}rooms join <room_jid> [nick]",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"🟡️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS] 🟡️ Room '{room_jid}' not valid!")
        return

    if len(args) == 2:
        room_nick = args[1]
    else:
        room = await bot.db.rooms.get(room_jid)
        room_nick = room[1] if room else bot.boundjid.resource

    try:
        _LEAVING_ROOMS.discard(room_jid)
        muc = bot.plugin["xep_0045"]

        await muc.join_muc(room_jid,
                           room_nick,
                           pshow=bot.presence.status["show"],
                           pstatus=bot.presence.status["status"])

        # Get current room state from DB
        db_room = await bot.db.rooms.get(room_jid)
        current_autojoin = db_room[2] if db_room else False
        current_status = db_room[3] if db_room else None

        if room_jid not in JOINED_ROOMS:
            JOINED_ROOMS[room_jid] = {
                "nick": room_nick,
                "autojoin": current_autojoin,
                "status": current_status,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {}
            }

        bot.presence.joined_rooms[room_jid] = room_nick
        bot.presence.broadcast()

        # Only add if it doesn't exist; update if it does
        if db_room:
            # Room exists, only update nick if different
            if db_room[1] != room_nick:
                await bot.db.rooms.update(room_jid, nick=room_nick)
        else:
            # New room, add with autojoin=False (default for manual join)
            await bot.db.rooms.add(room_jid, room_nick, False)

        log.info("[ROOMS] 🚪 Joined room %s nick=%s", room_jid, room_nick)
        await audit_event(
            bot,
            "room_joined",
            actor=sender_jid,
            target=room_jid,
            details={"nick": room_nick},
        )

        bot.reply(
            msg,
            f"🚪 Joined room: {room_jid}",
        )
    except Exception:
        log.exception("[ROOMS] 🚪 Joining room %s nick=%s FAILED!",
                      room_jid, room_nick)
        bot.reply(
            msg,
            f"🚪 Joining room FAILED: {room_jid}",
        )


# -------------------------------------------------
# ROOMS LEAVE
# -------------------------------------------------

@command("rooms leave", role=Role.ADMIN, aliases=["room leave"])
async def rooms_leave(bot, sender_jid, nick, args, msg, is_room):
    """
    Leave a joined room immediately. Doesn't touch the database. Only deletes
    it from the current JOINED_ROOMS list, without altering the 'autojoin'
    flag.

    Command
    -------
    {prefix}rooms leave <room_jid>
    """

    if len(args) != 1:
        bot.reply(
            msg,
            f"🟡️ Usage: {bot.prefix}rooms leave <room_jid>",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"🟡️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS] 🟡️ Room '{room_jid}' not valid!")
        return

    try:
        joined = await _leave_runtime_room(bot, room_jid)

        if not joined:
            if await _room_is_known(bot, room_jid):
                bot.reply(
                    msg,
                    f"ℹ️ Room already left: {room_jid}",
                )
            else:
                bot.reply(
                    msg,
                    f"ℹ️ Room is not used by this bot: {room_jid}",
                )
            return

        log.info("[ROOMS] 🚶 Left room %s", room_jid)
        await audit_event(bot, "room_left", actor=sender_jid, target=room_jid)

        bot.reply(
            msg,
            f"🚶 Left room: {room_jid}",
        )

    except Exception:
        log.exception("[ROOMS] 🚶 Failed to leave room %s", room_jid)

        bot.reply(
            msg,
            f"🚶 Failed to leave room: {room_jid}",
        )



# -------------------------------------------------
# ROOMS INVITE
# -------------------------------------------------

@command("rooms invite", role=Role.ADMIN, aliases=["room invite"])
async def rooms_invite(bot, sender_jid, nick, args, msg, is_room):
    """List, accept or decline pending room invites."""
    if not room_invites_enabled():
        bot.reply_error(
            msg,
            "Room invite workflow is disabled. "
            "Enable ROOM_INVITES_ENABLED in config.py.",
        )
        return

    if not args or args[0].lower() in {"help", "usage"}:
        bot.reply(
            msg,
            "Usage:\n"
            f"  {bot.prefix}rooms invite list [all|page|last]\n"
            f"  {bot.prefix}rooms invite accept <id>\n"
            f"  {bot.prefix}rooms invite decline <id>\n"
            f"  {bot.prefix}rooms invite cleanup [all|expired]",
        )
        return

    action = args[0].lower()

    if action == "cleanup":
        cleanup_mode = args[1].lower() if len(args) > 1 else "all"
        if len(args) > 2 or cleanup_mode not in {"all", "expired"}:
            bot.reply_usage(
                msg,
                f"{bot.prefix}rooms invite cleanup [all|expired]",
            )
            return

        if cleanup_mode == "expired":
            count = await cleanup_expired_room_invites(bot)
            bot.reply_ok(
                msg,
                "Expired pending room invite cleanup completed. "
                f"Deleted: {count}",
            )
        else:
            count = await cleanup_all_room_invites(bot)
            bot.reply_ok(
                msg,
                "Pending room invite cleanup completed. "
                f"Deleted: {count}",
            )
        await audit_event(
            bot,
            "room_invites_cleaned",
            actor=sender_jid,
            target="room_invites",
            details={"mode": cleanup_mode, "count": count},
        )
        return

    if action in {"list", "ls"}:
        await load_pending_room_invites(bot)
        await cleanup_expired_room_invites(bot)
        invites = [
            bot.pending_room_invites[invite_id]
            for invite_id in sorted(getattr(bot, "pending_room_invites", {}))
        ]
        lines = []
        if invites:
            for invite in invites:
                reason = f" — {invite['reason']}" if invite.get("reason") else ""
                lines.append(
                    f"#{invite['id']} {invite['room_jid']} — invited by {invite['inviter']}{reason}"
                )
        else:
            lines.append("None")
        bot.reply(
            msg,
            format_page(
                "📨 Pending Room Invites",
                lines,
                page_request=parse_page_args(args[1:]),
                page_size=10,
                command_hint=f"{bot.prefix}rooms invite list",
            ),
        )
        return

    if action not in {"accept", "decline", "reject", "remove", "rm", "delete", "del"}:
        bot.reply_warn(msg, f"Unknown room invite action: {action}")
        return

    if len(args) < 2:
        bot.reply_usage(msg, f"{bot.prefix}rooms invite {action} <id>")
        return

    try:
        invite_id = int(args[1])
    except ValueError:
        bot.reply_error(msg, "Invite id must be a number.")
        return

    await load_pending_room_invites(bot)
    invite = getattr(bot, "pending_room_invites", {}).get(invite_id)
    if not invite:
        bot.reply_error(msg, f"Unknown pending room invite id: {invite_id}")
        return

    room_jid = str(invite["room_jid"])
    inviter = str(invite["inviter"])

    if action == "accept":
        room_nick = str(config.get("nick") or getattr(bot.boundjid, "resource", None) or "EnvsBot")
        try:
            await _join_invited_room(bot, room_jid, room_nick)
        except Exception:
            log.exception("[ROOMS] Failed to accept room invite #%s", invite_id)
            bot.reply_error(
                msg,
                f"Room invite #{invite_id} could not be accepted. The invite remains pending.",
            )
            return

        await _delete_pending_room_invite(bot, invite_id)
        await audit_event(
            bot,
            "room_invite_accepted",
            actor=sender_jid,
            target=room_jid,
            details={"invite_id": invite_id, "inviter": inviter, "nick": room_nick},
        )
        bot.reply_ok(
            msg,
            f"Accepted room invite #{invite_id}. Joined and stored {room_jid} with autojoin enabled.",
        )
        return

    removed = await _delete_pending_room_invite(bot, invite_id)
    if not removed:
        bot.reply_error(msg, f"Unknown pending room invite id: {invite_id}")
        return

    await audit_event(
        bot,
        "room_invite_declined",
        actor=sender_jid,
        target=room_jid,
        details={"invite_id": invite_id, "inviter": inviter, "action": action},
    )
    bot.reply_ok(msg, f"Declined room invite #{invite_id} for {room_jid}.")


# -------------------------------------------------
# ROOMS SYNC
# -------------------------------------------------

@command("rooms sync", role=Role.ADMIN, aliases=["room sync"])
async def rooms_sync(bot, sender_jid, nick, args, msg, is_room):
    """
    Synchronize runtime rooms with database configuration. Leaves all rooms
    which have not set the 'autojoin' flag and joins the rooms which have the
    'autojoin' flag set.

    Command
    -------
    {prefix}rooms sync

    Description
    -----------
    Ensures that the bot's current room membership matches the
    configuration stored in the database.

    Actions performed
    -----------------
    • Leaves rooms joined by the bot but not stored in the database
    • Leaves all rooms which are in the database but haven't set the 'autojoin'
      flag.
    • Joins rooms that are configured with autojoin=true
    """
    try:
        rows = await bot.db.rooms.list()
    except Exception:
        log.exception("[ROOMS] 🔄 Failed to get rooms from DB")
        bot.reply(
            msg,
            "🔄 Failed to get rooms from DB",
        )
        return

    muc = bot.plugin["xep_0045"]
    left = []
    joined = []

    # Leave all currently joined rooms
    for room in tuple(JOINED_ROOMS.keys()):
        await _leave_runtime_room(bot, room)
        left.append(room)
    JOINED_ROOMS.clear()

    # Join only rooms from DB with autojoin=True
    for room_jid, nick_name, autojoin, status in rows:
        if autojoin:
            try:
                _LEAVING_ROOMS.discard(room_jid)
                await muc.join_muc(
                    room_jid,
                    nick_name,
                    pshow=bot.presence.status['show'],
                    pstatus=bot.presence.status['status']
                )
                JOINED_ROOMS[room_jid] = {
                    "nick": nick_name,
                    "autojoin": autojoin,
                    "status": status,
                    "affiliation": "unknown",
                    "role": "unknown",
                    "nicks": {}
                }
                bot.presence.joined_rooms[room_jid] = nick_name
                joined.append(room_jid)
            except Exception:
                log.exception(f"[ROOMS] 🚪 Failed to join room {room_jid}")

    bot.presence.broadcast()

    log.info("[ROOMS] 🔄 Synchronization complete: joined=%d left=%d",
             len(joined), len(left))
    await audit_event(
        bot,
        "rooms_synced",
        actor=sender_jid,
        target="rooms",
        details={"joined": len(joined), "left": len(left)},
    )

    lines = ["🔄 Room synchronization complete"]
    if left:
        lines.append(f"🚶 Left: {', '.join(left)}")
    if joined:
        lines.append(f"🚪 Joined: {', '.join(joined)}")
    if not joined and not left:
        lines.append("ℹ️ No changes required.")

    bot.reply(
        msg,
        "\n".join(lines),
    )
