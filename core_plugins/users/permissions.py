"""Split module for core_plugins/users.py: permissions."""

import logging
import asyncio
import inspect
from functools import partial
from datetime import datetime, timezone
from slixmpp import JID
from utils.config import config
from utils.command import command, Role, role_from_int
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event


def _owner_jid() -> str | None:
    """Return the configured owner JID as bare JID if it is valid."""
    owner = config.get("owner")
    if not owner:
        return None
    return _parse_user_jid(owner)


def _is_config_owner(jid: str) -> bool:
    """Return True if jid is the configured owner."""
    owner = _owner_jid()
    target = _parse_user_jid(jid)
    return bool(owner and target and owner == target)


async def _actor_role(bot, actor_jid: str) -> Role:
    """Resolve an actor role without room-based moderator elevation."""
    try:
        return await bot.get_user_role(actor_jid)
    except Exception:
        log.debug("[USERS] Could not resolve actor role", exc_info=True)
        return Role.NONE


def _role_from_user(user: dict | None) -> Role:
    """Return a safe stored user role, defaulting to USER for invalid rows."""
    if not user:
        return Role.USER
    try:
        role = role_from_int(int(user.get("role", Role.USER.value)))
    except Exception:
        return Role.USER

    # OWNER is intentionally config-only. NONE is an internal command-time
    # state for unknown users and must not be trusted as persisted data.
    if role in (Role.OWNER, Role.NONE):
        return Role.USER
    return role


def _role_label(role: Role) -> str:
    return role.name.lower()


def _available_role_names() -> str:
    """Return role names that may be assigned through the users command."""
    return ", ".join(ROLE_NAMES)


def _can_manage_roles(actor_role: Role) -> bool:
    """Return True for roles allowed to change/delete user records."""
    return actor_role <= Role.ADMIN


async def _can_change_role(bot, actor: str, target: str, target_role: Role, new_role: Role) -> tuple[bool, str]:
    """Validate role changes and prevent privilege mistakes."""
    actor_role = await _actor_role(bot, actor)
    if not _can_manage_roles(actor_role):
        return False, "⛔ You are not allowed to manage user roles."
    if _is_config_owner(target):
        return False, "⛔ The configured owner cannot be changed from the bot."
    if new_role not in ASSIGNABLE_ROLES:
        return False, "⛔ This role cannot be assigned from the bot."
    if target == actor:
        return False, "⛔ You cannot change your own role."
    if new_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can assign superadmin."
    if target_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can modify superadmin users."
    if target_role.value <= actor_role.value:
        return False, "⛔ You cannot modify users with equal or higher role."
    if new_role.value <= actor_role.value:
        return False, "⛔ You can only assign roles below your own role."
    return True, ""


async def _can_delete_user(bot, actor: str, target: str, target_role: Role) -> tuple[bool, str]:
    """Validate user deletion and prevent removing privileged accounts."""
    actor_role = await _actor_role(bot, actor)
    if not _can_manage_roles(actor_role):
        return False, "⛔ You are not allowed to delete users."
    if _is_config_owner(target):
        return False, "⛔ The configured owner cannot be deleted."
    if target == actor:
        return False, "⛔ You cannot delete your own user record."
    if target_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can delete superadmin users."
    if target_role.value <= actor_role.value:
        return False, "⛔ You cannot delete users with equal or higher role."
    return True, ""


def _grantable_plugin_names() -> str:
    """Return a human-readable list of plugin grants admins may assign."""
    return ", ".join(GRANTABLE_PLUGINS)


def _normalize_plugin_grants(value) -> list[str]:
    """Normalize stored plugin grant data to a sorted list."""
    if isinstance(value, dict):
        raw_names = [name for name, enabled in value.items() if enabled]
    elif isinstance(value, (list, tuple, set)):
        raw_names = list(value)
    elif isinstance(value, str):
        raw_names = [item for item in value.replace(",", " ").split()]
    else:
        raw_names = []

    valid, _invalid = _valid_plugin_names(raw_names)
    return sorted(valid)


async def get_user_plugin_grants(bot, jid: str) -> list[str]:
    """Return normalized plugin grants for a user JID."""
    bare_jid = _parse_user_jid(jid)
    if not bare_jid:
        return []

    try:
        store = bot.db.users.plugin("users")
        grants = await store.get(bare_jid, GRANTS_FIELD)
    except Exception:
        log.debug("[USERS] Could not read plugin grants for %s", bare_jid,
                  exc_info=True)
        return []

    return _normalize_plugin_grants(grants)


async def set_user_plugin_grants(bot, jid: str, grants: list[str]) -> None:
    """Persist plugin grants for a user JID."""
    bare_jid = _parse_user_jid(jid)
    if not bare_jid:
        raise ValueError("invalid user JID")

    valid, invalid = _valid_plugin_names(grants)
    if invalid:
        raise ValueError(f"invalid plugin grant(s): {', '.join(invalid)}")

    store = bot.db.users.plugin("users")
    await store.set(bare_jid, GRANTS_FIELD, sorted(valid))


async def user_has_plugin_grant(bot, jid: str, plugin: str) -> bool:
    """Return True when a user has the named room-scoped plugin grant."""
    plugin_name = _plugin_name(plugin)
    if plugin_name not in GRANTABLE_PLUGINS:
        return False
    return plugin_name in await get_user_plugin_grants(bot, jid)


def _bare_jid_from_affiliation_item(item) -> str | None:
    """Extract a bare JID from common MUC affiliation-list item shapes."""
    if item is None:
        return None

    if isinstance(item, dict):
        for key in ("jid", "bare", "value"):
            if item.get(key):
                return _parse_user_jid(item[key])

    for attr in ("jid", "bare"):
        value = getattr(item, attr, None)
        if value:
            return _parse_user_jid(value)

    get = getattr(item, "get", None)
    if callable(get):
        try:
            value = get("jid")
        except Exception:
            value = None
        if value:
            return _parse_user_jid(value)

    try:
        attrib = getattr(item, "attrib", None)
        if isinstance(attrib, dict) and attrib.get("jid"):
            return _parse_user_jid(attrib["jid"])
    except Exception:
        log.debug(
            "[USERS] Could not inspect affiliation item attributes",
            exc_info=True,
        )

    return _parse_user_jid(item)


def _normalize_affiliation_result(result) -> set[str]:
    """Normalize MUC affiliation query results to a set of bare JIDs."""
    if result is None:
        return set()

    if isinstance(result, dict):
        iterable = [*result.keys(), *result.values()]
    elif isinstance(result, (str, bytes)):
        iterable = [result]
    else:
        try:
            iterable = list(result)
        except TypeError:
            iterable = [result]

    jids = set()
    for item in iterable:
        bare = _bare_jid_from_affiliation_item(item)
        if bare:
            jids.add(bare)
    return jids


async def _query_affiliation_jids(bot, room_jid: str, affiliation: str) -> set[str]:
    """Query a room's MUC owner/admin affiliation list."""
    plugin_map = getattr(bot, "plugin", {}) or {}
    get_plugin = getattr(plugin_map, "get", None)
    muc = get_plugin("xep_0045", None) if callable(get_plugin) else None
    method = getattr(muc, "get_affiliation_list", None)
    if not callable(method):
        raise RuntimeError("XEP-0045 get_affiliation_list is unavailable")

    result = await _maybe_await(method(room_jid, affiliation))
    return _normalize_affiliation_result(result)


async def _live_room_affiliation_allows(bot, jid: str, room_jid: str) -> bool | None:
    """Return True/False from live MUC affiliation query, or None on failure."""
    queried = False
    had_error = False
    for affiliation in ("owner", "admin"):
        try:
            jids = await _query_affiliation_jids(bot, room_jid, affiliation)
            queried = True
        except Exception:
            had_error = True
            log.debug(
                "[USERS] Could not query %s affiliations for %s",
                affiliation,
                room_jid,
                exc_info=True,
            )
            continue
        if jid in jids:
            return True

    if not queried or had_error:
        return None
    return False


def _cached_room_affiliation_allows(jid: str, room_jid: str) -> bool:
    """Fallback owner/admin check using JOINED_ROOMS occupant cache."""
    try:
        from core_plugins.rooms import JOINED_ROOMS
        room_data = JOINED_ROOMS.get(room_jid, {}) or {}
        for occupant in (room_data.get("nicks", {}) or {}).values():
            occupant_jid = _parse_user_jid(occupant.get("jid"))
            affiliation = str(occupant.get("affiliation") or "").lower()
            if occupant_jid == jid and affiliation in {"admin", "owner"}:
                return True
    except Exception:
        log.debug("[USERS] Could not inspect cached room affiliations",
                  exc_info=True)
    return False


async def user_is_room_owner_or_admin(bot, jid: str, room_jid: str) -> bool:
    """Return True if jid is owner/admin in room by live query or cache."""
    bare_jid = _parse_user_jid(jid)
    room = str(room_jid or "").strip().lower()
    if not bare_jid or not room:
        return False

    live = await _live_room_affiliation_allows(bot, bare_jid, room)
    if live is not None:
        return live

    return _cached_room_affiliation_allows(bare_jid, room)


async def user_has_room_plugin_grant(
    bot,
    jid: str,
    plugin: str,
    room_jid: str,
) -> bool:
    """Return True for a plugin grant plus owner/admin affiliation in room."""
    bare_jid = _parse_user_jid(jid)
    if not bare_jid:
        return False
    if not await user_has_plugin_grant(bot, bare_jid, plugin):
        return False
    return await user_is_room_owner_or_admin(bot, bare_jid, room_jid)


@command("users roles", role=Role.ADMIN, aliases=["user roles"])
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


async def _validate_grant_change(bot, actor: str, target: str) -> tuple[bool, str, dict | None]:
    """Validate that actor may change plugin grants for target."""
    actor_jid = _parse_user_jid(actor)
    target_jid = _parse_user_jid(target)

    if not actor_jid or not target_jid:
        return False, "🟡️ Invalid user JID.", None

    actor_role = await _actor_role(bot, actor_jid)
    if not _can_manage_roles(actor_role):
        return False, "⛔ You are not allowed to manage plugin grants.", None

    if _is_config_owner(target_jid):
        return False, "⛔ The configured owner does not need plugin grants.", None
    if target_jid == actor_jid:
        return False, "⛔ You cannot change your own plugin grants.", None

    user = await bot.db.users.get(target_jid)
    if user is None:
        return False, f"🟡️ User not found: {target_jid}", None

    target_role = _role_from_user(user)
    if target_role == Role.SUPERADMIN and actor_role != Role.OWNER:
        return False, "⛔ Only the owner can modify superadmin users.", None
    if target_role.value <= actor_role.value:
        return False, "⛔ You cannot modify users with equal or higher role.", None

    return True, "", {"actor": actor_jid, "target": target_jid, "user": user}


async def _resolve_permission_target(bot, query: str) -> tuple[str | None, str]:
    """Resolve a permission target from bare JID or known nickname."""
    jid = _parse_user_jid(query)
    if jid:
        return jid, "jid"

    matches = await find_users_by_nick_safe(bot, query)
    if len(matches) == 1:
        return matches[0], "nick"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "missing"


async def _room_affiliation_status(bot, jid: str, room_jid: str) -> tuple[bool | None, str]:
    """Return room admin/owner status plus source label."""
    live = await _live_room_affiliation_allows(bot, jid, room_jid)
    if live is not None:
        return live, "live"
    cached = _cached_room_affiliation_allows(jid, room_jid)
    if cached:
        return True, "cache"
    return None, "unavailable"


def _can_manage_plugin_from_diagnostics(
    role: Role,
    grants: list[str],
    room_affiliation: bool | None,
    plugin: str,
) -> bool:
    """Return whether diagnostics predict room-scoped plugin access."""
    if role <= Role.MODERATOR:
        return True
    return bool(room_affiliation and plugin in grants)


@command(
    "users permissions",
    role=Role.ADMIN,
    aliases=["user permissions", "users perms", "user perms"],
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
    role = Role.OWNER if _is_config_owner(target) else _role_from_user(user)
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


@command("users admins", role=Role.ADMIN, aliases=["user admins", "users admin", "user admin"])
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
