"""Split module for core_plugins/rooms.py: commands."""

from utils.command import command, Role
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event
from utils.room_features import format_room_feature_line, list_room_features
from bot.room_state import joined_room_jids

from .defaults import _cleanup_room_plugin_state
from .presence import (
    _looks_like_room_jid,
    _resolve_room_settings_target,
    _room_is_known,
    is_valid_room_jid,
)
from .settings import _handle_room_feature_toggle, set_room_control_defaults
from .state import (
    JOINED_ROOMS,
    _LEAVING_ROOMS,
    _leave_runtime_room,
    _plugin_cleanup_changed,
    _room_diagnose_lines,
    _room_in_runtime_state,
    log,
)


_ROOM_LIST_MUC_SCOPES = {"muc", "room", "rooms"}
_ROOM_LIST_DM_SCOPES = {"dm", "1:1", "direct", "contacts"}


def _parse_rooms_list_args(args):
    """Return ``(scope, page_request)`` or ``None`` for invalid arguments."""
    remaining = [str(value).strip() for value in args]
    scope = "muc"
    if remaining and remaining[0].lower() in _ROOM_LIST_MUC_SCOPES:
        remaining.pop(0)
    elif remaining and remaining[0].lower() in _ROOM_LIST_DM_SCOPES:
        scope = "dm"
        remaining.pop(0)

    if len(remaining) > 1:
        return None
    if remaining and remaining[0].lower() not in {"all", "last"}:
        try:
            int(remaining[0])
        except ValueError:
            return None
    return scope, parse_page_args(remaining)


def _runtime_rooms(bot) -> dict[str, dict]:
    """Return one merged mapping of rooms tracked at runtime."""
    result = {
        str(room): {"nick": nick}
        for room, nick in (
            getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
        ).items()
    }
    for room, data in JOINED_ROOMS.items():
        result.setdefault(str(room), {}).update(data if isinstance(data, dict) else {})
    return result


def _muc_room_lines(bot, rows) -> tuple[list[str], int, int, int]:
    """Build a compact union of stored and currently joined MUCs."""
    stored = {
        str(room): {"nick": nick, "autojoin": bool(autojoin), "status": status}
        for room, nick, autojoin, status in rows
    }
    runtime = _runtime_rooms(bot)
    lines = []
    for room in sorted(set(stored) | set(runtime), key=str.casefold):
        saved = stored.get(room, {})
        live = runtime.get(room)
        values = live or {}
        fields = [
            f"nick={values.get('nick') or saved.get('nick') or 'unknown'}",
            f"autojoin={'yes' if saved.get('autojoin', values.get('autojoin', False)) else 'no'}",
        ]
        if live and values.get("affiliation"):
            fields.append(f"affiliation={values['affiliation']}")
        if live and values.get("role"):
            fields.append(f"role={values['role']}")
        if room not in stored:
            fields.append("stored=no")
        status = values.get("status", saved.get("status"))
        if status not in (None, "", "{}"):
            fields.append(f"status={status}")
        lines.append(f"• {'✅' if live is not None else '⚪'} {room} | " + " | ".join(fields))
    return lines, len(set(stored) | set(runtime)), len(stored), len(runtime)


def _roster_value(item, key: str, default=None):
    """Read one value from a Slixmpp roster item or a test mapping."""
    try:
        return item[key]
    except (KeyError, TypeError):
        return getattr(item, key, default)


def _direct_contact_lines(bot) -> tuple[list[str], int, int]:
    """Build compact lines for the bot's XMPP roster contacts."""
    roster = getattr(bot, "client_roster", None)
    if roster is None:
        return [], 0, 0

    own_jid = str(getattr(getattr(bot, "boundjid", None), "bare", "")).lower()
    muc_jids = joined_room_jids(bot, _runtime_rooms(bot))
    contacts = []
    for roster_jid in roster.keys():
        jid = str(getattr(roster_jid, "bare", roster_jid)).split("/", 1)[0]
        if not jid or jid.lower() == own_jid or jid.casefold() in muc_jids:
            continue
        item = roster[roster_jid]
        subscription = str(_roster_value(item, "subscription", "none") or "none")
        if subscription == "remove":
            continue
        resources = _roster_value(item, "resources", {}) or {}
        name = str(_roster_value(item, "name", "") or "").strip()
        pending = []
        if _roster_value(item, "pending_in", False):
            pending.append("in")
        if _roster_value(item, "pending_out", False):
            pending.append("out")
        contacts.append((jid, subscription, name, bool(resources), pending))

    contacts.sort(key=lambda item: item[0].casefold())
    lines = []
    for jid, subscription, name, online, pending in contacts:
        fields = [f"subscription={subscription}"]
        if name:
            fields.append(f"name={name}")
        if pending:
            fields.append(f"pending={','.join(pending)}")
        lines.append(f"• {'🟢' if online else '⚪'} {jid} | " + " | ".join(fields))
    return lines, len(contacts), sum(1 for item in contacts if item[3])


@command(
    "rooms plugins",
    role=Role.USER,
    aliases=[
        "room plugins",
        "rooms features",
        "room features",
        "rooms feature list",
        "room feature list",
        "rooms plugins list",
        "room plugins list",
        "rooms features list",
        "room features list",
    ],
    short="Show room plugin toggles; requires room admin/owner or bot moderator.",
    usage="{prefix}rooms plugins [<room_jid>] [all|page|last]",
    examples=[
        "{prefix}rooms plugins",
        "{prefix}rooms plugins all",
        "{prefix}rooms plugins room@conference.example.org all",
        "{prefix}help room settings",
        "{prefix}help rooms settings",
    ],
    category="rooms",
    context="room / MUC PM / private chat with <room_jid>",
)
async def cmd_room_plugins(bot, sender_jid, nick, args, msg, is_room):
    """Show plugin setup for a room."""
    usage = f"{bot.prefix}rooms plugins [<room_jid>] [all|page|last]"
    resolved = await _resolve_room_settings_target(
        bot, msg, is_room, args, sender_jid, usage
    )
    if resolved is None:
        return
    room_jid, remaining = resolved

    if remaining and str(remaining[0]).strip().lower() in {"list", "ls"}:
        remaining = remaining[1:]

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


@command(
    "rooms set_plugin_defaults",
    role=Role.USER,
    aliases=["room set_plugin_defaults", "rooms spd", "room spd"],
    short="Restore room plugin toggles for a room; requires room admin/owner or bot moderator.",
    usage="{prefix}rooms set_plugin_defaults [<room_jid>]",
    examples=[
        "{prefix}rooms set_plugin_defaults",
        "{prefix}rooms spd",
        "{prefix}rooms set_plugin_defaults room@conference.example.org",
    ],
    category="rooms",
    context="room / MUC PM / private chat with <room_jid>",
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


@command(
    "rooms diagnose",
    role=Role.ADMIN,
    aliases=["room diagnose", "rooms debug", "room debug"],
    short="Show operational diagnostics for one room.",
    usage="{prefix}rooms diagnose <room_jid>",
    examples=["{prefix}rooms diagnose room@conference.example.org"],
    category="rooms",
    context="private chat / MUC PM",
)
async def cmd_room_diagnose(bot, sender_jid, nick, args, msg, is_room):
    """Show diagnostics for one configured or joined room."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}rooms diagnose <room_jid>")
        return
    room_jid = str(args[0]).lower()
    if not _looks_like_room_jid(room_jid):
        bot.reply_error(msg, f"Invalid room JID: {room_jid}")
        return
    lines = await _room_diagnose_lines(bot, room_jid)
    bot.reply(msg, lines)


@command(
    "rooms enable",
    role=Role.USER,
    aliases=["room enable", "rooms feature enable", "room feature enable"],
    short="Enable a room plugin toggle; requires room admin/owner or bot moderator.",
    usage="{prefix}rooms enable [<room_jid>] <plugin>",
    examples=[
        "{prefix}rooms enable ducks",
        "{prefix}rooms enable room@conference.example.org ducks",
        "{prefix}rooms enable weather",
        "{prefix}help room settings",
    ],
    category="rooms",
    context="room / MUC PM / private chat with <room_jid>",
)
async def cmd_room_enable(bot, sender_jid, nick, args, msg, is_room):
    """Enable a room-scoped plugin for a room."""
    await _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, enabled=True)


@command(
    "rooms disable",
    role=Role.USER,
    aliases=["room disable", "rooms feature disable", "room feature disable"],
    short="Disable a room plugin toggle; requires room admin/owner or bot moderator.",
    usage="{prefix}rooms disable [<room_jid>] <plugin>",
    examples=[
        "{prefix}rooms disable ducks",
        "{prefix}rooms disable room@conference.example.org ducks",
        "{prefix}rooms disable xkcd",
    ],
    category="rooms",
    context="room / MUC PM / private chat with <room_jid>",
)
async def cmd_room_disable(bot, sender_jid, nick, args, msg, is_room):
    """Disable a room-scoped plugin for a room."""
    await _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, enabled=False)


@command(
    "rooms add",
    role=Role.ADMIN,
    aliases=["room add"],
    short="Add or update a stored room configuration.",
    usage="{prefix}rooms add <room_jid> [nick] [autojoin]",
    examples=["{prefix}rooms add test@conference.example.org EnvsBot true"],
    category="rooms",
    context="private chat / MUC PM",
)
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


@command(
    "rooms update",
    role=Role.ADMIN,
    aliases=["room update"],
    short="Update one field of a stored room.",
    usage="{prefix}rooms update <room_jid> <nick|autojoin|status> <value>",
    examples=["{prefix}rooms update test@conference.example.org autojoin true"],
    category="rooms",
    context="private chat / MUC PM",
)
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


@command(
    "rooms delete",
    role=Role.ADMIN,
    aliases=[
        "room delete",
        "rooms del",
        "room del",
        "rooms remove",
        "room remove",
        "rooms rm",
        "room rm",
    ],
    short="Remove a stored room and leave it if currently joined.",
    usage="{prefix}rooms delete <room_jid>",
    examples=["{prefix}rooms delete test@conference.example.org"],
    category="rooms",
    context="private chat / MUC PM",
)
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


@command(
    "rooms list",
    role=Role.ADMIN,
    aliases=["room list"],
    short="List MUC rooms or direct XMPP contacts.",
    usage="{prefix}rooms list [muc|dm|1:1] [<page>|last|all]",
    examples=[
        "{prefix}rooms list",
        "{prefix}rooms list all",
        "{prefix}rooms list dm",
        "{prefix}rooms list 1:1 all",
        "{prefix}rooms list direct",
        "{prefix}rooms list contacts all",
    ],
    category="rooms",
    context="private chat / MUC PM",
)
async def rooms_list(bot, sender_jid, nick, args, msg, is_room):
    """Show a merged MUC list or the bot's direct-contact roster."""
    parsed = _parse_rooms_list_args(args)
    if parsed is None:
        bot.reply_usage(
            msg,
            f"{bot.prefix}rooms list [muc|dm|1:1] [<page>|last|all]",
        )
        return
    scope, page = parsed

    if scope == "dm":
        contact_lines, contact_count, online_count = _direct_contact_lines(bot)
        details = [
            f"Direct contacts ({contact_count}): online={online_count}",
            "1:1 chats are not joined like MUCs; this lists XMPP roster contacts.",
        ]
        if contact_lines:
            details.extend(contact_lines)
        else:
            details.append("• none")
        title = "💬 Direct contacts"
        command_hint = f"{bot.prefix}rooms list dm"
    else:
        rows = await bot.db.rooms.list()
        room_lines, total_count, stored_count, joined_count = _muc_room_lines(bot, rows)
        details = [
            f"MUC rooms ({total_count}): stored={stored_count} | joined={joined_count}",
            "Legend: ✅ joined | ⚪ not joined",
        ]
        if room_lines:
            details.extend(room_lines)
        else:
            details.append("• none")
        title = "📋 Rooms"
        command_hint = f"{bot.prefix}rooms list"

    bot.reply(
        msg,
        format_page(
            title,
            details,
            page_request=page,
            page_size=12,
            command_hint=command_hint,
        ),
    )


@command(
    "rooms join",
    role=Role.ADMIN,
    aliases=["room join"],
    short="Join a room immediately and store it if needed.",
    usage="{prefix}rooms join <room_jid> [nick]",
    examples=["{prefix}rooms join test@conference.example.org"],
    category="rooms",
    context="private chat / MUC PM",
)
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


@command(
    "rooms leave",
    role=Role.ADMIN,
    aliases=["room leave"],
    short="Leave a room without deleting its stored configuration.",
    usage="{prefix}rooms leave <room_jid>",
    examples=["{prefix}rooms leave test@conference.example.org"],
    category="rooms",
    context="private chat / MUC PM",
)
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


@command(
    "rooms sync",
    role=Role.ADMIN,
    aliases=["room sync"],
    short="Synchronize joined rooms with stored autojoin settings.",
    usage="{prefix}rooms sync",
    examples=["{prefix}rooms sync"],
    category="rooms",
    context="private chat / MUC PM",
)
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
