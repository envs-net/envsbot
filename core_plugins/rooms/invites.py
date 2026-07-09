"""Split module for core_plugins/rooms.py: invites."""

import time
from xml.etree import ElementTree as ET
from utils.command import command, Role
from utils.config import config
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event
from utils.xmpp_notify import (
    ensure_notification_target_joined,
    notification_message_type,
)

from .settings import set_room_control_defaults
from .state import (
    JOINED_ROOMS,
    _DIRECT_INVITE_NS,
    _LEAVING_ROOMS,
    _MUC_USER_NS,
    _jid_bare,
    _safe_get_plugin,
    _safe_plugin_value,
    log,
)


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


def _invite_inviter_from_attr(value: str | None, room_jid: str = "") -> str:
    """Return the best available inviter identity."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    bare = _jid_bare(raw)
    if room_jid and bare == room_jid and "/" in raw:
        return raw.lower()
    return bare or raw.lower()


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



def _room_invite_onboarding_lines(bot, room_jid: str) -> list[str]:
    """Return concise next steps after accepting a room invite."""
    prefix = getattr(bot, "prefix", None) or str(config.get("prefix", ",") or ",")
    return [
        f"✅ Accepted room invite. Joined and stored {room_jid} with autojoin enabled.",
        "",
        "Next checks:",
        f"• {prefix}rooms diagnose {room_jid}",
        f"• {prefix}rooms plugins {room_jid} all",
        f"• {prefix}doctor rooms",
        "",
        "Tip: make sure the bot has the room affiliation it needs before enabling moderation-like features.",
    ]


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


@command(
    "rooms invite",
    role=Role.ADMIN,
    aliases=["room invite"],
    short="List, accept, decline or clean up pending room invites.",
    usage="{prefix}rooms invite list [all|page|last] | {prefix}rooms invite accept <id> | {prefix}rooms invite decline <id> | {prefix}rooms invite cleanup [all|expired]",
    examples=[
        "{prefix}rooms invite list",
        "{prefix}rooms invite list all",
        "{prefix}rooms invite accept 1",
        "{prefix}rooms invite decline 1",
        "{prefix}rooms invite cleanup",
        "{prefix}rooms invite cleanup all",
        "{prefix}rooms invite cleanup expired",
    ],
    category="rooms",
    context="private chat / MUC PM / invite notify room",
)
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
        lines = _room_invite_onboarding_lines(bot, room_jid)
        lines[0] = f"✅ Accepted room invite #{invite_id}. Joined and stored {room_jid} with autojoin enabled."
        bot.reply(msg, lines)
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
