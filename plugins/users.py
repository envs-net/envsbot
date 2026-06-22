"""
Users plugin. Users are created automatically when the bot gets aware of them.
The default role is "USER".

Provides:
- User registration and management
- Last-seen tracking
- Nickname tracking per room (runtime via PluginRuntimeStore)
- Lookup by JID or nickname

Usage examples:
    {prefix}users info <jid|nick>
    {prefix}users list [room]
    {prefix}users role <jid> <role>
    {prefix}users delete <jid>
"""

import logging
import asyncio
from functools import partial
from datetime import datetime, timezone
from slixmpp import JID

from utils.config import config
from utils.command import command, Role, role_from_int
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event

log = logging.getLogger(__name__)

prefix = getattr(config, "prefix", ",")

MAX_ROOM_NICKS = config.get("users", {}).get("max_room_nicks", 5)

PLUGIN_META = {
    "name": "users",
    "version": "0.1.0",
    "description": "User management with caching, nick lookup and logging",
    "category": "core",
}


# ---------------------------------------------------------------------------
# Event Handles
# ---------------------------------------------------------------------------

async def on_muc_presence(bot, pres):
    if pres["type"] not in ("available", "unavailable"):
        return

    try:
        room = pres["muc"]["room"]
        nick = pres["muc"]["nick"]
    except KeyError:
        return

    # Check for real jid
    real_jid = pres["muc"].get("jid")

    # Return if no real JID
    if real_jid:
        real_jid = str(real_jid.bare)
    else:
        return

    # Filter our own messages
    bare_jid = str(JID(real_jid).bare)
    if bare_jid == bot.boundjid.bare:
        return

    if pres["type"] == "unavailable":
        await update_last_seen(bot, real_jid)
        return

    await asyncio.gather(
        track_room_nick(bot, real_jid, room, nick),
        update_last_seen(bot, real_jid),
    )


async def on_groupchat_message(bot, msg):
    try:
        room = msg["muc"]["room"]
        nick = msg["muc"]["nick"]
    except KeyError:
        return

    # Check Room Affiliation
    rooms_plugin = bot.bot_plugins.plugins.get("rooms")
    if not rooms_plugin:
        return
    if not rooms_plugin.bot_has_privilege(room):
        return

    # Check for real jid
    muc = bot.plugin.get("xep_0045", None)
    real_jid = None

    if muc:
        try:
            real_jid = muc.get_jid_property(room, nick, "jid")
        except Exception:
            real_jid = None

    # Return if no real JID
    if not real_jid:
        return
    real_jid = str(JID(real_jid).bare)

    # Filter our own messages
    if not real_jid:
        return
    if real_jid == bot.boundjid.bare:
        return

    await update_last_seen(bot, real_jid)


# ---------------------------------------------------------------------------
# ON_LOAD setup function
# ---------------------------------------------------------------------------

async def on_load(bot):
    """
    Initialize plugin and register MUC handlers.
    """
    # for integrity Unit Tests
    db = getattr(bot, "db", None)
    users_api = getattr(db, "users", None) if db else None

    if users_api is None or not hasattr(users_api, "plugin"):
        log.info("[USERS] on_load: skipped init (missing db.users)")
        return

    # --- initialize _nick_index on UserManager
    store = bot.db.users.plugin("users")
    bot.db.users._nick_index = await store.get_global("_nick_index", {})
    if bot.db.users._nick_index is None:
        bot.db.users._nick_index = {}

    # --- add event handlers ---
    bot.bot_plugins.register_event(
        "users",
        "groupchat_presence",
        partial(on_muc_presence, bot))
    bot.bot_plugins.register_event(
        "users",
        "groupchat_message",
        partial(on_groupchat_message, bot))


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

async def find_users_by_nick_safe(bot, nick: str):
    """
    Find users by nick using cache and fallback scan.
    """
    index = bot.db.users._nick_index
    return sorted(list(index.get(nick, [])))


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
        role = role_from_int(user["role"])

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


# ---------------------------------------------------------------------------
# RUNTIME
# ---------------------------------------------------------------------------

async def track_room_nick(bot, real_jid: str, room: str, nick: str):
    """
    Track nickname history per room using PluginRuntimeStore
    and maintain a global nick index for O(1) lookup.
    """
    um = bot.db.users
    if await um.get(real_jid) is None:
        log.info(f"[USERS] ✅ Creating user: '{real_jid}'")
        await um.create(real_jid, nick)

    store = um.plugin("users")

    # --- load current state ---
    roomnicks = await store.get(real_jid, "roomnicks") or {}

    nicks = roomnicks.get(room, [])

    # no-op if already most recent
    if nicks and nicks[0] == nick:
        return

    # reorder / insert nick
    if nick in nicks:
        nicks.remove(nick)

    nicks.insert(0, nick)
    roomnicks[room] = nicks[:MAX_ROOM_NICKS]

    await store.set(real_jid, "roomnicks", roomnicks)

    # collect all current nicks for this user
    new_nicks = [n for nicks in roomnicks.values() for n in nicks]
    new_nicks = list(dict.fromkeys(new_nicks))

    # --- maintain global index ---
    async with um._nick_index_lock:
        index = um._nick_index

        # 1. remove jid from all mappings
        for n, jids in tuple(index.items()):
            if real_jid in jids:
                filtered = [j for j in jids if j != real_jid]
                if filtered:
                    index[n] = filtered
                else:
                    del index[n]

        # 2. add jid to current nick set
        for n in new_nicks:
            jids = index.setdefault(n, [])
            if real_jid not in jids:
                jids.append(real_jid)

    log.debug(f"[USERS] 📝 Nick tracked: {real_jid} -> {room} = {nick}")


async def update_last_seen(bot, real_jid: str):
    """
    Update last_seen timestamp.
    """
    now = datetime.now(timezone.utc)

    try:
        user = await bot.db.users.get(real_jid)

        if user and user.get("last_seen"):
            try:
                last_seen = datetime.fromisoformat(user["last_seen"])
                if (now - last_seen).total_seconds() < 60:
                    return
            except Exception as exc:
                log.debug("[USERS] Could not parse last_seen for %s: %s", real_jid, exc)

        await bot.db.users.update_last_seen(real_jid)

        log.debug(f"[USERS] ⏱️ Updated last_seen: {real_jid}")

    except Exception:
        log.exception(f"[USERS] 🔴  Failed to update last_seen for {real_jid}")



def _is_config_owner(jid: str) -> bool:
    """Return True if jid is the configured owner."""
    try:
        return str(JID(config.get("owner", "")).bare) == str(JID(jid).bare)
    except Exception:
        return False


async def _actor_role(bot, actor_jid: str) -> Role:
    """Resolve an actor role without room-based moderator elevation."""
    try:
        return await bot.get_user_role(actor_jid)
    except Exception:
        log.debug("[USERS] Could not resolve actor role", exc_info=True)
        return Role.NONE


def _role_from_user(user: dict | None) -> Role:
    """Return a stored user role, defaulting to USER for missing rows."""
    if not user:
        return Role.USER
    try:
        return role_from_int(int(user.get("role", Role.USER.value)))
    except Exception:
        return Role.USER


def _role_label(role: Role) -> str:
    return role.name.lower()


async def _can_change_role(bot, actor: str, target: str, target_role: Role, new_role: Role) -> tuple[bool, str]:
    """Validate role changes and prevent privilege mistakes."""
    actor_role = await _actor_role(bot, actor)
    if _is_config_owner(target):
        return False, "⛔ The configured owner cannot be changed from the bot."
    if new_role == Role.OWNER:
        return False, "⛔ Owner can only be configured in config.py."
    if target == actor and new_role.value > actor_role.value:
        return False, "⛔ You cannot lower your own privileges."
    if target == actor and new_role.value < actor_role.value:
        return False, "⛔ You cannot raise your own role."
    if new_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can assign superadmin."
    if target_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can modify superadmin users."
    if target != actor and target_role.value <= actor_role.value:
        return False, "⛔ You cannot modify users with equal or higher role."
    if new_role.value < actor_role.value:
        return False, "⛔ You cannot assign a role higher than your own."
    return True, ""


async def _can_delete_user(bot, actor: str, target: str, target_role: Role) -> tuple[bool, str]:
    """Validate user deletion and prevent removing privileged accounts."""
    actor_role = await _actor_role(bot, actor)
    if _is_config_owner(target):
        return False, "⛔ The configured owner cannot be deleted."
    if target == actor:
        return False, "⛔ You cannot delete your own user record."
    if target_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can delete superadmin users."
    if target_role.value <= actor_role.value:
        return False, "⛔ You cannot delete users with equal or higher role."
    return True, ""

# ---------------------------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------------------------

@command("users info", role=Role.ADMIN, aliases=["user info"])
async def users_info(bot, sender, nick, args, msg, is_room):
    """
    Show user info by JID or nickname from 'users' database table.

    Usage:
        {prefix}users info <jid|nick>
    """
    try:
        if not args:
            log.warning("[USERS] 🟡️ users info without args")
            bot.reply(msg, f"🟡️ Usage: {prefix}users info <jid|nick>")
            return

        query = args[0]
        um = bot.db.users

        try:
            jid_query = str(JID(query).bare)
            user = await um.get(jid_query)
        except Exception:
            user = None

        if user:
            log.info(f"[USERS] 🔎 Info lookup by JID: {jid_query}")
            await _send_user_info(bot, msg, user)
            return

        jids = await find_users_by_nick_safe(bot, query)

        if not jids:
            log.warning(f"[USERS] 🟡️ No users found for nick: {query}")
            bot.reply(msg, f"🟡️ No users found for nick: {query}")
            return

        if len(jids) > 1:
            log.info(f"[USERS] 🔎 Multiple users for nick: {query}")
            lines = [f"🔎 Multiple users found for '{query}':"]
            for jid in jids:
                lines.append(f"- {jid}")
            bot.reply(msg, "\n".join(lines))
            return

        jid = next(iter(jids))
        user = await um.get(jid)

        if user is None:
            log.info(f"[USERS][INFO] 🔴  Unregistered user (jid={jid})")
            bot.reply(msg, "🔴  User is not registered.")
            return

        log.info(f"[USERS] 🔎 Info lookup by nick: {query} -> {jid}")
        await _send_user_info(bot, msg, user)

    except Exception:
        log.exception("[USERS] 🔴  users info failed")
        bot.reply(msg, "🟡️ Failed to fetch user info.")


@command("users list", role=Role.ADMIN, aliases=["user list"])
async def users_list(bot, sender, nick, args, msg, is_room):
    """
    List all users of a room. If no room JID is given, use the sender's bare
    JID (private chat context).

    Usage:
        {prefix}users list [room_jid]
    """
    try:
        # Import JOINED_ROOMS from rooms plugin
        rooms_plugin = bot.bot_plugins.plugins.get("rooms")
        if not rooms_plugin or not hasattr(rooms_plugin, "JOINED_ROOMS"):
            log.error(
                "[USERS] 🟡️ Rooms plugin not loaded or JOINED_ROOMS missing."
            )
            bot.reply(
                msg,
                "🟡️ Rooms plugin not loaded or JOINED_ROOMS missing."
            )
            return
        JOINED_ROOMS = rooms_plugin.JOINED_ROOMS

        if is_room:
            log.warning(
                "[USERS] 🚫 users_list called from a room,"
                " which is not allowed.",
            )
            bot.reply(
                msg,
                "🟡️ This command can only be used in a private chat"
                " with the bot.",
            )
            return

        # Determine room_jid
        if args:
            room_jid = args[0]
            if room_jid not in JOINED_ROOMS:
                log.warning(
                    "[USERS] 🚫 Room JID not found in JOINED_ROOMS: %s",
                    room_jid
                )
                bot.reply(
                    msg,
                    f"🟡️ Not joined to room: {room_jid}"
                )
                return
        else:
            room_jid = msg["from"].bare
            if room_jid not in JOINED_ROOMS:
                log.warning(
                    "[USERS] 🚫 Room JID not in JOINED_ROOMS: %s",
                    room_jid,
                )
                bot.reply(
                    msg,
                    f"🟡️ Not joined to room: {room_jid}"
                )
                return

        room_info = JOINED_ROOMS[room_jid]
        nicks = room_info.get("nicks", {})
        if not nicks:
            log.info(
                "[USERS] ℹ️ No users found in room: %s",
                room_jid
            )
            bot.reply(
                msg,
                f"ℹ️ No users found in room: {room_jid}"
            )
            return

        lines = []
        for nick, user_info in tuple(nicks.items()):
            jid = user_info.get("jid", "—")
            affiliation = user_info.get("affiliation", "—")
            role = user_info.get("role", "—")
            lines.append(
                f"[{affiliation}/{role}] {nick} ({jid})"
            )

        lines.sort()
        output = [f"📋 Users in {room_jid}:"] + lines

        log.info(
            "[USERS] 📋 Listed users for room: %s",
            room_jid
        )
        bot.reply(msg, "\n".join(output))

    except Exception:
        log.exception("[USERS] 🔴  users list failed")
        bot.reply(msg, "🟡️ Failed to list users.")


@command("users role", role=Role.ADMIN, aliases=["user role"])
async def users_update(bot, sender, nick, args, msg, is_room):
    """Update a user's role with owner/superadmin safety checks."""
    try:
        if len(args) != 2:
            log.warning("[USERS] 🟡️ users role wrong number of args")
            bot.reply_usage(msg, f"{prefix}users role <jid> <role>")
            return

        try:
            actor = str(JID(sender).bare)
            target = str(JID(args[0]).bare)
        except Exception:
            bot.reply(msg, "🟡️ Invalid JID.")
            return

        role_map = {role.name.lower(): role for role in Role}
        role_name = args[1].lower()
        if role_name not in role_map:
            bot.reply(msg, f"🟡️ Invalid role. Available: {', '.join(role_map)}")
            return

        new_role = role_map[role_name]
        um = bot.db.users
        target_user = await um.get(target)
        if not target_user:
            bot.reply(msg, f"🟡️ User not found: {target}")
            return

        old_role = _role_from_user(target_user)
        allowed, reason = await _can_change_role(bot, actor, target, old_role, new_role)
        if not allowed:
            bot.reply(msg, reason)
            return

        if old_role == new_role:
            bot.reply(msg, f"ℹ️ {target} already has role {_role_label(new_role)}.")
            return

        await um.set(target, "role", new_role.value)
        await audit_event(bot, 
            "user_role_changed",
            actor=actor,
            target=target,
            details={"old_role": _role_label(old_role), "new_role": _role_label(new_role)},
        )

        log.info("[USERS] 🔄 Role updated: %s %s -> %s", target, old_role, new_role)
        bot.reply(msg, f"🔄 Updated role for {target}: {_role_label(old_role)} → {_role_label(new_role)}")

    except Exception:
        log.exception("[USERS] 🔴 users role failed")
        bot.reply(msg, "🟡️ Failed to update user.")


@command("users roles", role=Role.ADMIN, aliases=["user roles"])
async def users_roles(bot, sender, nick, args, msg, is_room):
    """Show available roles and their ordering."""
    lines = [
        "👥 Roles",
        "Lower numbers have higher privileges.",
        "",
    ]
    for role in Role:
        lines.append(f"• {role.name.lower():10} = {role.value}")
    lines += [
        "",
        "Protection rules:",
        "• owner comes only from config.py",
        "• only owner can assign superadmin",
        "• users cannot promote themselves",
        "• users cannot modify/delete equal or higher roles",
    ]
    bot.reply(msg, lines)


@command("users admins", role=Role.ADMIN, aliases=["user admins", "users admin", "user admin"])
async def users_admins(bot, sender, nick, args, msg, is_room):
    """List users with admin-level roles."""
    users = await bot.db.users.list()
    page = parse_page_args(args)
    lines = []
    for user in users:
        role = role_from_int(int(user.get("role", Role.USER.value)))
        if role <= Role.ADMIN:
            lines.append(f"• {user['jid']} — {role.name.lower()}")

    owner = config.get("owner")
    if owner and not any(line.startswith(f"• {owner} ") for line in lines):
        lines.insert(0, f"• {owner} — owner (config)")

    bot.reply(
        msg,
        format_page(
            "👥 Admin users",
            lines,
            page_request=page,
            page_size=12,
            command_hint=f"{bot.prefix}users admins",
        ),
    )


@command("users delete", role=Role.ADMIN, aliases=["user delete"])
async def users_delete(bot, sender, nick, args, msg, is_room):
    """
    Delete a user. The user will be created again as soon as the bot gets aware
    of that user again. The user will start with a completely deleted runtime
    DB.

    Usage:
        {prefix}users delete <jid>
    """
    try:
        if not args:
            bot.reply(msg, f"🟡️ Usage: {prefix}users delete <jid>")
            return

        try:
            jid = str(JID(args[0]).bare)
        except Exception:
            log.warning(f"[USERS] 🟡️ Invalid JID for delete: {args[0]}")
            bot.reply(msg, "🟡️ Invalid JID.")
            return

        um = bot.db.users
        user = await um.get(jid)

        if not user:
            log.warning(f"[USERS] 🟡️ Delete failed, user not found: {jid}")
            bot.reply(msg, f"🟡️ User not found: {jid}")
            return

        actor = str(JID(sender).bare)
        target_role = _role_from_user(user)
        allowed, reason = await _can_delete_user(bot, actor, jid, target_role)
        if not allowed:
            bot.reply(msg, reason)
            return

        await um.delete(jid)
        await audit_event(bot, 
            "user_deleted",
            actor=actor,
            target=jid,
            details={"role": _role_label(target_role)},
        )

        log.info(f"[USERS] 🗑️ Deleted user: {jid}")
        bot.reply(msg, f"🗑️ Deleted: {jid}")

    except Exception:
        log.exception("[USERS] 🔴  users delete failed")
        bot.reply(msg, "🟡️ Failed to delete user.")
