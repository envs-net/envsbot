"""Split module for core_plugins/users.py: tracking."""

import asyncio
from functools import partial
from datetime import datetime, timezone
from slixmpp import JID

from .lookup import _parse_user_jid
from .roles import MAX_ROOM_NICKS, log


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

    # Filter our own presence
    if real_jid == bot.boundjid.bare:
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
    if real_jid == bot.boundjid.bare:
        return

    await update_last_seen(bot, real_jid)


def _is_muc_private_message(bot, msg) -> bool:
    """Return True when a chat message came from a joined room occupant."""
    checker = getattr(bot, "_is_muc_private_message", None)
    if callable(checker):
        try:
            return bool(checker(msg))
        except Exception:
            log.debug("[USERS] Could not classify private message", exc_info=True)

    try:
        sender = msg["from"]
    except Exception:
        sender = getattr(msg, "from", None)
    if sender is None:
        return False
    try:
        sender_bare = str(JID(sender).bare)
    except Exception:
        return False
    presence = getattr(bot, "presence", None)
    joined_rooms = getattr(presence, "joined_rooms", {}) or {}
    return sender_bare in joined_rooms


async def on_private_message(bot, msg):
    """Register and refresh users who contact the bot in a direct 1:1 chat."""
    try:
        msg_type = msg["type"]
    except Exception:
        msg_type = getattr(msg, "type", "")
    if str(msg_type or "").strip().lower() not in {"chat", "normal"}:
        return
    if _is_muc_private_message(bot, msg):
        return

    try:
        sender = msg["from"]
    except Exception:
        sender = getattr(msg, "from", None)
    try:
        real_jid = _parse_user_jid(sender)
    except Exception:
        real_jid = None
    if not real_jid:
        return

    bound_jid = getattr(bot, "boundjid", None)
    own_jid = _parse_user_jid(getattr(bound_jid, "bare", bound_jid))
    if own_jid and real_jid == own_jid:
        return

    users = bot.db.users
    if await users.get(real_jid) is None:
        log.info("[USERS] ✅ Creating direct-message user: '%s'", real_jid)
        await users.create(real_jid)

    await update_last_seen(bot, real_jid)


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
    bot.bot_plugins.register_runtime_event(
        "users",
        "private_message_received",
        partial(on_private_message, bot),
    )


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
