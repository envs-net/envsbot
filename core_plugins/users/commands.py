"""Split module for core_plugins/users.py: commands."""

from utils.command import command, Role
from utils.formatting import format_page, parse_page_args
from bot.room_state import joined_room_jids
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
    role=Role.USER,
    aliases=["user info"],
    short="Show your user info, or inspect another user as an admin.",
    usage="{prefix}users info [jid|nick]",
    examples=[
        "{prefix}users info",
        "{prefix}users info alice@example.org",
    ],
    category="users",
    context="private chat / MUC PM",
)
async def users_info(bot, sender, nick, args, msg, is_room):
    """
    Show the caller's user info or, for admins, another user by JID/nickname.

    Usage:
        {prefix}users info [jid|nick]
    """
    try:
        if is_room:
            bot.reply(msg, "🟡️ Use this command in a private chat or MUC PM.")
            return
        if len(args) > 1:
            bot.reply(msg, f"🟡️ Usage: {_command_prefix(bot)}users info [jid|nick]")
            return

        actor = _parse_user_jid(sender)
        if not actor:
            bot.reply(msg, "🟡️ Could not resolve your user JID.")
            return

        query = args[0] if args else actor
        supplied_jid = _parse_user_jid(query)
        if args and supplied_jid != actor:
            actor_role = await bot.get_user_role(actor)
            if actor_role > Role.ADMIN:
                bot.reply(msg, "⛔ You may only view your own user info.")
                return

        um = bot.db.users
        target = None

        jid_query = supplied_jid
        user = await um.get(jid_query) if jid_query else None
        if user:
            target = jid_query

        if user and target == actor:
            log.info(f"[USERS] 🔎 Info lookup by JID: {jid_query}")
            await _send_user_info(bot, msg, user)
            return

        if not user and jid_query == actor:
            await um.create(actor)
            user = await um.get(actor)
            if user is None:
                user = {
                    "jid": actor,
                    "nickname": None,
                    "role": Role.USER.value,
                }
            await _send_user_info(bot, msg, user)
            return

        if not user and jid_query:
            log.warning(f"[USERS] 🟡️ User not found by JID: {jid_query}")
            bot.reply(msg, f"🟡️ User not found: {jid_query}")
            return

        if not user:
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

            target = next(iter(jids))
            user = await um.get(target)

        if user is None or not target:
            log.info(f"[USERS][INFO] 🔴  Unregistered user (jid={target})")
            bot.reply(msg, "🔴  User is not registered.")
            return

        log.info(f"[USERS] 🔎 Info lookup: {query} -> {target}")
        await _send_user_info(bot, msg, user)

    except Exception:
        log.exception("[USERS] 🔴  users info failed")
        bot.reply(msg, "🟡️ Failed to fetch user info.")


_USER_LIST_ACTIVE_SCOPES = {"active", "direct", "dm", "1:1"}
_USER_LIST_PASSIVE_SCOPES = {"passive", "room", "rooms", "muc"}
_USER_LIST_KNOWN_SCOPES = {"known", "stored", "other"}
_USER_LIST_PAGE_TOKENS = {"all", "last"}


def _parse_users_list_args(args):
    """Return ``(scope, room_jid, page_request)`` for ``users list``."""
    remaining = [str(value).strip() for value in args]
    scope = "all"
    room_jid = None

    if remaining:
        first = remaining[0].lower()
        if first in _USER_LIST_ACTIVE_SCOPES:
            scope = "active"
            remaining.pop(0)
        elif first in _USER_LIST_PASSIVE_SCOPES:
            scope = "passive"
            remaining.pop(0)
        elif first in _USER_LIST_KNOWN_SCOPES:
            scope = "known"
            remaining.pop(0)
        elif first not in _USER_LIST_PAGE_TOKENS and not first.isdigit():
            room_jid = remaining.pop(0)
            scope = "room"

    if len(remaining) > 1:
        return None
    if remaining and remaining[0].lower() not in _USER_LIST_PAGE_TOKENS:
        try:
            int(remaining[0])
        except ValueError:
            return None
    return scope, room_jid, parse_page_args(remaining)


def _user_roster_value(item, key: str, default=None):
    """Read one field from a Slixmpp roster item or a test mapping."""
    try:
        return item[key]
    except (KeyError, TypeError):
        return getattr(item, key, default)


def _direct_user_state(bot) -> dict[str, dict]:
    """Return direct users learned from messages and the current roster."""
    result = {
        jid: {"roster": False, "online": False, "name": ""}
        for jid in set(getattr(bot.db.users, "_direct_users", set()) or set())
    }
    roster = getattr(bot, "client_roster", None)
    if roster is None:
        return result

    own_jid = _parse_user_jid(getattr(getattr(bot, "boundjid", None), "bare", ""))
    for roster_jid in roster.keys():
        jid = _parse_user_jid(getattr(roster_jid, "bare", roster_jid))
        if not jid or jid == own_jid:
            continue
        item = roster[roster_jid]
        if str(_user_roster_value(item, "subscription", "none") or "none") == "remove":
            continue
        result[jid] = {
            "roster": True,
            "online": bool(_user_roster_value(item, "resources", {}) or {}),
            "name": str(_user_roster_value(item, "name", "") or "").strip(),
        }
    return result


def _room_user_state(joined_rooms) -> dict[str, dict]:
    """Return users currently visible in joined MUCs."""
    result = {}
    for room, room_info in (joined_rooms or {}).items():
        if not isinstance(room_info, dict):
            continue
        for nick, user_info in (room_info.get("nicks", {}) or {}).items():
            if not isinstance(user_info, dict):
                continue
            jid = _parse_user_jid(user_info.get("jid"))
            if not jid:
                continue
            state = result.setdefault(jid, {"rooms": set(), "nicks": set()})
            state["rooms"].add(str(room))
            if str(nick).strip():
                state["nicks"].add(str(nick).strip())
    return result


def _known_user_line(user, *, kind: str, direct=None, room=None) -> str:
    """Format one compact known-user line."""
    jid = str(user.get("jid") or "unknown")
    fields = [f"role={_role_label(_role_from_user(user))}"]
    nickname = str(user.get("nickname") or "").strip()
    if not nickname and direct:
        nickname = str(direct.get("name") or "").strip()
    if not nickname and room and room.get("nicks"):
        nickname = sorted(room["nicks"], key=str.casefold)[0]
    if nickname:
        fields.append(f"nick={nickname}")
    if kind == "active" and direct and direct.get("roster"):
        fields.append(f"online={'yes' if direct.get('online') else 'no'}")
    if room and room.get("rooms"):
        fields.append(f"rooms={len(room['rooms'])}")
    if not user.get("stored", True):
        fields.append("stored=no")
    icon = {"active": "💬", "passive": "👥", "known": "⚪"}[kind]
    return f"• {icon} {jid} | " + " | ".join(fields)


def _known_user_sections(bot, users, joined_rooms, scope: str):
    """Build categorized lines for all users known to the bot."""
    users_by_jid = {
        str(user.get("jid")): {**user, "stored": True}
        for user in users
        if user.get("jid") and str(user.get("jid")) != "__GLOBAL__"
    }
    direct_state = _direct_user_state(bot)
    room_state = _room_user_state(joined_rooms)
    historic_room_users = set(getattr(bot.db.users, "_room_users", set()) or set())
    muc_jids = joined_room_jids(bot, joined_rooms)

    direct_state = {
        jid: state
        for jid, state in direct_state.items()
        if jid.casefold() not in muc_jids
    }
    room_state = {
        jid: state
        for jid, state in room_state.items()
        if jid.casefold() not in muc_jids
    }
    historic_room_users = {
        jid for jid in historic_room_users if str(jid).casefold() not in muc_jids
    }

    roster_jids = {
        jid for jid, state in direct_state.items() if state.get("roster")
    }
    all_jids = set(users_by_jid) | roster_jids | set(room_state)
    all_jids = {jid for jid in all_jids if jid.casefold() not in muc_jids}
    own_jid = _parse_user_jid(getattr(getattr(bot, "boundjid", None), "bare", ""))
    if own_jid:
        all_jids.discard(own_jid)

    active_jids = set(direct_state) & all_jids
    passive_jids = (
        (set(room_state) | (historic_room_users & set(users_by_jid))) & all_jids
    ) - active_jids
    known_jids = all_jids - active_jids - passive_jids

    def rows_for(jids, kind):
        rows = []
        for jid in jids:
            user = users_by_jid.get(jid, {"jid": jid, "stored": False})
            rows.append((
                int(_role_from_user(user)),
                jid.casefold(),
                _known_user_line(
                    user,
                    kind=kind,
                    direct=direct_state.get(jid),
                    room=room_state.get(jid),
                ),
            ))
        return [row[2] for row in sorted(rows)]

    groups = {
        "active": rows_for(active_jids, "active"),
        "passive": rows_for(passive_jids, "passive"),
        "known": rows_for(known_jids, "known"),
    }
    counts = {name: len(lines) for name, lines in groups.items()}

    if scope != "all":
        labels = {
            "active": "Active/direct users",
            "passive": "Passive/room users",
            "known": "Stored-only users",
        }
        lines = [f"{labels[scope]} ({counts[scope]}):"]
        lines.extend(groups[scope] or ["• none"])
        return lines, counts

    lines = [
        (
            f"Known users ({sum(counts.values())}): active={counts['active']} | "
            f"passive={counts['passive']} | stored-only={counts['known']}"
        ),
        "Legend: 💬 active/direct | 👥 passive/room | ⚪ stored only",
        "",
        f"Active/direct users ({counts['active']}):",
        *(groups["active"] or ["• none"]),
        "",
        f"Passive/room users ({counts['passive']}):",
        *(groups["passive"] or ["• none"]),
    ]
    if counts["known"]:
        lines.extend([
            "",
            f"Stored-only users ({counts['known']}):",
            *groups["known"],
        ])
    return lines, counts


async def _list_room_users(bot, msg, room_jid: str, page_request) -> None:
    """Keep the detailed per-room occupant list for explicit room queries."""
    rooms_plugin = bot.bot_plugins.plugins.get("rooms")
    joined_rooms = getattr(rooms_plugin, "JOINED_ROOMS", None) if rooms_plugin else None
    if joined_rooms is None:
        bot.reply(msg, "🟡️ Rooms plugin not loaded or JOINED_ROOMS missing.")
        return
    if room_jid not in joined_rooms:
        bot.reply(msg, f"🟡️ Not joined to room: {room_jid}")
        return

    nicks = joined_rooms[room_jid].get("nicks", {})
    if not nicks:
        bot.reply(msg, f"ℹ️ No users found in room: {room_jid}")
        return

    lines = []
    for room_nick, user_info in tuple(nicks.items()):
        jid = user_info.get("jid", "—")
        affiliation = user_info.get("affiliation", "—")
        role = user_info.get("role", "—")
        lines.append(f"[{affiliation}/{role}] {room_nick} ({jid})")
    lines.sort()
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


@command(
    "users list",
    role=Role.ADMIN,
    aliases=["user list"],
    short="List known users by direct, room-observed or stored-only source.",
    usage="{prefix}users list [active|passive|known|room_jid] [all|page|last]",
    examples=[
        "{prefix}users list",
        "{prefix}users list active",
        "{prefix}users list passive all",
        "{prefix}users list test@conference.example.org 2",
    ],
    category="users",
    context="private chat only",
)
async def users_list(bot, sender, nick, args, msg, is_room):
    """List all known users, or current occupants of one explicit room."""
    try:
        if is_room:
            bot.reply(msg, "🟡️ This command can only be used in a private chat with the bot.")
            return

        parsed = _parse_users_list_args(args)
        if parsed is None:
            bot.reply_usage(
                msg,
                (
                    f"{_command_prefix(bot)}users list "
                    "[active|passive|known|room_jid] [all|page|last]"
                ),
            )
            return
        scope, room_jid, page_request = parsed

        if scope == "room":
            await _list_room_users(bot, msg, room_jid, page_request)
            return

        users = await bot.db.users.list()
        rooms_plugin = bot.bot_plugins.plugins.get("rooms")
        joined_rooms = getattr(rooms_plugin, "JOINED_ROOMS", {}) if rooms_plugin else {}
        lines, _counts = _known_user_sections(bot, users, joined_rooms, scope)
        command_hint = f"{_command_prefix(bot)}users list"
        if scope != "all":
            command_hint += f" {scope}"
        bot.reply(
            msg,
            "\n".join(format_page(
                "👥 Known users",
                lines,
                page_request=page_request,
                page_size=20,
                command_hint=command_hint,
            )),
        )
    except Exception:
        log.exception("[USERS] 🔴  users list failed")
        bot.reply(msg, "🟡️ Failed to list users.")


@command(
    "users role",
    role=Role.ADMIN,
    aliases=["user role"],
    short="Create or change a user's global bot role with hierarchy checks.",
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
        created = target_user is None
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

        if created:
            await um.create(target)

        if old_role == new_role:
            await _write_user_audit(
                bot,
                "user_role_changed" if created else "user_role_change_noop",
                actor=actor,
                target=target,
                details=(
                    {
                        "old_role": _role_label(old_role),
                        "new_role": _role_label(new_role),
                        "created": True,
                    }
                    if created
                    else {"role": _role_label(new_role)}
                ),
            )
            if created:
                bot.reply(msg, f"✅ Created user {target} with role {_role_label(new_role)}.")
            else:
                bot.reply(msg, f"ℹ️ {target} already has role {_role_label(new_role)}.")
            return

        await um.set(target, "role", new_role.value)
        await _write_user_audit(
            bot,
            "user_role_changed",
            actor=actor,
            target=target,
            details={
                "old_role": _role_label(old_role),
                "new_role": _role_label(new_role),
                **({"created": True} if created else {}),
            },
        )

        log.info("[USERS] 🔄 Role updated")
        if created:
            bot.reply(msg, f"✅ Created user {target} with role {_role_label(new_role)}.")
        else:
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
