"""
Birthday notification plugin.

Automatically sends birthday greetings in rooms when:
- Birthday notifications are ENABLED for the room (via MUC direct message)
- It's the user's birthday (based on profile BIRTHDAY field)
- The user is currently present in the room
- The notification hasn't been sent yet today

**Features:**
- Per-room opt-in (must be enabled per room via MUC direct message)
- Daily birthday checks at bot startup and periodically
- Instant notification when user joins room on their birthday
- Multi-room support (greet in all rooms where enabled and user is present)
- Tracks sent notifications per day to avoid duplicate greetings
- Handles both MM-DD and YYYY-MM-DD birthday formats

**Commands:**
• {prefix}birthday_notify on — Enable birthday notifications in this room
• {prefix}birthday_notify off — Disable birthday notifications in this room
• {prefix}birthday_notify status — Check if enabled
"""

import asyncio
import datetime
import logging
from functools import partial
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS
from utils.plugin_helper import handle_room_toggle_command
from plugins.vcard import vcard_field

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "birthday_notify",
    "version": "1.0.2",
    "description": "🎂 Automatic birthday notifications in rooms (opt-in per room)",
    "category": "fun",
    "requires": ["rooms"],
}

# Track which birthdays we've announced today: {jid: date_str}
ANNOUNCED_TODAY = {}

# Background task for periodic birthday checks
_BIRTHDAY_CHECK_TASK = None



def _parse_birthday(birthday_str: str) -> dict | None:
    """
    Parse birthday string (MM-DD or YYYY-MM-DD) into components.

    Returns:
        dict with keys: 'month', 'day', 'year' (year only if YYYY-MM-DD)
        or None if invalid
    """
    if not birthday_str:
        return None

    try:
        if len(birthday_str) == 5:  # MM-DD
            month = int(birthday_str[0:2])
            day = int(birthday_str[3:5])
            year = None
        elif len(birthday_str) == 10:  # YYYY-MM-DD
            year = int(birthday_str[0:4])
            month = int(birthday_str[5:7])
            day = int(birthday_str[8:10])
        else:
            return None

        # Validate
        if 1 <= month <= 12 and 1 <= day <= 31:
            return {"month": month, "day": day, "year": year}
        else:
            return None

    except (ValueError, IndexError):
        pass

    return None


def _is_birthday_today(birthday_str: str) -> bool:
    """
    Check if birthday is today.

    Args:
        birthday_str: Birthday string (MM-DD or YYYY-MM-DD)

    Returns:
        True if today is the user's birthday
    """
    birthday_data = _parse_birthday(birthday_str)
    if not birthday_data:
        return False

    today = datetime.date.today()
    return (today.month, today.day) == (birthday_data["month"], birthday_data["day"])


def _calculate_age(birthday_str: str) -> int | None:
    """
    Calculate age from birthday string (only if YYYY-MM-DD format).

    Args:
        birthday_str: Birthday string (MM-DD or YYYY-MM-DD)

    Returns:
        Age in years or None if birthday format doesn't include year
    """
    birthday_data = _parse_birthday(birthday_str)
    if not birthday_data or not birthday_data.get("year"):
        return None

    today = datetime.date.today()
    age = today.year - birthday_data["year"]

    # Adjust if birthday hasn't occurred yet this year
    if (today.month, today.day) < (birthday_data["month"], birthday_data["day"]):
        age -= 1

    return age


async def _is_enabled_for_room(bot, room_jid: str) -> bool:
    """
    Check if birthday notifications are enabled for a specific room.

    Args:
        bot: Bot instance
        room_jid: Room JID

    Returns:
        True if enabled, False otherwise
    """
    try:
        store = bot.db.users.plugin("birthday_notify")
        enabled_rooms = await store.get_global("birthday_notify_enabled_rooms", default={})
        return enabled_rooms.get(str(room_jid), False) is True
    except Exception:
        return False


async def _check_user_birthday(bot, user_jid_str: str, nick: str, room_jid):
    """
    Check if a specific user has birthday today and announce if so.
    """
    try:
        today_str = datetime.date.today().isoformat()
        store = bot.db.users.plugin("birthday_notify")

        msg = bot.make_message(mfrom=room_jid,
                               mto=bot.boundjid.bare,
                               mtype="chat",
                               mbody="None")

        # Get user's birthday from profile
        birthday = await vcard_field(bot, msg, nick, "BDAY")
        log.info(f"[BIRTHDAY] Checking {nick} ({user_jid_str}) in room {room_jid} - birthday: {birthday}")

        if not birthday:
            return
        
        # Load from DB if not in memory
        if user_jid_str not in ANNOUNCED_TODAY:
            announced_date = birthday
            if announced_date:
                ANNOUNCED_TODAY[user_jid_str] = announced_date

        # Skip if we already announced this user today
        if ANNOUNCED_TODAY.get(user_jid_str) == today_str:
            return


        # Check if today is their birthday
        if not _is_birthday_today(birthday):
            return

        # Birthday! Build message with age if available
        age = _calculate_age(birthday)
        if age is not None:
            msg_text = f"🎂 Happy Birthday {nick}! 🎉 You're turning {age} today!"
        else:
            msg_text = f"🎂 Happy Birthday {nick}! 🎉"

        try:
            msg = bot.make_message(
                mto=room_jid,
                mbody=msg_text,
                mtype="groupchat"
            )
            # Use safe send method
            await bot._safe_send_message(msg)
        except Exception as e:
            log.exception(f"[BIRTHDAY] 🔴 Failed to send birthday message: {e}")
            return

        # Mark as announced
        ANNOUNCED_TODAY[user_jid_str] = today_str

        # Persist to DB
        await store.set(user_jid_str, "announced_date", today_str)
        await bot.db.users.flush_all()

        log.info(
            f"[BIRTHDAY] 🎂 Birthday announcement for {nick} "
            f"({user_jid_str}) in room {room_jid}"
            + (f" (age {age})" if age else "")
        )

    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error checking user birthday: {e}")


async def _check_and_announce_birthdays(bot):
    """
    Check all users for birthdays and announce in their present rooms.

    Only announces once per day per user (tracked in ANNOUNCED_TODAY).
    Only announces in rooms where birthday_notify is enabled.
    """
    try:
        log.info(f"[BIRTHDAY] Already announced: {ANNOUNCED_TODAY}")
        for room_jid, room_data in JOINED_ROOMS.items():
            # Check if enabled for this room
            enabled = await _is_enabled_for_room(bot, str(room_jid))
            if not enabled:
                continue

            nicks_data = room_data.get("nicks", {})

            for nick, nick_info in nicks_data.items():
                user_jid = nick_info.get("jid")
                if not user_jid:
                    continue

                user_jid_str = str(user_jid)
                await _check_user_birthday(bot, user_jid_str, nick, room_jid)

    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error in birthday check: {e}")


async def _birthday_check_loop(bot, check_interval: int = 3600):
    """
    Periodic task that checks for birthdays.

    Args:
        bot: The bot instance
        check_interval: Seconds between checks (default: 1 hour = 3600s)
    """
    try:
        while True:
            try:
                await asyncio.sleep(check_interval)
                await _check_and_announce_birthdays(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception(f"[BIRTHDAY] 🔴 Error in check loop: {e}")
    except asyncio.CancelledError:
        log.debug("[BIRTHDAY] ✅ Birthday check loop stopped")


# ============================================================================
# EVENT HANDLERS
# ============================================================================

async def on_muc_presence(bot, pres):
    """
    Called when someone joins/leaves a MUC room.
    Check if they have birthday today.
    """
    try:
        # Only handle presence (join)
        if pres["type"] == "unavailable":
            return

        room_jid = pres["from"].bare
        nick = pres["from"].resource
        jid = pres["muc"].get("jid")

        if not jid:
            return

        user_jid_str = str(jid.bare) if jid else None
        if not user_jid_str:
            return

        # Check if birthday notifications enabled for this room
        enabled = await _is_enabled_for_room(bot, str(room_jid))
        if not enabled:
            return

        await _check_user_birthday(bot, user_jid_str, nick, room_jid)

    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error in muc_presence: {e}")


# ============================================================================
# COMMANDS
# ============================================================================

@command("birthday_notify", role=Role.USER)
async def birthday_notify_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Enable, disable, or show birthday notifications for this room.

    on/off/status are only allowed from a MUC DM by room admins/owners
    or bot-level moderators/admins/owners.
    """
    if await handle_room_toggle_command(
        bot, msg, is_room, args,
        store_getter=_get_birthday_store,
        key="birthday_notify_enabled_rooms",
        label="Birthday notifications",
        storage="dict",
        log_prefix="[BIRTHDAY]",
    ):
        return

    prefix = config.get('prefix', ',')
    bot.reply(msg, f"🟡️ Usage: {prefix}birthday_notify <on|off|status>")


async def _get_birthday_store(bot):
    return bot.db.users.plugin("birthday_notify")


# ============================================================================
# PLUGIN LIFECYCLE
# ============================================================================

async def on_ready(bot):
    """
    Called when bot is fully initialized.

    - Performs initial birthday check
    - Starts background periodic check task
    """
    global _BIRTHDAY_CHECK_TASK

    try:
        log.info("[BIRTHDAY] 🎂 Initializing birthday notifications...")

        # Initial check
        await _check_and_announce_birthdays(bot)

        # Start background check task (check every hour)
        _BIRTHDAY_CHECK_TASK = asyncio.create_task(
            _birthday_check_loop(bot, check_interval=3600)
        )

        log.info("[BIRTHDAY] ✅ Birthday notification system ready")

    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error during initialization: {e}")


async def on_load(bot):
    """
    Called when plugin is loaded.
    Register MUC presence event handler.
    """
    try:
        # Register MUC presence event handler
        bot.bot_plugins.register_event(
            "birthday_notify",
            "groupchat_presence",
            partial(on_muc_presence, bot)
        )
        log.info("[BIRTHDAY] ✅ MUC presence handler registered")
    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error registering event handler: {e}")


async def on_unload(bot):
    """
    Called when plugin is unloaded.

    Stops the background birthday check task.
    """
    global _BIRTHDAY_CHECK_TASK

    try:
        if _BIRTHDAY_CHECK_TASK:
            _BIRTHDAY_CHECK_TASK.cancel()
            try:
                await _BIRTHDAY_CHECK_TASK
            except asyncio.CancelledError:
                pass

        log.info("[BIRTHDAY] ✅ Birthday notification plugin unloaded")

    except Exception as e:
        log.exception(f"[BIRTHDAY] 🔴 Error during plugin unload: {e}")
