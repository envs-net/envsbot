"""
Room management and persistence.

This plugin provides administrative commands for managing XMPP
multi-user chat rooms stored in the bot database. Administrators
can add rooms, update their configuration, remove them, view the
current list of rooms, and control whether the bot joins or leaves
rooms at runtime.

Rooms can optionally be configured with an *autojoin* flag so the
bot automatically joins them when it starts.
"""

import asyncio
import logging

from functools import partial

from utils.command import command, Role
from utils.config import config

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "rooms",
    "version": "0.1.0",
    "description": "Database-backed room management",
    "category": "core",
}

# joined rooms module global
JOINED_ROOMS = {}


# -------------------------------------------------
# Event Handlers
# -------------------------------------------------

# Handlers
async def on_muc_presence(bot, pres):
    room = pres["from"].bare
    nick = pres["from"].resource
    role = pres["muc"].get("role")
    jid = pres["muc"].get("jid")
    affiliation = pres["muc"].get("affiliation")

    if jid is None:
        jid = pres["from"]

    jid_bare = str(jid.bare) if jid else None

    if room in JOINED_ROOMS:
        room_info = JOINED_ROOMS[room]
    else:
        room_info = {
            "nick": "unknown",
            "autojoin": "unknown",
            "status": None,
            "affiliation": "unknown",
            "role": "unknown",
            "nicks": {}
        }

    if pres["type"] == "unavailable":
        if JOINED_ROOMS.get(room) is None:
            return
        if nick == JOINED_ROOMS[room]["nick"]:
            del JOINED_ROOMS[room]
        else:
            del JOINED_ROOMS[room]["nicks"][nick]

    new_nick = room_info["nicks"].get(nick)
    if new_nick is None:
        new_nick = {
            "jid": jid_bare if jid is not None else str(pres["from"]),
            "affiliation":
                affiliation if affiliation is not None else "unknown",
            "role": role if role is not None else "unknown"
        }
    if affiliation is not None:
        new_nick["affiliation"] = affiliation
    if role is not None:
        new_nick["role"] = role

    room_info["nicks"][nick] = new_nick

    if jid_bare == bot.boundjid.bare:
        if affiliation is not None:
            if affiliation != room_info["affiliation"]:
                room_info["affiliation"] = affiliation
        if role != room_info["role"]:
            room_info["role"] = role
        if nick != room_info["nick"]:
            room_info["nick"] = nick

    JOINED_ROOMS[room] = room_info


# -------------------------------------------------
# ON_LOAD startup function (Module autoloadind)
# -------------------------------------------------

async def on_load(bot):

    # --- add event handlers ---
    bot.plugins.register_event(
        "rooms",
        "groupchat_presence",
        partial(on_muc_presence, bot))

    # Case 1: reload → restore previous runtime state
    reload_rooms = getattr(bot, "_reload_rooms", None)

    if reload_rooms is not None:
        del bot._reload_rooms

        for room, data in reload_rooms.items():
            # --- Get room data from DB ---
            db_room = await bot.db.rooms.get(room)
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

            autojoin = (data["autojoin"]
                        or db_autojoin
                        or None)

            status = (data["status"]
                      or db_status
                      or None)

            # --- rebuild runtime state ---
            JOINED_ROOMS[room] = {
                "nick": nick,
                "autojoin": autojoin,
                "status": status,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {}
            }

            await bot.plugin["xep_0045"].join_muc(
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
    # store current runtime state for reload
    bot._reload_rooms = dict(JOINED_ROOMS)

    for room_jid, data in JOINED_ROOMS.items():
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
        log.warning("[ROOMS] ⚠️ MUC discovery failed for %s: %s", domain, e)

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
            f"⚠️ Domain '{domain}' does not provide muc service.")
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
    muc = bot.plugin["xep_0045"]

    rows = await bot.db.rooms.list()
    for room_jid, nick, autojoin, status in rows:
        if not autojoin:
            continue
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
            log.exception(f"[ROOMS] ❌Couldn't join room '{room_jid}'")


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
            (f"⚠️ Usage: {bot.prefix}rooms add <room_jid>"
             " <nick> [autojoin]"),
            )
        return

    room_jid = args[0]
    room_nick = args[1]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"⚠️ Invalid room JID: {room_jid}"
        )
        log.warning(f"[ROOMS]⚠️ Room '{room_jid}' not valid!")
        return

    autojoin = len(args) >= 3 and args[2].lower() in ("true", "1", "yes")

    db_room = bot.db.rooms.get(room_jid)
    if not db_room:
        await bot.db.rooms.add(room_jid, room_nick, autojoin)

        log.info("[ROOMS] ➕ Added room %s nick=%s autojoin=%s",
                 room_jid, room_nick, autojoin)

    bot.reply(
        msg,
        f"✅ Room added: {room_jid}",
    )


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
            (f"⚠️ Usage: {bot.prefix}rooms update <room_jid>"
             f" <field> <value>"),
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"⚠️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS]⚠️Room '{room_jid}' not valid!")
        return

    field = args[1].lower()
    value = args[2]
    if field in ["nick", "autojoin"]:

        if field == "autojoin":
            value = value.lower() in ("true", "1", "yes")

        await bot.db.rooms.update(room_jid, **{field: value})

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
            f"⚠️ Usage: {bot.prefix}rooms delete <room_jid>",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"⚠️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS]⚠️Room '{room_jid}' not valid!")
        return

    try:
        if room_jid in await bot.db.rooms.list():
            await bot.db.rooms.delete(room_jid)

        joined = room_jid in JOINED_ROOMS

        if joined:

            bot.plugin["xep_0045"].leave_muc(room_jid, bot.boundjid.user)

            del JOINED_ROOMS[room_jid]

            if room_jid in bot.presence.joined_rooms:
                del bot.presence.joined_rooms[room_jid]

            bot.presence.broadcast()

            log.info("[ROOMS] 🚶 Left room %s", room_jid)

        log.info("[ROOMS] 🗑️ Deleted room %s", room_jid)

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
    """
    Show all rooms stored in the database, if they are autojoin or not.

    Command
    -------
    {prefix}rooms list
    """

    rows = await bot.db.rooms.list()

    if not rows:
        bot.reply(msg, "ℹ️ No rooms stored.")
        return

    header = f"{'ROOM':40} {'NICK':15} {'AUTOJOIN':8} {'JOINED':6} {'STATUS'}"
    lines = ["📋 Stored rooms", header, "-" * len(header)]

    for room_jid, nick_name, autojoin, status in rows:

        autojoin_flag = "yes" if autojoin else "no"
        joined_flag = "yes" if room_jid in JOINED_ROOMS else "no"

        lines.append(
            f"{room_jid:40} {nick_name:15} {autojoin_flag:8} {joined_flag:6}"
            f" {status}"
        )

    header = (f"{'ROOM':40} {'NICK':15} {'AFFILIATION':10} {'ROLE':10}"
              f" {'AUTOJOIN'}")
    lines += ["", "📋 JOINED rooms", header, "-" * len(header)]

    for room, data in JOINED_ROOMS.items():
        nick = data["nick"]
        affiliation = data["affiliation"]
        role = data["role"]
        autojoin = data["autojoin"]
        autojoin_flag = "yes" if autojoin else "no"

        lines.append(f"{room:40} {nick:15} {affiliation:10} {role:10}"
                     f" {autojoin_flag:8}")

    output = "\n".join(lines)
    bot.reply(msg, f"{output}")


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
            f"⚠️ Usage: {bot.prefix}rooms join <room_jid> [nick]",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"⚠️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS]⚠️Room '{room_jid}' not valid!")
        return

    if len(args) == 2:
        room_nick = args[1]
    else:
        room = await bot.db.rooms.get(room_jid)
        room_nick = room[1] if room else bot.boundjid.resource

    try:
        muc = bot.plugin["xep_0045"]

        await muc.join_muc(room_jid,
                           room_nick,
                           pshow=bot.presence.status["show"],
                           pstatus=bot.presence.status["status"])

        if room_jid not in JOINED_ROOMS:
            JOINED_ROOMS[room_jid] = {
                "nick": room_nick,
                "autojoin": False,
                "status": None,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {}
            }

        bot.presence.joined_rooms[room_jid] = room_nick
        bot.presence.broadcast()

        await bot.db.rooms.add(room_jid, room_nick, False)

        log.info("[ROOMS] 🚪 Joined room %s nick=%s", room_jid, room_nick)

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
            f"⚠️ Usage: {bot.prefix}rooms leave <room_jid>",
        )
        return

    room_jid = args[0]

    if not await is_valid_room_jid(bot, room_jid, msg):
        bot.reply(
            msg,
            f"⚠️ Invalid room JID: {room_jid}",
        )
        log.warning(f"[ROOMS]⚠️Room '{room_jid}' not valid!")
        return

    try:
        muc = bot.plugin["xep_0045"]
        muc.leave_muc(room_jid, bot.boundjid.user)

        # --- Delete room completely from JOINED_ROOMS --
        if room_jid in JOINED_ROOMS:
            del JOINED_ROOMS[room_jid]

        if room_jid in bot.presence.joined_rooms:
            del bot.presence.joined_rooms[room_jid]

        bot.presence.broadcast()

        log.info("[ROOMS] 🚶 Left room %s", room_jid)

        bot.reply(
            msg,
            f"🚶 Left room: {room_jid}",
        )

    except Exception:
        log.exception("[ROOMS] 🚶 Failed to leave room %s", room_jid)

        bot.replyy(
            msg,
            f"🚶 Failed to leave rooom: {room_jid}",
        )


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
    for room in list(JOINED_ROOMS.keys()):
        try:
            muc.leave_muc(room, JOINED_ROOMS[room]["nick"])
        except KeyError:
            log.debug(f"[ROOMS] rooms sync - Room already left: '{room}'")
        if room in bot.presence.joined_rooms:
            del bot.presence.joined_rooms[room]
        left.append(room)
    JOINED_ROOMS.clear()

    # Join only rooms from DB with autojoin=True
    for room_jid, nick_name, autojoin, status in rows:
        if autojoin:
            try:
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
