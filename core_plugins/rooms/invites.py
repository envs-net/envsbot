"""Split module for core_plugins/rooms.py: invites."""

from xml.etree import ElementTree as ET

from envs_xmpp_core.xmpp.invites import (
    extract_room_invite as _core_extract_room_invite,
)
from envs_xmpp_core.xmpp.invites import (
    invite_is_expired as _core_invite_is_expired,
)
from envs_xmpp_core.xmpp.invites import (
    inviter_from_attr as _core_inviter_from_attr,
)
from envs_xmpp_core.xmpp.invites import (
    reason_from_invite_element as _core_reason_from_invite_element,
)
from envs_xmpp_core.xmpp.invites import (
    room_invite_from_direct_plugin as _core_room_invite_from_direct_plugin,
)
from envs_xmpp_core.xmpp.invites import (
    room_invite_from_muc_plugin as _core_room_invite_from_muc_plugin,
)
from envs_xmpp_core.xmpp.pending_invites import (
    PendingRoomInvite,
    PendingRoomInviteStore,
    PendingRoomInviteStoreResult,
)

from utils.audit import audit_event
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config
from utils.formatting import format_page, parse_page_args
from utils.permissions import configured_room_invite_admin_rooms
from utils.xmpp_notify import (
    ensure_notification_target_joined,
    notification_message_type,
    prepare_notification_target,
)

from .settings import set_room_control_defaults
from .state import (
    _LEAVING_ROOMS,
    JOINED_ROOMS,
    _jid_bare,
    _join_muc_with_timeout,
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
    return configured_room_invite_admin_rooms(config)


def _room_invite_max_age_days() -> int:
    """Return configured pending invite max age in days."""
    try:
        return max(0, int(config.get("room_invite_max_age_days", 30) or 0))
    except (TypeError, ValueError):
        return 30


def _room_invite_is_expired(invite: dict, now: int | None = None) -> bool:
    """Return True when a pending invite exceeded the configured max age."""
    return _core_invite_is_expired(
        invite.get("created_at", 0),
        _room_invite_max_age_days(),
        now=now,
    )


def _invite_inviter_from_attr(value: str | None, room_jid: str = "") -> str:
    """Return the best available inviter identity."""
    return _core_inviter_from_attr(value, room_jid, jid_bare=_jid_bare)


def _room_invite_reason_from_invite(invite_el: ET.Element) -> str:
    """Extract an optional mediated invite reason."""
    return _core_reason_from_invite_element(invite_el)


def _room_invite_from_muc_plugin(msg) -> dict[str, str] | None:
    """Extract mediated MUC invites from Slixmpp stanza plugins."""
    invite = _core_room_invite_from_muc_plugin(
        msg,
        jid_bare=_jid_bare,
        get_plugin=_safe_get_plugin,
        plugin_value=_safe_plugin_value,
    )
    return invite.as_dict() if invite is not None else None


def _room_invite_from_direct_plugin(msg) -> dict[str, str] | None:
    """Extract XEP-0249 direct invites from Slixmpp stanza plugins."""
    invite = _core_room_invite_from_direct_plugin(
        msg,
        jid_bare=_jid_bare,
        get_plugin=_safe_get_plugin,
        plugin_value=_safe_plugin_value,
    )
    return invite.as_dict() if invite is not None else None


def extract_room_invite(msg) -> dict[str, str] | None:
    """Extract room, inviter and reason from direct or mediated MUC invites."""
    invite = _core_extract_room_invite(
        msg,
        jid_bare=_jid_bare,
        get_plugin=_safe_get_plugin,
        plugin_value=_safe_plugin_value,
    )
    return invite.as_dict() if invite is not None else None


def _db_api(bot):
    """Return the connected DatabaseManager API when persistence is available."""
    db = getattr(bot, "db", None)
    if db is None or getattr(db, "conn", None) is None:
        return None
    required = ("transaction", "write", "fetch_one", "fetch_all")
    if not all(callable(getattr(db, name, None)) for name in required):
        return None
    return db


class _EnvsBotRoomInviteRepository:
    """Adapt envsbot's DatabaseManager API to the shared invite store."""

    def __init__(self, bot) -> None:
        self.bot = bot

    def available(self) -> bool:
        return _db_api(self.bot) is not None

    async def setup(self) -> None:
        db = _db_api(self.bot)
        if db is None:
            return
        async with db.transaction(label="room_invites_init") as conn:
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

    async def load_all(self) -> list[PendingRoomInvite]:
        db = _db_api(self.bot)
        if db is None:
            return []
        rows = await db.fetch_all(
            """
            SELECT id, room_jid, inviter, reason, created_at
            FROM room_invites
            ORDER BY id ASC
            """
        )
        return [PendingRoomInvite.from_row(row) for row in rows]

    async def insert_if_absent(
        self,
        room_jid: str,
        inviter: str,
        reason: str,
        created_at: int,
    ) -> PendingRoomInviteStoreResult:
        db = _db_api(self.bot)
        if db is None:
            raise RuntimeError("room invite database is unavailable")
        cur = await db.write(
            """
            INSERT INTO room_invites (room_jid, inviter, reason, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(room_jid, inviter) DO NOTHING
            """,
            (room_jid, inviter, reason, created_at),
            label="room_invite_store",
        )
        row = await db.fetch_one(
            """
            SELECT id, room_jid, inviter, reason, created_at
            FROM room_invites
            WHERE room_jid = ? AND inviter = ?
            """,
            (room_jid, inviter),
        )
        if not row:
            raise RuntimeError(f"could not reload stored room invite for {room_jid} from {inviter}")
        return PendingRoomInviteStoreResult(
            PendingRoomInvite.from_row(row),
            created=cur.rowcount == 1,
        )

    async def get(self, invite_id: int) -> PendingRoomInvite | None:
        db = _db_api(self.bot)
        if db is None:
            return None
        row = await db.fetch_one(
            """
            SELECT id, room_jid, inviter, reason, created_at
            FROM room_invites
            WHERE id = ?
            """,
            (invite_id,),
        )
        return PendingRoomInvite.from_row(row) if row else None

    async def delete(self, invite_id: int) -> int:
        db = _db_api(self.bot)
        if db is None:
            return 0
        cur = await db.write(
            "DELETE FROM room_invites WHERE id = ?",
            (invite_id,),
            label="room_invite_delete",
        )
        return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0

    async def delete_many(self, invite_ids) -> int:
        ids = [int(invite_id) for invite_id in invite_ids]
        if not ids:
            return 0
        db = _db_api(self.bot)
        if db is None:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cur = await db.write(
            f"DELETE FROM room_invites WHERE id IN ({placeholders})",
            ids,
            label="room_invites_expire",
        )
        return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else len(ids)

    async def clear(self) -> int:
        db = _db_api(self.bot)
        if db is None:
            return 0
        cur = await db.write(
            "DELETE FROM room_invites",
            label="room_invites_clear",
        )
        return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0


def _pending_invite_store(bot) -> PendingRoomInviteStore:
    """Return the shared store while adopting historical injected test state."""
    store = getattr(bot, "_pending_room_invite_store", None)
    if not isinstance(store, PendingRoomInviteStore):
        store = PendingRoomInviteStore(_EnvsBotRoomInviteRepository(bot))
        bot._pending_room_invite_store = store

    current = getattr(bot, "pending_room_invites", None)
    if isinstance(current, dict) and current is not store.pending:
        store.adopt(current)
    elif not isinstance(current, dict) and current is not store.pending:
        store.adopt({})

    bot.pending_room_invites = store.pending
    bot.pending_room_invite_index = store.index
    return store


async def setup_room_invites_db(bot) -> None:
    """Create the persistent pending room invite table when needed."""
    await _pending_invite_store(bot).setup()


async def load_pending_room_invites(bot) -> dict[int, PendingRoomInvite]:
    """Load pending room invites through the shared typed store."""
    store = _pending_invite_store(bot)
    result = await store.load(max_age_days=_room_invite_max_age_days())
    if result.expired_count:
        log.info("Expired %d pending room invite(s)", result.expired_count)
    return store.pending


async def _store_pending_room_invite(
    bot,
    room_jid: str,
    inviter: str,
    reason: str = "",
) -> PendingRoomInviteStoreResult | None:
    """Persist one pending invite and report whether it was newly created."""
    store = _pending_invite_store(bot)
    try:
        return await store.store(
            room_jid,
            inviter,
            reason,
            max_age_days=_room_invite_max_age_days(),
        )
    except RuntimeError:
        log.exception("Could not store room invite for %s from %s", room_jid, inviter)
        await load_pending_room_invites(bot)
        invite_id = store.index.get((room_jid, inviter))
        existing = store.pending.get(invite_id) if invite_id is not None else None
        if existing is None:
            return None
        return PendingRoomInviteStoreResult(existing, created=False)


async def _delete_pending_room_invite(bot, invite_id: int) -> PendingRoomInvite | None:
    """Delete and return one pending room invite."""
    return await _pending_invite_store(bot).delete(invite_id)


async def cleanup_expired_room_invites(bot) -> int:
    """Delete expired pending room invites and return the number removed."""
    return await _pending_invite_store(bot).cleanup_expired(
        max_age_days=_room_invite_max_age_days()
    )


async def cleanup_all_room_invites(bot) -> int:
    """Delete all pending room invites and return the number removed."""
    return await _pending_invite_store(bot).clear()


async def _notify_room_invite(bot, body: str) -> None:
    """Send an invite workflow notification to owner or admin room."""
    target = room_invite_notify_target()
    if not target:
        log.warning("Room invite notification skipped: no target configured")
        return

    joined = await ensure_notification_target_joined(bot, target)
    message_type: str | None
    if joined:
        # A successful notification-target join means the target is a MUC.
        # Keep the established helper visible here for callers/tests that
        # override message-type detection, but never downgrade a joined MUC
        # to a direct-chat stanza if runtime bookkeeping lags behind.
        message_type = notification_message_type(bot, target)
        if message_type != "groupchat":
            message_type = "groupchat"
    else:
        message_type = await prepare_notification_target(bot, target, joined=False)
    if message_type is None:
        log.warning(
            "Room invite notification deferred: MUC target %s is unavailable; "
            "the invite remains pending",
            target,
        )
        return

    message = bot.make_message(
        mto=target,
        mbody=body,
        mtype=message_type,
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

    stored_result = await _store_pending_room_invite(bot, room_jid, inviter, reason)
    if stored_result is None:
        return True
    if not stored_result.created:
        log.info("Ignoring duplicate room invite for %s from %s", room_jid, inviter)
        return True
    pending = stored_result.invite
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
    await _join_muc_with_timeout(bot, muc, room_jid, room_nick)

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
    usage=(
        "{prefix}rooms invite list [all|page|last] | "
        "{prefix}rooms invite accept <id> | "
        "{prefix}rooms invite decline <id> | "
        "{prefix}rooms invite cleanup [all|expired]"
    ),
    subcommands=[
        help_subcommand(
            "list",
            "{prefix}rooms invite list [all|page|last]",
            "List pending room invitations waiting for an admin decision.",
            aliases=("ls",),
            examples=[
                help_example(
                    "{prefix}rooms invite list",
                    "Show the first page of pending invitations.",
                )
            ],
        ),
        help_subcommand(
            "accept",
            "{prefix}rooms invite accept <id>",
            "Accept one pending invitation and join/store the room.",
            examples=[
                help_example(
                    "{prefix}rooms invite accept 1",
                    "Accept pending invitation 1.",
                )
            ],
        ),
        help_subcommand(
            "decline",
            "{prefix}rooms invite decline <id>",
            "Decline and remove one pending room invitation.",
            examples=[
                help_example(
                    "{prefix}rooms invite decline 1",
                    "Decline pending invitation 1.",
                )
            ],
        ),
        help_subcommand(
            "cleanup",
            "{prefix}rooms invite cleanup [all|expired]",
            "Remove all pending invites or only expired entries.",
            examples=[
                help_example(
                    "{prefix}rooms invite cleanup expired",
                    "Delete only expired pending invitations.",
                ),
                help_example(
                    "{prefix}rooms invite cleanup all",
                    "Delete every pending invitation.",
                ),
            ],
        ),
    ],
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
                    f"#{invite['id']} {invite['room_jid']} — invited by "
                    f"{invite['inviter']}{reason}"
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
        lines[0] = (
            f"✅ Accepted room invite #{invite_id}. Joined and stored {room_jid} "
            "with autojoin enabled."
        )
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
