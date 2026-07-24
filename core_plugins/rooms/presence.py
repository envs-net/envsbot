"""Split module for core_plugins/rooms.py: presence."""

import asyncio
import inspect

from .state import JOINED_ROOMS, _LEAVING_ROOMS, _jid_bare, log
from .permissions import _sender_can_manage_room_settings


def _looks_like_room_jid(value: object) -> bool:
    """Return True if a value looks like a bare MUC JID argument."""
    raw = str(value or "").strip()
    room_jid = _jid_bare(raw)
    if not raw or "/" in raw or "@" not in room_jid:
        return False
    node, domain = room_jid.split("@", 1)
    return bool(node and domain)


def _message_context_room(msg, is_room: bool) -> str:
    """Return the implicit room for public room messages or MUC PMs."""
    try:
        from_jid = msg["from"]
        room_jid = _jid_bare(from_jid)
        nick = getattr(from_jid, "resource", None)
    except Exception:
        return ""

    if is_room:
        return room_jid
    if nick and room_jid in JOINED_ROOMS:
        return room_jid
    return ""


async def _room_is_known(bot, room_jid: str) -> bool:
    """Return True if the room is joined or stored in the room database."""
    if room_jid in JOINED_ROOMS:
        return True
    rooms_db = getattr(getattr(bot, "db", None), "rooms", None)
    get_room = getattr(rooms_db, "get", None)
    if not callable(get_room):
        return False
    try:
        result = get_room(room_jid)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)
    except Exception:
        log.debug("[ROOMS] Could not look up room %s", room_jid, exc_info=True)
        return False


async def _resolve_room_settings_target(bot, msg, is_room: bool, args: list[str], sender_jid: str, usage: str):
    """Resolve and authorize the target room for room setting commands."""
    remaining = list(args)
    explicit = False
    if remaining and _looks_like_room_jid(remaining[0]):
        room_jid = _jid_bare(remaining.pop(0))
        explicit = True
    else:
        room_jid = _message_context_room(msg, is_room)

    if not room_jid:
        bot.reply_usage(msg, usage)
        bot.reply_info(
            msg,
            "Use a MUC PM, run the command in the room, or pass <room_jid> when using a normal DM/admin room.",
        )
        return None

    if not explicit and not is_room and room_jid not in JOINED_ROOMS:
        bot.reply_error(msg, "This command can only infer a room from MUC PMs or room messages.")
        return None

    if not await _room_is_known(bot, room_jid):
        bot.reply_error(msg, f"Room '{room_jid}' is not currently joined or stored.")
        return None

    if not await _sender_can_manage_room_settings(bot, sender_jid, room_jid):
        bot.reply_error(
            msg,
            f"Only room admins/owners or bot moderators can manage room settings for '{room_jid}'.",
        )
        return None

    return room_jid, remaining


def is_nick_change(pres):
    # Looks for <status code="303"/> (nick change)
    search = './/{http://jabber.org/protocol/muc#user}status'
    for stat in pres.xml.findall(search):
        if stat.attrib.get("code") == "303":
            return True
    return False


async def on_muc_presence(bot, pres):
    try:
        room = pres["from"].bare
        nick = pres["from"].resource
        role = pres["muc"].get("role")
        jid = pres["muc"].get("jid")
        affiliation = pres["muc"].get("affiliation")
        jid_bare = str(jid.bare) if jid else None

        if room in _LEAVING_ROOMS and room not in JOINED_ROOMS:
            log.debug(
                "[ROOMS] Ignoring stale presence for intentionally left room %s",
                room,
            )
            return

        room_info = JOINED_ROOMS.setdefault(room, {
            "nick": "unknown", "autojoin": "unknown", "status": None,
            "affiliation": "unknown", "role": "unknown", "nicks": {}
        })

        nicks = room_info["nicks"]

        # --- Handle nick changes: remove old, add new ---
        if is_nick_change(pres) and pres["type"] == "unavailable":
            old_nick = nick
            if old_nick in nicks:
                del nicks[old_nick]
            log.debug(f"[ROOMS] Removed old nick due to nick change: {
                      old_nick} from {room}")
            return  # Don't re-add, handled by new presence

        # --- Handle leaves/disconnects/kicks/bans ---
        if pres["type"] == "unavailable":
            if nick in nicks:
                del nicks[nick]
                log.debug(f"[ROOMS] Removed nick {nick} from {room}")
            # If the bot itself left the room, remove both runtime mirrors.
            if nick == room_info.get("nick"):
                JOINED_ROOMS.pop(room, None)
                presence_rooms = getattr(
                    getattr(bot, "presence", None), "joined_rooms", None
                )
                if isinstance(presence_rooms, dict):
                    presence_rooms.pop(room, None)
                log.info(f"[ROOMS] Bot left room {
                         room}, cleaned up room state.")
            return

        # --- Else: presence update or join (available) ---
        affiliation = affiliation if affiliation is not None else "unknown"
        previous = nicks.get(nick, {}) if isinstance(nicks.get(nick, {}), dict) else {}
        resolved_jid = jid_bare or previous.get("jid")
        nicks[nick] = {
            # Some MUC presence updates do not include the real occupant JID.
            # Keep an existing real JID instead of replacing it with the
            # occupant JID (room@conference/nick), which is not stable and
            # breaks plugins that need to map messages back to registered users.
            "jid": resolved_jid,
            "affiliation": affiliation,
            "role": role if role is not None else "unknown"
        }

        # Update bot's own state in room_info if relevant. The detailed
        # JOINED_ROOMS mapping is the primary MUC state, while
        # PresenceManager.joined_rooms is still used for routing, MUC-PM
        # context and directed presence broadcasts. Refresh both from the
        # authoritative self-presence so missing state heals automatically.
        if jid_bare == bot.boundjid.bare:
            if affiliation is not None:
                room_info["affiliation"] = affiliation
            if role is not None:
                room_info["role"] = role
            if nick != room_info["nick"]:
                room_info["nick"] = nick
            presence_rooms = getattr(
                getattr(bot, "presence", None), "joined_rooms", None
            )
            if isinstance(presence_rooms, dict):
                presence_rooms[room] = nick

        JOINED_ROOMS[room] = room_info

    except Exception as e:
        log.exception(f"[ROOMS] Error in on_muc_presence: {e}")


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
        log.warning("[ROOMS] 🟡️ MUC discovery failed for %s: %s", domain, e)

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
            f"🟡️ Domain '{domain}' does not provide muc service.")
        return False
    return True
