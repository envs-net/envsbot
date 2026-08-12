"""Commands for inspecting and managing user permissions and grants."""

from utils.command import Role, command
from utils.formatting import format_page, parse_page_args

from .formatting import _write_user_audit, _yes_no
from .lookup import _parse_user_jid, _valid_plugin_names
from .permissions import (
    _can_manage_plugin_from_diagnostics,
    _grantable_plugin_names,
    _is_config_owner,
    _owner_jid,
    _resolve_permission_target,
    _role_from_user,
    _role_label,
    _room_affiliation_status,
    _validate_grant_change,
    get_user_plugin_grants,
    set_user_plugin_grants,
)
from .roles import ASSIGNABLE_ROLES, GRANTABLE_PLUGINS, _command_prefix


@command(
    "users roles",
    role=Role.ADMIN,
    aliases=["user roles"],
    short="Show available roles and their ordering.",
    usage="{prefix}users roles",
    examples=["{prefix}users roles"],
    category="users",
    context="private chat / MUC PM",
)
async def users_roles(bot, sender, nick, args, msg, is_room):
    """Show available roles and their ordering."""
    lines = [
        "👥 Roles",
        "Lower numbers have higher privileges.",
        "",
    ]
    lines.append(f"• {Role.OWNER.name.lower():10} = {Role.OWNER.value} (config-only)")
    for role in ASSIGNABLE_ROLES:
        lines.append(f"• {role.name.lower():10} = {role.value}")
    lines.append(f"• {Role.NONE.name.lower():10} = {Role.NONE.value} (internal only)")
    lines += [
        "",
        "Protection rules:",
        "• owner comes only from config.py",
        "• none is internal and cannot be assigned",
        "• only owner can assign or modify superadmin",
        "• users cannot change/delete themselves",
        "• users can only assign roles below their own role",
        "• users cannot modify/delete equal or higher roles",
    ]
    bot.reply(msg, lines)

@command(
    "users permissions",
    role=Role.ADMIN,
    aliases=["user permissions", "users perms", "user perms"],
    short="Diagnose global, room and room-scoped plugin permissions.",
    usage="{prefix}users permissions <jid|nick> [room_jid]",
    examples=[
        "{prefix}users permissions alice@example.org",
        "{prefix}users permissions alice@example.org room@conference.example.org",
        "{prefix}users perms alice room@conference.example.org",
    ],
    category="users",
    context="private chat / MUC PM",
)
async def users_permissions(bot, sender, nick, args, msg, is_room):
    """Show a user's effective bot and room-scoped plugin permissions."""
    if not args or len(args) > 2:
        bot.reply(
            msg,
            f"🟡️ Usage: {_command_prefix(bot)}users permissions <jid|nick> [room_jid]",
        )
        return

    target, source = await _resolve_permission_target(bot, args[0])
    if source == "ambiguous":
        bot.reply(msg, f"🟡️ Nick is ambiguous: {args[0]}")
        return
    if not target:
        bot.reply(msg, f"🟡️ User not found: {args[0]}")
        return

    user = await bot.db.users.get(target)
    is_owner = _is_config_owner(target)
    if user is None and not is_owner:
        bot.reply(msg, f"🟡️ User not found: {target}")
        return

    role = Role.OWNER if is_owner else _role_from_user(user)
    grants = await get_user_plugin_grants(bot, target)
    grants_text = ", ".join(grants) if grants else "none"

    lines = [
        "🔎 Permission diagnostics",
        f"User: {target}",
        f"Resolved by: {source}",
        f"Bot role: {_role_label(role)}",
        f"Plugin grants: {grants_text}",
    ]

    if len(args) == 2:
        room_jid = str(args[1]).strip().lower()
        room_affiliation, source_label = await _room_affiliation_status(
            bot,
            target,
            room_jid,
        )
        room_manage = bool(role <= Role.MODERATOR or room_affiliation)
        lines.extend([
            f"Room: {room_jid}",
            f"Room admin/owner: {_yes_no(room_affiliation)} ({source_label})",
            f"Can manage room settings: {_yes_no(room_manage)}",
            "Plugin access:",
        ])
        for plugin in GRANTABLE_PLUGINS:
            allowed = _can_manage_plugin_from_diagnostics(
                role,
                grants,
                room_affiliation,
                plugin,
            )
            reason = "global role" if role <= Role.MODERATOR else (
                "grant + room admin/owner" if allowed else "missing grant or room affiliation"
            )
            lines.append(f"• {plugin}: {_yes_no(allowed)} ({reason})")
    else:
        lines.extend([
            "Room: —",
            "Pass a room JID to include room affiliation and plugin access.",
        ])

    bot.reply(msg, "\n".join(lines))

@command(
    "users grant",
    role=Role.ADMIN,
    aliases=["user grant", "users plugin grant", "user plugin grant"],
    short="Grant room-scoped plugin permissions to a user.",
    usage="{prefix}users grant <jid> <plugin> [plugin ...]",
    examples=["{prefix}users grant alice@example.org rss pin poll"],
    category="users",
    context="private chat / MUC PM",
)
async def users_grant(bot, sender, nick, args, msg, is_room):
    """Grant one or more room-scoped plugin permissions to a user."""
    if len(args) < 2:
        bot.reply(
            msg,
            f"🟡️ Usage: {_command_prefix(bot)}users grant <jid> <plugin> [plugin ...]",
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
    if not valid:
        bot.reply(msg, f"🟡️ Available plugin grants: {_grantable_plugin_names()}")
        return

    allowed, reason, context = await _validate_grant_change(bot, sender, args[0])
    if not allowed:
        bot.reply(msg, reason)
        return
    if context is None:
        bot.reply(msg, "🔴 Could not resolve the target user.")
        return

    target = context["target"]
    current = set(await get_user_plugin_grants(bot, target))
    before = sorted(current)
    current.update(valid)
    after = sorted(current)

    if before == after:
        bot.reply(msg, f"ℹ️ {target} already has plugin grants: {', '.join(after)}")
        return

    await set_user_plugin_grants(bot, target, after)
    await _write_user_audit(
        bot,
        "user_plugin_grants_changed",
        actor=context["actor"],
        target=target,
        details={"old_grants": before, "new_grants": after, "added": valid},
    )
    bot.reply(msg, f"✅ Plugin grants for {target}: {', '.join(after)}")

@command(
    "users grants",
    role=Role.ADMIN,
    aliases=["user grants", "users plugin grants", "user plugin grants"],
    short="Show a user's room-scoped plugin permissions.",
    usage="{prefix}users grants <jid>",
    examples=["{prefix}users grants alice@example.org"],
    category="users",
    context="private chat / MUC PM",
)
async def users_grants(bot, sender, nick, args, msg, is_room):
    """Show room-scoped plugin permissions assigned to a user."""
    if len(args) != 1:
        bot.reply(msg, f"🟡️ Usage: {_command_prefix(bot)}users grants <jid>")
        return

    jid = _parse_user_jid(args[0])
    if not jid:
        bot.reply(msg, "🟡️ Invalid user JID.")
        return

    user = await bot.db.users.get(jid)
    if user is None:
        bot.reply(msg, f"🟡️ User not found: {jid}")
        return

    grants = await get_user_plugin_grants(bot, jid)
    value = ", ".join(grants) if grants else "none"
    bot.reply(msg, f"🔐 Plugin grants for {jid}: {value}")

@command(
    "users admins",
    role=Role.ADMIN,
    aliases=["user admins", "users admin", "user admin"],
    short="List users with admin-level roles.",
    usage="{prefix}users admins [all|page|last]",
    examples=["{prefix}users admins"],
    category="users",
    context="private chat / MUC PM",
)
async def users_admins(bot, sender, nick, args, msg, is_room):
    """List users with admin-level roles."""
    users = await bot.db.users.list()
    page = parse_page_args(args)
    lines = []
    for user in users:
        role = _role_from_user(user)
        if role <= Role.ADMIN:
            lines.append(f"• {user['jid']} — {role.name.lower()}")

    owner = _owner_jid()
    if owner and not any(line.startswith(f"• {owner} ") for line in lines):
        lines.insert(0, f"• {owner} — owner (config)")

    bot.reply(
        msg,
        format_page(
            "👥 Admin users",
            lines,
            page_request=page,
            page_size=12,
            command_hint=f"{_command_prefix(bot)}users admins",
        ),
    )
