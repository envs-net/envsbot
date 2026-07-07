"""Split module for core_plugins/rooms.py: lifecycle."""

from functools import partial
from utils.config import config


async def on_ready(bot):
    """Load pending room invites after the database is ready."""
    await load_pending_room_invites(bot)
    await cleanup_expired_room_invites(bot)


async def on_load(bot):

    # --- add event handlers ---
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_presence",
        partial(on_muc_presence, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "message",
        partial(on_room_invite_message, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_invite",
        partial(on_room_invite, bot))
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_direct_invite",
        partial(on_room_invite, bot))

    # get muc and rooms_db with guard
    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        log.warning("[ROOMS] 🟡️ missing dependencies: "
                    f"rooms_db={'OK' if rooms_db is not None else 'missing'} "
                    f"xep_0045={'OK' if muc is not None else 'missing'}")
        return

    # Case 1: reload → restore previous runtime state
    reload_rooms = getattr(bot, "_reload_rooms", None)

    if reload_rooms is not None:
        del bot._reload_rooms

        for room, data in tuple(reload_rooms.items()):
            # --- Get room data from DB ---
            db_room = await rooms_db.get(room)
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

            # Use runtime state if available, fallback to DB
            autojoin = data.get("autojoin")
            if autojoin is None:
                autojoin = db_autojoin

            status = data.get("status") or db_status or None

            # --- rebuild runtime state ---
            JOINED_ROOMS[room] = {
                "nick": nick,
                "autojoin": autojoin,
                "status": status,
                "affiliation": "unknown",
                "role": "unknown",
                "nicks": {}
            }

            await muc.join_muc(
                room,
                nick,
                pshow=bot.presence.status["show"],
                pstatus=bot.presence.status["status"]
            )

            bot.presence.joined_rooms[room] = nick
    else:
        # Case 2: normal startup → use config
        await autojoin_rooms(bot)


async def on_unload(bot):
    bot._reload_rooms = dict(JOINED_ROOMS)

    for room_jid, data in tuple(JOINED_ROOMS.items()):
        bot.plugin["xep_0045"].leave_muc(room_jid, data["nick"])

    bot.presence.joined_rooms.clear()
