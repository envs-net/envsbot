"""
Info plugin: Show the current weather for a user's location
configured in their vCard or for an explicitly provided city/ZIP code.
Only works in groupchats or MUC DMs where the room feature is enabled.

IMPORTANT: You may need to turn the plugins usage on with the following
command in each room you want to use it in:
    {prefix}weather on

Commands:
    {prefix}weather <on|off|status>
    {prefix}weather [nick|city|zip]
"""

import aiohttp
import logging
import urllib
from core_plugins import _core
from plugins import vcard
from utils.command import command, Role
# Intentionally exposed for tests and runtime settings.
from utils.config import config
from utils.http_fetch import fetch_text, passthrough_validator
from core_plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "weather",
    "version": "0.5.0",
    "description": ("Gives weather according to users location or an "
                    "explicit city/ZIP code"),
    "category": "info",
    "requires": ["_core", "rooms", "vcard"],
}

WEATHER_KEY = "WEATHER"
WEATHER_HTTP_TIMEOUT = float(config.get("http_timeout_seconds", 8) or 8)


async def get_display_name(bot, jid):
    store = bot.db.users.plugin("users")
    display_name = "unknown"
    try:
        roomnicks = await store.get(jid, "roomnicks")
        if isinstance(roomnicks, dict):
            for nick_values in roomnicks.values():
                if nick_values:
                    display_name = nick_values[0]
                    break
    except Exception as e:
        log.warning(
            "[PROFILE] 🔴  Failed to get roomnicks for %s: %s",
            jid, e
        )
    log.debug(
        "[PROFILE] 👤 Profile lookup for self: %s",
        display_name
    )
    return display_name


def get_pm_target(sender_jid, nick):
    if hasattr(sender_jid, "bare"):
        bare_jid = sender_jid.bare
    else:
        bare_jid = str(sender_jid).split('/')[0]
    return bare_jid, nick


async def get_weather_store(bot):
    return bot.db.users.plugin("weather")


@command("weather", role=Role.USER, aliases=["w"])
async def weather_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current weather for a users location set in their vCard or
    for an explicitly provided city/ZIP code. If the <nick> is omitted,
    your own location according to your vCard is used. In rooms and MUC
    PMs, an argument matching a room nick uses that user's vCard; any
    other argument is treated as a direct weather location.

    Usage:
        {prefix}weather
        {prefix}weather <on|off|status>
        {prefix}weather <nick|city|zip>
    """
    handled = await _core.handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_weather_store,
        key=WEATHER_KEY,
        label="Get weather",
        storage="dict",
        log_prefix="[WEATHER]",
    )
    if handled:
        return

    enabled_rooms = await _core._get_enabled_rooms(bot, WEATHER_KEY, "weather")

    if _core._is_muc_pm(msg):
        await _handle_weather_muc_pm(bot, msg, args, enabled_rooms)
        return

    if is_room:
        await _handle_weather_room(bot, msg, args, enabled_rooms)
        return

    await _handle_weather_dm(bot, msg, args)


async def _handle_weather_room(bot, msg, args, enabled_rooms):
    log.debug(
        "[WEATHER] Command invoked in room %s by %s with args: %s",
        msg["from"].bare,
        msg["from"].resource,
        args,
    )

    muc_jid = msg["from"].bare
    if muc_jid not in enabled_rooms:
        return

    nicks = JOINED_ROOMS.get(muc_jid, {}).get("nicks", {})

    direct_location = _resolve_direct_location(args, nicks)
    if direct_location is not None:
        await _reply_with_weather_for_location(
            bot,
            msg,
            direct_location,
            direct_location,
        )
        return

    target_nick = _resolve_room_target_nick(bot, msg, args)
    if target_nick is None:
        return

    if target_nick not in nicks:
        log.debug(
            "[WEATHER] Lookup failed: Nick %r not found in room %s",
            target_nick,
            muc_jid,
        )
        prefix = "Your nick" if not args else "Nick"
        bot.reply(msg, f"🔴  {prefix} '{target_nick}' not found in this room.")
        return

    jid = nicks[target_nick].get("jid", None)
    await _process_weather_for_jid(bot, msg, jid, target_nick,
                                   muc_jid, is_dm=False)


async def _handle_weather_muc_pm(bot, msg, args, enabled_rooms):
    log.debug(
        "[WEATHER] Command invoked in room %s by %s with args: %s",
        msg["from"].bare,
        msg["from"].resource,
        args,
    )

    muc_jid = msg["from"].bare
    if muc_jid not in enabled_rooms:
        return

    nicks = JOINED_ROOMS.get(muc_jid, {}).get("nicks", {})

    direct_location = _resolve_direct_location(args, nicks)
    if direct_location is not None:
        await _reply_with_weather_for_location(
            bot,
            msg,
            direct_location,
            direct_location,
        )
        return

    target_nick = _resolve_muc_pm_target_nick(bot, msg, args)
    if target_nick is None:
        return

    if target_nick not in nicks:
        log.debug(
            "[WEATHER] Lookup failed: Nick %r not found in room %s",
            target_nick,
            muc_jid,
        )
        prefix = "Your nick" if not args else "Nick"
        bot.reply(msg, f"🔴  {prefix} '{target_nick}' not found in this room.")
        return

    jid = nicks[target_nick].get("jid", None)
    await _process_weather_for_jid(bot, msg, jid, target_nick,
                                   muc_jid, is_dm=False)


async def _handle_weather_dm(bot, msg, args):
    target_nick = msg["from"].bare
    display_name = target_nick

    if args:
        direct_location = _location_from_args(args)
        if not direct_location:
            bot.reply(
                msg,
                "🔴  Please provide a city or ZIP code.",
            )
            return
        log.debug(
            "[WEATHER] Command invoked by %r in DM for direct location: %s",
            target_nick,
            direct_location,
        )
        await _reply_with_weather_for_location(
            bot,
            msg,
            direct_location,
            direct_location,
        )
        return

    try:
        vcard_data = await vcard.get_user_vcard(bot, msg, target_nick)
        locality, region, country = _extract_location_fields(vcard_data)
    except Exception as e:
        log.warning(f"[WEATHER] Failed to get vCard fields for"
                    f" {target_nick}: {e}")
        bot.reply(msg, "🔴  Failed to retrieve your vCard information.")
        return

    await _reply_with_weather(bot, msg, display_name,
                              locality, region, country)


def _resolve_room_target_nick(bot, msg, args):
    if args:
        return " ".join(args).strip()

    target_nick = msg.get("mucnick") or getattr(msg["from"], "resource", None)
    if not target_nick:
        bot.reply(msg, "🔴  Couldn't determine your nickname.")
        return None
    return target_nick


def _resolve_muc_pm_target_nick(bot, msg, args):
    if args:
        return " ".join(args).strip()

    target_nick = getattr(msg["from"], "resource", None)
    if not target_nick:
        bot.reply(msg, "🔴  Couldn't determine your nickname.")
        return None
    return target_nick


def _location_from_args(args):
    return " ".join(str(arg) for arg in args).strip()


def _resolve_direct_location(args, nicks):
    if not args:
        return None

    arg_text = _location_from_args(args)
    if not arg_text:
        return None

    if arg_text in nicks:
        return None

    return arg_text


def _extract_location_fields(vcard_data):
    return (
        vcard_data.get("LOCALITY", None),
        vcard_data.get("REGION", None),
        vcard_data.get("CTRY", None),
    )


async def _process_weather_for_jid(bot, msg, jid, target_nick, muc_jid, is_dm):
    display_name = target_nick
    try:
        vcard_data = await vcard.get_user_vcard(bot, msg, jid)
        locality, region, country = _extract_location_fields(vcard_data)
    except Exception as e:
        log.warning(f"[WEATHER] Failed to get vCard fields for"
                    f" {target_nick}: {e}")
        bot.reply(
            msg,
            f"🔴  Failed to retrieve vCard information for '{target_nick}'.",
        )
        return

    log.debug(f"[VCARD] vCard for '{target_nick}' ({muc_jid}) received.")
    await _reply_with_weather(bot, msg, display_name, locality,
                              region, country)


async def _reply_with_weather(bot, msg, display_name, locality,
                              region, country):
    location = _select_location(locality, region, country)
    await _reply_with_weather_for_location(bot, msg, display_name, location)


async def _reply_with_weather_for_location(bot, msg, display_name, location):

    log.debug("[WEATHER] Location for %s: %s", display_name, location)

    if not location or location.strip() == "":
        bot.reply(msg, f"🟡️ No LOCATION in vCard for {display_name}.")
        return

    forecast_url, weather_url = _build_wttr_urls(location)

    try:
        result = await fetch_text(
            weather_url,
            timeout_seconds=WEATHER_HTTP_TIMEOUT,
            max_bytes=8192,
            session_factory=aiohttp.ClientSession,
            validator=passthrough_validator,
            raise_for_status=False,
        )
        if result.status != 200:
            bot.reply(msg, f"🌦️ Failed to fetch weather for"
                           f" {display_name}.")
            log.warning(
                f"[WEATHER] 🌦️ HTTP error {result.status} for"
                f" {display_name} at {location}"
            )
            return
        weather = result.text
    except Exception:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(
            f"[WEATHER] 🌦️ Exception fetching weather for"
            f" {display_name} at {location}"
        )
        return

    bot.reply(
        msg,
        f"{_format_weather_reply(display_name, location, weather)}\n"
        f"Forecast: {forecast_url}",
        ephemeral=False,
    )


def _format_weather_reply(display_name, location, weather):
    weather_loc, weather_desc = _parse_wttr_weather(weather)
    header = f"🌤️ Weather for {display_name}"

    if not _same_location_text(display_name, location):
        location_label = location
        if weather_loc and _same_location_text(weather_loc, location):
            location_label = weather_loc.title()
        header = f"{header} ({location_label})"

    if weather_loc and not (
        _same_location_text(weather_loc, display_name)
        or _same_location_text(weather_loc, location)
    ):
        weather_desc = f"{weather_loc.title()}: {weather_desc}"

    return f"{header}: {weather_desc.strip()}"


def _parse_wttr_weather(weather):
    weather_loc, separator, weather_desc = weather.partition(":")
    if not separator:
        return "", weather.strip()
    return weather_loc.strip(), weather_desc.strip()


def _same_location_text(left, right):
    return _normalize_location_text(left) == _normalize_location_text(right)


def _normalize_location_text(value):
    return " ".join(str(value or "").strip().split()).casefold()


def _build_wttr_urls(location):
    enc_location = urllib.parse.quote(location.strip(), safe="")
    forecast_url = f"https://wttr.in/{enc_location}"
    weather_url = f"{forecast_url}?format=4&m"
    return forecast_url, weather_url


def _select_location(locality, region, country):
    location = None
    if country is not None:
        location = country
    if region is not None:
        location = region
    if locality is not None:
        location = locality
    if location is None:
        location = ""
    return location
