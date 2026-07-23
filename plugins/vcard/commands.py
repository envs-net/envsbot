"""Split module for plugins/vcard.py: commands."""

import datetime
from core_plugins import _core
from utils.command import command, Role
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.config import config
from bot.room_state import JOINED_ROOMS
from .config import VCARD_KEY, log
from .fetch import get_info, get_vcard
from .fields import _get_vcard_field
from .formatting import _format_vcard_reply
from .store import get_vcard_store
from .timezone import _get_vcard_timezone


















async def _resolve_vcard_target(bot, msg, args, is_room, enabled_rooms):
    """Resolve lookup target for room/PM/DM contexts.

    Returns:
        (jid, target_nick, muc_jid) or (None, None, None) if command should
        stop.
    """
    in_room_context = is_room or _core._is_muc_pm(msg)

    if in_room_context and args:
        target_nick = " ".join(args).strip()
        muc_jid = f"{msg['from'].bare}"
        if muc_jid not in enabled_rooms:
            return None, None, None

        joined = JOINED_ROOMS.get(muc_jid, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return None, None, None

        jid = nick_info.get("jid")
        if not jid:
            bot.reply(msg, "🔴  Could not resolve JID for nick"
                           f" '{target_nick}'.")
            return None, None, None

        return jid, target_nick, muc_jid

    if in_room_context and not args:
        target_nick = msg["from"].resource
        muc_jid = f"{msg['from'].bare}"
        if muc_jid not in enabled_rooms:
            return None, None, None

        joined = JOINED_ROOMS.get(muc_jid, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Your Nick '{target_nick}' not found"
                           " in this room.")
            return None, None, None

        jid = nick_info.get("jid")
        if not jid:
            bot.reply(msg, "🔴  Could not resolve your JID for"
                           f" nick '{target_nick}'.")
            return None, None, None

        return jid, target_nick, muc_jid

    # DM context
    if args:
        log.info(f"[VCARD] Direct message with args from '{msg['from'].bare}'")
        bot.reply(
            msg,
            "🔴  In direct messages, you can only look up your own vCard."
            " Use the command without args.",
        )
        return None, None, None

    jid = msg["from"].bare
    return jid, jid, "Direct Message"


@command(
    "vcard",
    role=Role.USER,
    aliases=["v"],
    short="Show vCard data or control room access to vCard lookups.",
    usage="{prefix}vcard [on|off|status|nick]",
    subcommands=[
        help_subcommand(
            "<nick>",
            "{prefix}vcard [nick]",
            "Show your own vCard or look up a room user's vCard by nickname.",
            examples=[
                help_example("{prefix}vcard", "Show your own vCard in a direct chat."),
                help_example("{prefix}vcard Alice", "Show Alice's vCard in a shared room."),
            ],
        ),
        *room_toggle_subcommands("vcard", "vCard lookups"),
    ],
    examples=[
        "{prefix}vcard",
        "{prefix}vcard status",
        "{prefix}rooms enable vcard",
    ],
    category="profile",
    context="any",
)
async def vcard_command(bot, sender_jid, sender_nick, args, msg, is_room):
    """
    Look up the vCard of a user by MUC nick (MUC JID only), never real JID!

    Usage: {prefix}vcard [<nick>|on|off|status]

    IMPORTANT: You may have to activate the vcard commands if not activated
    by default with the command:
        {prefix}vcard on

    Usage:
        {prefix}vcard on|off|status
            - Enable, disable or check status of vCard commands in this room.
        {prefix}vcard [nick]
            - Look up the vCard of a user by their MUC nickname in this room.
              or omit the nick for your own vCard

    """
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    in_room_context = is_room or _core._is_muc_pm(msg)

    if msg["from"].bare not in enabled_rooms and in_room_context:
        return

    if in_room_context:
        handled = await _core.handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_vcard_store,
            key=VCARD_KEY,
            label="Get vCard data",
            plugin="vcard",
            storage="dict",
            log_prefix="[VCARD]",
        )
        if handled:
            return

    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")

    jid, target_nick, muc_jid = await _resolve_vcard_target(
        bot, msg, args, is_room, enabled_rooms
    )
    if jid is None:
        return

    try:
        vcard_info = await get_vcard(bot, msg, jid=jid)

        if not vcard_info:
            bot.reply(msg, f"ℹ️ No vCard found for {target_nick} ({muc_jid}).")
            log.info(f"[VCARD] No vCard found for '{target_nick}' ({muc_jid})")
            return

        lines, vcard = _format_vcard_reply(vcard_info, target_nick, muc_jid)

        timezone = await _get_vcard_timezone(bot, msg, jid, is_room, args)
        if timezone:
            if lines[-1] != "":
                lines.append("")
            lines.append(f"• Timezone: {timezone}")

        bot.reply(msg, lines)
    except Exception as e:
        bot.reply(msg, f"🔴 Failed to fetch vCard for {target_nick}: {e}")
        log.error("[VCARD] Exception during vCard lookup"
                  f" for '{target_nick}' ({muc_jid}): {e}")


@command(
    "fullname",
    role=Role.USER,
    aliases=["f"],
    short="Show the full name from a user's vCard.",
    usage="{prefix}fullname [nick]",
    examples=["{prefix}fullname Alice"],
    category="profile",
    context="any",
)
async def get_fullname(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the FULLNAME of a user from their vCard.

    Usage:
        {prefix}fullname [nick]
        {prefix}f [nick]

    Example:
        {prefix}fullname Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "FN", "Full Name")


@command(
    "nicknames",
    role=Role.USER,
    aliases=["nicks"],
    short="Show nicknames from a user's vCard.",
    usage="{prefix}nicknames [nick]",
    examples=["{prefix}nicks Alice"],
    category="profile",
    context="any",
)
async def get_nicknames(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the nicknames from a user's vCard.

    Usage:
        {prefix}nicknames [nick]
        {prefix}nicks [nick]

    Example:
        {prefix}nicknames Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "NICKNAME", "Nicknames")


@command(
    "organisations",
    role=Role.USER,
    aliases=["orgs"],
    short="Show organisations from a user's vCard.",
    usage="{prefix}organisations [nick]",
    examples=["{prefix}orgs Alice"],
    category="profile",
    context="any",
)
async def get_organisations(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the organisations from a user's vCard.

    Usage:
        {prefix}organisations [nick]
        {prefix}orgs [nick]

    Example:
        {prefix}orgs Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "ORG", "Organisations")


@command(
    "notes",
    role=Role.USER,
    short="Show notes from a user's vCard.",
    usage="{prefix}notes [nick]",
    examples=["{prefix}notes Alice"],
    category="profile",
    context="any",
)
async def get_notes(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the notes from a user's vCard.

    Usage:
        {prefix}notes [nick]

    Example:
        {prefix}notes Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "NOTE", "Notes")


@command(
    "emails",
    role=Role.USER,
    aliases=["e"],
    short="Show email addresses from a user's vCard.",
    usage="{prefix}emails [nick]",
    examples=["{prefix}emails Alice"],
    category="profile",
    context="any",
)
async def get_email(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the EMAILs of a user.

    Usage:
        {prefix}emails [nick]
        {prefix}e [nick]

    Example:
        {prefix}email Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "EMAIL", "Emails")


@command(
    "urls",
    role=Role.USER,
    aliases=["u"],
    short="Show URLs from a user's vCard.",
    usage="{prefix}urls [nick]",
    examples=["{prefix}urls Alice"],
    category="profile",
    context="any",
)
async def get_urls(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the URLS of a user.

    Usage:
        {prefix}urls [nick]
        {prefix}u [nick]

    Example:
        {prefix}urls Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "URL", "URLs")


@command(
    "birthday",
    role=Role.USER,
    aliases=["b"],
    short="Show birthday data from a user's vCard.",
    usage="{prefix}birthday [nick]",
    examples=["{prefix}birthday Alice"],
    category="profile",
    context="any",
)
async def get_birthday(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the BIRTHDAY of a user and days until next birthday from their vCard.

    Usage:
        {prefix}birthday [nick]
        {prefix}b [nick]
    Example:
        {prefix}birthday Envsi
    """
    jid = None
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    if (is_room or _core._is_muc_pm(msg)) and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return
        display_name = target_nick
        jid = nick_info.get("jid")
    elif (is_room or _core._is_muc_pm(msg)) and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg,
                      f"🔴  Your Nick '{target_nick}' not found in this room.")
            return
        jid = nick_info.get("jid")
        display_name = target_nick
    else:
        if args:
            log.info(f"[VCARD] Direct message with args from '{
                     msg['from'].bare}'")
            bot.reply(
                msg,
                "🔴  In direct messages, you can only look up your own"
                " birthday. Use the command without args.")
            return
        jid = str(msg["from"].bare)
        display_name = jid

    vcard = await get_info(bot, msg, jid)
    value = None
    if vcard and vcard["BDAY"] is not None:
        value = vcard["BDAY"]
    if value is None or value == "" or value == []:
        bot.reply(msg, f"ℹ️ No Birthday set for {display_name}.")
        return

    # Calculate days until next birthday
    today = datetime.date.today()
    try:
        if len(value) == 10:  # YYYY-MM-DD
            month = int(value[5:7])
            day = int(value[8:10])
        elif len(value) == 5:  # MM-DD
            month = int(value[0:2])
            day = int(value[3:5])
        else:
            raise ValueError
        this_year = today.year
        next_birthday = datetime.date(this_year, month, day)
        if next_birthday < today:
            next_birthday = datetime.date(this_year + 1, month, day)
        days_left = (next_birthday - today).days
        days_str = f"{days_left} day{'s' if days_left != 1 else ''}"
        bot.reply(msg, f"🎂 Birthday for {display_name}: {value}"
                  + f" ({days_str} until next birthday)")
    except Exception:
        bot.reply(msg, f"🎂 Birthday for {display_name}: {value}")


def _diagnostic_enabled_count(enabled_rooms: set[str], room_jid: str | None) -> int:
    if not room_jid:
        return len(enabled_rooms)
    target = str(room_jid).split('/', 1)[0].strip().lower()
    return sum(
        1 for room in enabled_rooms
        if str(room).split('/', 1)[0].strip().lower() == target
    )


def _joined_nick_count(room_jid: str | None = None) -> int:
    if room_jid:
        target = str(room_jid).split('/', 1)[0].strip().lower()
        joined = JOINED_ROOMS.get(target, {})
        nicks = joined.get("nicks", {}) if isinstance(joined, dict) else {}
        return len(nicks) if isinstance(nicks, dict) else 0
    total = 0
    for joined in JOINED_ROOMS.values():
        nicks = joined.get("nicks", {}) if isinstance(joined, dict) else {}
        if isinstance(nicks, dict):
            total += len(nicks)
    return total


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int | float]:
    """Return small vCard counters for diagnostics."""
    enabled_rooms = await _core._get_enabled_rooms(
        bot, VCARD_KEY, "vcard", [room_jid] if room_jid else ()
    )
    plugin_map = getattr(bot, "plugin", {}) or {}
    return {
        "enabled_rooms": _diagnostic_enabled_count(enabled_rooms, room_jid),
        "joined_rooms": 1 if room_jid and _joined_nick_count(room_jid) else (len(JOINED_ROOMS) if not room_jid else 0),
        "tracked_nicks": _joined_nick_count(room_jid),
        "xep_0054_available": int("xep_0054" in plugin_map),
        "fetch_timeout": float(config.get("vcard_fetch_timeout_seconds", 10) or 10),
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return vCard plugin health lines."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    icon = "✅" if state["xep_0054_available"] else "⚠️"
    return [
        f"{icon} vCard{scope}: enabled_rooms={state['enabled_rooms']}, "
        f"joined_rooms={state['joined_rooms']}, "
        f"tracked_nicks={state['tracked_nicks']}, "
        f"xep_0054_available={state['xep_0054_available']}, "
        f"fetch_timeout={state['fetch_timeout']:g}s"
    ]
