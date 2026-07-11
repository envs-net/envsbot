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
import urllib.parse
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
WEATHER_MAX_BYTES = 65536
WTTR_HEADERS = {
    "User-Agent": "curl/8.0 (envsbot weather; +https://github.com/envs-net/envsbot)",
    "Accept": "text/plain, */*;q=0.1",
}


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


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return weather room-toggle counters for diagnostics."""
    store = await get_weather_store(bot)
    enabled = await store.get_global(WEATHER_KEY, default={})
    if not isinstance(enabled, dict):
        enabled = {}
    if room_jid:
        target = str(room_jid or "").split("/", 1)[0].strip().lower()
        return {
            "enabled_rooms": int(any(str(room).split("/", 1)[0].strip().lower() == target for room in enabled))
        }
    return {"enabled_rooms": len(enabled)}


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return weather diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [f"✅ Weather{scope}: enabled_rooms={state.get('enabled_rooms', 0)}, timeout={WEATHER_HTTP_TIMEOUT:g}s"]


@command(
    "weather",
    role=Role.USER,
    aliases=["w"],
    short="Show weather from a user's vCard location, a room nick, or an explicit city/ZIP code; or control room access.",
    usage="{prefix}weather [on|off|status|nick|city|zip]",
    examples=[
        "{prefix}weather status",
        "{prefix}weather Alice",
        "{prefix}rooms enable weather",
    ],
    category="utility",
    context="any",
)
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
    target_jid = msg["from"].bare
    display_name = str(msg.get("mucnick") or "you")

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
            target_jid,
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
        vcard_data = await vcard.get_user_vcard(bot, msg, target_jid)
        locality, region, country = _extract_location_fields(vcard_data)
    except Exception as e:
        log.warning(f"[WEATHER] Failed to get vCard fields for"
                    f" {target_jid}: {e}")
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
                    f" {jid}: {e}")
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
        weather = await _fetch_wttr_weather_text(weather_url)
    except WeatherFetchError as exc:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(
            "[WEATHER] 🌦️ Failed to fetch weather for %s at %s: %s",
            display_name,
            location,
            exc,
        )
        return
    except Exception:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(
            "[WEATHER] 🌦️ Exception fetching weather for %s at %s",
            display_name,
            location,
            exc_info=True,
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


class WeatherFetchError(RuntimeError):
    """Raised when wttr.in returns an unusable weather response."""


def _wttr_fetch_candidates(weather_url: str) -> list[str]:
    """Return wttr.in fetch URLs, including a plain-HTTP fallback."""
    urls = [weather_url]
    if weather_url.startswith("https://wttr.in/"):
        urls.append(weather_url.replace("https://", "http://", 1))
    return urls


async def _fetch_wttr_weather_text(weather_url: str) -> str:
    """Fetch and validate the compact wttr.in weather response."""
    errors: list[str] = []
    for candidate_url in _wttr_fetch_candidates(weather_url):
        try:
            result = await fetch_text(
                candidate_url,
                timeout_seconds=WEATHER_HTTP_TIMEOUT,
                max_bytes=WEATHER_MAX_BYTES,
                headers=WTTR_HEADERS,
                session_factory=aiohttp.ClientSession,
                validator=passthrough_validator,
                raise_for_status=False,
            )
        except Exception as exc:
            errors.append(f"{candidate_url}: {exc}")
            log.debug(
                "[WEATHER] wttr.in fetch attempt failed for %s",
                candidate_url,
                exc_info=True,
            )
            continue

        if result.status != 200:
            errors.append(f"{candidate_url}: HTTP {result.status}")
            continue

        weather = result.text.strip()
        if not weather:
            errors.append(f"{candidate_url}: empty response")
            continue
        unusable_reason = _wttr_unusable_response_reason(weather)
        if unusable_reason:
            errors.append(f"{candidate_url}: {unusable_reason}")
            continue

        return weather

    raise WeatherFetchError("; ".join(errors) or "no usable response")


def _wttr_unusable_response_reason(weather: str) -> str:
    """Return a reason when wttr.in did not return compact weather text."""
    normalized = weather.strip()
    lowered = normalized.lower()
    if not normalized:
        return "empty response"
    if lowered.startswith("unknown location"):
        return normalized
    if "<html" in lowered or "<!doctype" in lowered:
        return "HTML response instead of compact weather text"
    if len(normalized) > 1000:
        return "unexpectedly large compact weather response"
    if normalized.count("\n") > 6:
        return "unexpected multiline weather response"
    return ""


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
