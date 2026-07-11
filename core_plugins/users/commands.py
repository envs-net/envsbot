"""Split module for core_plugins/users.py: commands."""

from slixmpp import JID
from utils.command import command, Role
from utils.formatting import format_page, parse_page_args
from .formatting import _audit_reason, _send_user_info, _write_user_audit
from .lookup import _parse_user_jid, _valid_plugin_names, find_users_by_nick_safe
from .permissions import (
    _available_role_names,
    _can_change_role,
    _can_delete_user,
    _grantable_plugin_names,
    _role_from_user,
    _role_label,
    _validate_grant_change,
    get_user_plugin_grants,
    set_user_plugin_grants,
)
from .roles import ROLE_NAMES, _command_prefix, log


@command(
    "users info",
    role=Role.ADMIN,
    aliases=["user info"],
    short="Show user info by JID or known nickname.",
    usage="{prefix}users info <jid|nick>",
    examples=["{prefix}users info alice@example.org"],
    category="users",
    context="private chat / MUC PM",
)
async def users_info(bot, sender, nick, args, msg, is_room):
    """
    Show user info by JID or nickname from 'users' database table.

    Usage:
        {prefix}users info <jid|nick>
    """
    try:
        if not args:
            log.warning("[USERS] 🟡️ users info without args")
            bot.reply(msg, f"🟡️ Usage: {_command_prefix(bot)}users info <jid|nick>")
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


@command(
    "users list",
    role=Role.ADMIN,
    aliases=["user list"],
    short="List users currently known in one joined room.",
    usage="{prefix}users list [room_jid] [all|page|last]",
    examples=[
        "{prefix}users list test@conference.example.org",
        "{prefix}users list test@conference.example.org 2",
    ],
    category="users",
    context="private chat only",
)
async def users_list(bot, sender, nick, args, msg, is_room):
    """
    List all users of a room. If no room JID is given, use the sender's bare
    JID (private chat context).

    Usage:
        {prefix}users list [room_jid] [all|page|last]
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

        # Determine room_jid and optional pagination.
        page_tokens = {"all", "last"}
        if args and (str(args[0]).lower() in page_tokens or str(args[0]).isdigit()):
            room_jid = msg["from"].bare
            page_args = args[:1]
        elif args:
            room_jid = args[0]
            page_args = args[1:2]
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
            page_args = []
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
        page_request = parse_page_args(page_args)

        log.info(
            "[USERS] 📋 Listed users for room: %s",
            room_jid
        )
        bot.reply(
            msg,
            "\n".join(format_page(
                f"📋 Users in {room_jid}:",
                lines,
                page_request=page_request,
                page_size=20,
                command_hint=f"{_command_prefix(bot)}users list {room_jid}",
            )),
        )

    except Exception:
        log.exception("[USERS] 🔴  users list failed")
        bot.reply(msg, "🟡️ Failed to list users.")


@command(
    "users role",
    role=Role.ADMIN,
    aliases=["user role"],
    short="Change a user's global bot role with hierarchy checks.",
    usage="{prefix}users role <jid> <role>",
    examples=["{prefix}users role alice@example.org trusted"],
    category="users",
    context="private chat / MUC PM",
)
async def users_update(bot, sender, nick, args, msg, is_room):
    """Update a user's role with owner/superadmin safety checks."""
    try:
        if len(args) != 2:
            log.warning("[USERS] 🟡️ users role wrong number of args")
            bot.reply_usage(msg, f"{_command_prefix(bot)}users role <jid> <role>")
            return

        actor = _parse_user_jid(sender)
        target = _parse_user_jid(args[0])
        if not actor or not target:
            await _write_user_audit(
                bot,
                "user_role_change_denied",
                actor=actor or str(sender),
                target=target or str(args[0]),
                details={"reason": "invalid_user_jid", "requested_role": str(args[1])},
            )
            bot.reply(msg, "🟡️ Invalid user JID.")
            return

        role_name = args[1].lower()
        if role_name not in ROLE_NAMES:
            await _write_user_audit(
                bot,
                "user_role_change_denied",
                actor=actor,
                target=target,
                details={"reason": "invalid_role", "requested_role": role_name},
            )
            bot.reply(msg, f"🟡️ Invalid role. Available: {_available_role_names()}")
            return

        new_role = ROLE_NAMES[role_name]
        um = bot.db.users
        target_user = await um.get(target)
        if not target_user:
            await _write_user_audit(
                bot,
                "user_role_change_denied",
                actor=actor,
                target=target,
                details={"reason": "user_not_found", "requested_role": _role_label(new_role)},
            )
            bot.reply(msg, f"🟡️ User not found: {target}")
            return

        old_role = _role_from_user(target_user)
        allowed, reason = await _can_change_role(bot, actor, target, old_role, new_role)
        if not allowed:
            await _write_user_audit(
                bot,
                "user_role_change_denied",
                actor=actor,
                target=target,
                details={
                    "reason": _audit_reason(reason),
                    "old_role": _role_label(old_role),
                    "requested_role": _role_label(new_role),
                },
            )
            bot.reply(msg, reason)
            return

        if old_role == new_role:
            await _write_user_audit(
                bot,
                "user_role_change_noop",
                actor=actor,
                target=target,
                details={"role": _role_label(new_role)},
            )
            bot.reply(msg, f"ℹ️ {target} already has role {_role_label(new_role)}.")
            return

        await um.set(target, "role", new_role.value)
        await _write_user_audit(
            bot,
            "user_role_changed",
            actor=actor,
            target=target,
            details={"old_role": _role_label(old_role), "new_role": _role_label(new_role)},
        )

        log.info("[USERS] 🔄 Role updated")
        bot.reply(msg, f"🔄 Updated role for {target}: {_role_label(old_role)} → {_role_label(new_role)}")

    except Exception:
        log.exception("[USERS] 🔴 users role failed")
        bot.reply(msg, "🟡️ Failed to update user.")


@command(
    "users revoke",
    role=Role.ADMIN,
    aliases=["user revoke", "users plugin revoke", "user plugin revoke"],
    short="Revoke room-scoped plugin permissions from a user.",
    usage="{prefix}users revoke <jid> <plugin> [plugin ...]",
    examples=["{prefix}users revoke alice@example.org rss"],
    category="users",
    context="private chat / MUC PM",
)
async def users_revoke(bot, sender, nick, args, msg, is_room):
    """Revoke one or more room-scoped plugin permissions from a user."""
    if len(args) < 2:
        bot.reply(
            msg,
            f"🟡️ Usage: {_command_prefix(bot)}users revoke <jid> <plugin> [plugin ...]",
        )
        return

    valid, invalid = _valid_plugin_names(args[1:])
    if invalid:
        bot.reply(
            msg,
            "🟡️ Invalid plugin grant(s): "
            f"{', '.join(invalid)}. Available: {_grantable_plugin_names()}",
        )
        return

    allowed, reason, context = await _validate_grant_change(bot, sender, args[0])
    if not allowed:
        bot.reply(msg, reason)
        return

    target = context["target"]
    current = set(await get_user_plugin_grants(bot, target))
    before = sorted(current)
    current.difference_update(valid)
    after = sorted(current)

    if before == after:
        bot.reply(msg, f"ℹ️ No matching plugin grants to revoke for {target}.")
        return

    await set_user_plugin_grants(bot, target, after)
    await _write_user_audit(
        bot,
        "user_plugin_grants_changed",
        actor=context["actor"],
        target=target,
        details={"old_grants": before, "new_grants": after, "removed": valid},
    )
    grants = ", ".join(after) if after else "none"
    bot.reply(msg, f"✅ Plugin grants for {target}: {grants}")


@command(
    "users delete",
    role=Role.ADMIN,
    aliases=["user delete"],
    short="Delete one non-privileged user record and its runtime data.",
    usage="{prefix}users delete <jid>",
    examples=["{prefix}users delete alice@example.org"],
    category="users",
    context="private chat / MUC PM",
)
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
            bot.reply(msg, f"🟡️ Usage: {_command_prefix(bot)}users delete <jid>")
            return

        actor = _parse_user_jid(sender)
        jid = _parse_user_jid(args[0])
        if not jid:
            log.warning("[USERS] 🟡️ Invalid JID for delete: %s", args[0])
            await _write_user_audit(
                bot,
                "user_delete_denied",
                actor=actor or str(sender),
                target=str(args[0]),
                details={"reason": "invalid_user_jid"},
            )
            bot.reply(msg, "🟡️ Invalid user JID.")
            return

        if not actor:
            await _write_user_audit(
                bot,
                "user_delete_denied",
                actor=str(sender),
                target=jid,
                details={"reason": "invalid_sender_jid"},
            )
            bot.reply(msg, "🟡️ Invalid sender JID.")
            return

        um = bot.db.users
        user = await um.get(jid)

        if not user:
            log.warning(f"[USERS] 🟡️ Delete failed, user not found: {jid}")
            await _write_user_audit(
                bot,
                "user_delete_denied",
                actor=actor,
                target=jid,
                details={"reason": "user_not_found"},
            )
            bot.reply(msg, f"🟡️ User not found: {jid}")
            return

        target_role = _role_from_user(user)
        allowed, reason = await _can_delete_user(bot, actor, jid, target_role)
        if not allowed:
            await _write_user_audit(
                bot,
                "user_delete_denied",
                actor=actor,
                target=jid,
                details={"reason": _audit_reason(reason), "role": _role_label(target_role)},
            )
            bot.reply(msg, reason)
            return

        await um.delete(jid)
        await _write_user_audit(
            bot,
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
