"""Split module for core_plugins/rooms.py: commands."""

from utils.command import command, Role
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event
from utils.room_features import format_room_feature_line, list_room_features

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
    aliases=["room delete"],
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
    short="List stored rooms and currently joined rooms.",
    usage="{prefix}rooms list [all|page|last]",
    examples=[
        "{prefix}rooms list",
        "{prefix}rooms list all",
    ],
    category="rooms",
    context="private chat / MUC PM",
)
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
