from utils.time_utils import utc_now

"""Split module for core_plugins/users.py: tracking."""

import asyncio
from datetime import datetime
from functools import partial

from slixmpp import JID

from .lookup import _parse_user_jid
from .roles import MAX_ROOM_NICKS, log

_DIRECT_USERS_KEY = "_direct_users"
_ROOM_USERS_KEY = "_room_users"
_DELETED_USERS_KEY = "_deleted_users"


def _normalized_jid_set(value) -> set[str]:
    """Return a normalized set of bare JIDs from persisted source data."""
    if not isinstance(value, (list, tuple, set)):
        return set()
    result = set()
    for item in value:
        jid = _parse_user_jid(item)
        if jid:
            result.add(jid)
    return result


async def _update_persisted_jid_set(
    users,
    *,
    attr: str,
    key: str,
    jid: str,
    present: bool,
) -> set[str]:
    """Add or remove one JID from a persisted plugin-global set."""
    known = _normalized_jid_set(getattr(users, attr, set()) or set())
    if (jid in known) == present:
        return known

    def update(current):
        updated = _normalized_jid_set(current)
        if present:
            updated.add(jid)
        else:
            updated.discard(jid)
        return sorted(updated)

    persisted = await users.plugin("users").update_global(
        key,
        update,
        default=sorted(known),
    )
    result = _normalized_jid_set(persisted)
    setattr(users, attr, result)
    return result


async def _clear_user_deleted(bot, real_jid: str) -> None:
    """Allow a previously deleted user to reappear after new activity."""
    jid = _parse_user_jid(real_jid)
    if not jid:
        return
    await _update_persisted_jid_set(
        bot.db.users,
        attr="_deleted_users",
        key=_DELETED_USERS_KEY,
        jid=jid,
        present=False,
    )


async def _mark_user_deleted(bot, real_jid: str) -> None:
    """Forget source metadata and suppress stale roster/room observations."""
    jid = _parse_user_jid(real_jid)
    if not jid:
        return

    users = bot.db.users
    await _update_persisted_jid_set(
        users,
        attr="_direct_users",
        key=_DIRECT_USERS_KEY,
        jid=jid,
        present=False,
    )
    await _update_persisted_jid_set(
        users,
        attr="_room_users",
        key=_ROOM_USERS_KEY,
        jid=jid,
        present=False,
    )
    await _update_persisted_jid_set(
        users,
        attr="_deleted_users",
        key=_DELETED_USERS_KEY,
        jid=jid,
        present=True,
    )


async def _remember_user_source(bot, real_jid: str, source: str) -> None:
    """Persist whether a user was learned directly or from a room."""
    if source == "direct":
        attr = "_direct_users"
        key = _DIRECT_USERS_KEY
    elif source == "room":
        attr = "_room_users"
        key = _ROOM_USERS_KEY
    else:
        raise ValueError(f"Unsupported user source: {source}")

    users = bot.db.users
    await _clear_user_deleted(bot, real_jid)
    await _update_persisted_jid_set(
        users,
        attr=attr,
        key=key,
        jid=real_jid,
        present=True,
    )


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
    own_value = getattr(bound_jid, "bare", bound_jid)
    own_jid = _parse_user_jid(str(own_value)) if own_value else None
    if own_jid and real_jid == own_jid:
        return

    users = bot.db.users
    if await users.get(real_jid) is None:
        log.info("[USERS] ✅ Creating direct-message user: '%s'", real_jid)
        await users.create(real_jid)

    await _remember_user_source(bot, real_jid, "direct")
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

    bot.db.users._direct_users = _normalized_jid_set(
        await store.get_global(_DIRECT_USERS_KEY, [])
    )
    room_users = _normalized_jid_set(
        await store.get_global(_ROOM_USERS_KEY, [])
    )
    if not room_users:
        for jids in bot.db.users._nick_index.values():
            room_users.update(_normalized_jid_set(jids))
    bot.db.users._room_users = room_users
    bot.db.users._deleted_users = _normalized_jid_set(
        await store.get_global(_DELETED_USERS_KEY, [])
    )

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

    await _remember_user_source(bot, real_jid, "room")

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
    now = utc_now()

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
