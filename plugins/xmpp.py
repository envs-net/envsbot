"""
XMPP utility commands plugin.

This plugin provides various commands for interacting with XMPP
servers and users, such as pinging a JID, querying service discovery info,
checking compliance scores, and performing DNS SRV lookups.

Commands:
    {prefix}x <on|off|status>       - Toggle usage of XMPP commands in a room
                                      or show status.
    {prefix}x help                  - Displays all available commands.
    {prefix}x version <domain>      - Shows the software version of an
                                      XMPP server (XEP-0092).
    {prefix}x items <domain|jid>    - Lists service items of an
                                      XMPP server (XEP-0030).
    {prefix}x contact <domain>      - Displays admin/contact information for a
                                      server (XEP-0030).
    {prefix}x info <domain|jid>     - Shows identities & features (XEP-0030).
    {prefix}x ping <domain|jid>     - Pings an XMPP entity (XEP-0199).
    {prefix}x cert <domain>         - Check the XMPP S2S TLS certificate.
    {prefix}x check <domain|jid>    - Run ping/disco/version/SRV/TLS diagnostics.
    {prefix}x uptime <domain>       - Shows the uptime of an XMPP server
                                      (XEP-0012).
    {prefix}x srv <domain>          - DNS SRV lookup.
    {prefix}x compliance <domain>   - Compliance score from
                                      compliance.conversations.im.
"""
import asyncio
import time

import slixmpp
from utils.command import command, Role
from utils.config import config
from utils.http_fetch import fetch_preview, passthrough_validator
from utils.tls_certificate import (
    VALID_XMPP_CERTIFICATE_MESSAGE as XMPP_VALID_CERTIFICATE_MESSAGE,
    diagnose_xmpp_server_certificate,
    make_srv_resolver as _make_srv_resolver,
    source_domain_from_jid,
    validate_xmpp_domain as _validate_domain,
)
from core_plugins._core import (
        handle_room_toggle_command,
        _get_enabled_rooms,
        _is_muc_pm,
        JOINED_ROOMS,
)

XMPP_KEY = "XMPP"
XMPP_QUERY_TIMEOUT_SECONDS = float(config.get("xmpp_query_timeout_seconds", 8) or 8)
XMPP_HTTP_TIMEOUT_SECONDS = float(config.get("http_timeout_seconds", 8) or 8)
XMPP_CERTIFICATE_PROBE_TIMEOUT_SECONDS = max(
    1.0,
    min(5.0, XMPP_QUERY_TIMEOUT_SECONDS),
)
XMPP_COMPLIANCE_MAX_READ_BYTES = max(
    8192,
    int(config.get("xmpp_compliance_max_read_bytes", 262144) or 262144),
)


def _compliance_preview_complete(body: bytes) -> bool:
    """Return True once a compliance-page preview has enough score data."""
    lower = body.lower()
    return b"stat_result" in lower or b"</html" in lower


PLUGIN_META = {
    "name": "xmpp",
    "version": "0.3.7",
    "description":
    "XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.)",
    "category": "tools",
    "requires": ["rooms", "_core"],
}

HELP_TEXT = """
XMPP Utility Commands:
  {prefix}x help                  - Show this help message
  {prefix}x <on|off|status>       - Toggle usage or show status
  {prefix}x version <domain>      - Show server software version (XEP-0092)
  {prefix}x items <domain|jid>    - List service items (XEP-0030)
  {prefix}x contact <domain>      - Show server contact information (XEP-0030)
  {prefix}x info <domain|jid>     - Show identities & features (XEP-0030)
  {prefix}x ping <domain|jid>     - Ping entity (XEP-0199)
  {prefix}x cert <domain>         - Check the XMPP S2S TLS certificate
  {prefix}x check <domain|jid>    - Run ping/disco/version/SRV/TLS diagnostics
  {prefix}x uptime <domain>       - Show server uptime (XEP-0012)
  {prefix}x srv <domain>          - DNS SRV lookup
  {prefix}x compliance <domain>   - Compliance score
""".format(prefix=config.get("prefix", ""))


async def get_xmpp_store(bot):
    return bot.db.users.plugin("xmpp")


def _resolve_target(bot, args, msg, is_room, nick):
    """
    Resolves the command argument to a valid XMPP JID target or room-nick,
    depending on current context (rooms, PM, etc).
    Returns (target, error_message) tuple.
    """
    if not args or len(args) < 1:
        return None, "Missing target JID or nick"
    target = args[0]
    if (is_room or (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and str(msg["from"].bare) in JOINED_ROOMS
    )):
        room = msg["from"].bare
        nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
        if target in nicks:
            return f"{room}/{target}", None
    return target, None


def get_domain_from_jid(arg):
    """
    Returns the domain part if an argument is a JID, otherwise returns the
    argument unchanged.
    """
    if "@" in arg:
        return arg.split("@", 1)[1]
    return arg


def inform_if_jid(msg, target, bot, command_name, domain_only=False):
    """
    If user gave a JID when a domain is required, inform the user.
    """
    if "@" in target:
        domain = get_domain_from_jid(target)
        if domain_only:
            bot.reply(msg, f"Note: '{command_name}' only works with domains."
                           f" Using '{domain}' from '{target}'.")
        return domain
    return target


@command(
    "xmpp",
    role=Role.USER,
    aliases=["x"],
    short="Enable, disable or show room access to XMPP lookup commands.",
    usage="{prefix}xmpp <on|off|status>",
    examples=["{prefix}xmpp status"],
    category="xmpp",
    context="room or MUC PM",
)
async def cmd_xmpp(bot, sender_jid, nick, args, msg, is_room):
    """
    Toggle xmpp commands on or off or show status.

    Usage:
        {prefix}xmpp on|off|status - Toggle usage or show status
    """

    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_xmpp_store,
        key=XMPP_KEY,
        label="Use XMPP commands",
        plugin="xmpp",
        storage="dict",
        log_prefix="[XMPP]",
    )
    if handled:
        return

    bot.reply(msg, "Usage: {prefix}xmpp <on|off|"
                   "status>".format(prefix=config.get("prefix", "")))
    return


@command(
    "xmpp help",
    role=Role.USER,
    aliases=["x help"],
    short="Show help for XMPP lookup subcommands.",
    usage="{prefix}xmpp help",
    examples=["{prefix}x help"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_help(bot, sender_jid, nick, args, msg, is_room):
    """
    Display help message with all available XMPP commands.

    Usage:
        {prefix}xmpp help
        {prefix}x help
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    bot.reply(msg, HELP_TEXT)


@command(
    "xmpp version",
    role=Role.USER,
    aliases=["x version"],
    short="Query XMPP software version and diagnose S2S TLS failures.",
    usage="{prefix}xmpp version <jid>",
    examples=["{prefix}x version envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_version(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the software version of an XMPP server (XEP-0092).
    Usage:
        {prefix}xmpp version <domain>
        {prefix}x version <domain>
    """
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if _should_block_xmpp_version(is_room, msg, enabled_rooms):
        return

    if not args or len(args) < 1:
        bot.reply(msg, "❌ Missing domain")
        return

    target = get_domain_from_jid(args[0])

    is_valid, error_msg = _validate_domain(target)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid domain: {error_msg}")
        return

    if "@" in args[0]:
        bot.reply(
            msg,
            f"Note: 'version' only works with domains."
            f" Using '{target}' from '{args[0]}'."
        )

    try:
        result = await bot.plugin["xep_0092"].get_version(jid=target,
                                                          timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        name, version, os_info = _extract_xmpp_version_info(result)

        if name and version:
            version_info = _format_xmpp_version_info(name, version, os_info)
            bot.reply(msg, f"ℹ️ Version for {target}: {version_info}")
        else:
            bot.reply(
                msg,
                f"ℹ️ {target} does not provide version"
                f" information via XEP-0092"
            )
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Version request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err_condition = _get_iq_error_condition(e)
        if err_condition == "service-unavailable":
            bot.reply(
                msg,
                f"🔴 {target} does not support version"
                f" requests (XEP-0092)."
            )
        else:
            reply = f"🔴 Version request failed: {err_condition}"
            if err_condition == "remote-server-timeout":
                certificate = await _diagnose_xmpp_server_certificate(target)
                if certificate:
                    if certificate.startswith(XMPP_VALID_CERTIFICATE_MESSAGE):
                        certificate += " The timeout occurs later in federation."
                    reply += f"\n🔐 {certificate}"
            bot.reply(msg, reply)
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


def _should_block_xmpp_version(is_room, msg, enabled_rooms):
    return ((is_room or _is_muc_pm(msg))
            and msg["from"].bare not in enabled_rooms)


def _extract_xmpp_version_info(result):
    name, version, os_info = None, None, None

    if hasattr(result, "xml"):
        for child in result.xml:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag != "query":
                continue

            for elem in child:
                if "}" in elem.tag:
                    elem_tag = elem.tag.split("}")[-1]
                else:
                    elem_tag = elem.tag
                if elem_tag == "name":
                    name = elem.text
                elif elem_tag == "version":
                    version = elem.text
                elif elem_tag == "os":
                    os_info = elem.text

    return name, version, os_info


def _format_xmpp_version_info(name, version, os_info):
    version_info = f"**{name}** v{version}"
    if os_info:
        version_info += f" on {os_info}"
    return version_info


def _get_iq_error_condition(exc):
    err = exc.iq["error"]
    return err.get("condition", "unknown")


@command(
    "xmpp uptime",
    role=Role.USER,
    aliases=["x uptime"],
    short="Query XMPP entity uptime.",
    usage="{prefix}xmpp uptime <jid>",
    examples=["{prefix}x uptime envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_uptime(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the uptime of an XMPP server (XEP-0012).

    Usage:
        {prefix}xmpp uptime <domain>
        {prefix}x uptime <domain>
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    if not args or len(args) < 1:
        bot.reply(msg, "❌ Missing domain")
        return

    target = get_domain_from_jid(args[0])

    # Validate domain
    is_valid, error_msg = _validate_domain(target)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid domain: {error_msg}")
        return

    if "@" in args[0]:
        bot.reply(msg, f"Note: 'uptime' only works with domains."
                       f" Using '{target}' from '{args[0]}'.")

    try:
        result = await bot.plugin["xep_0012"].get_last_activity(jid=target,
                                                                timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        seconds = result['last_activity']['seconds']
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        uptime_str = []
        if days > 0:
            uptime_str.append(f"{days}d")
        if hours > 0:
            uptime_str.append(f"{hours}h")
        if minutes > 0:
            uptime_str.append(f"{minutes}m")
        if secs > 0 or not uptime_str:
            uptime_str.append(f"{secs}s")
        bot.reply(msg, f"⏱️ Uptime for {target}: {' '.join(uptime_str)}")
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Uptime request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        if err_condition == "service-unavailable":
            bot.reply(msg, f"🔴 {target} does not support uptime"
                           " requests (XEP-0012).")
        else:
            bot.reply(msg, f"🔴 Uptime request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command(
    "xmpp items",
    role=Role.USER,
    aliases=["x items"],
    short="List service discovery items.",
    usage="{prefix}xmpp items <jid>",
    examples=["{prefix}x items envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_items(bot, sender_jid, nick, args, msg, is_room):
    """
    List the service items of an XMPP server (XEP-0030).

    Usage:
        {prefix}xmpp items <domain|jid>
        {prefix}x items <domain|jid>
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return
    target = inform_if_jid(msg, target, bot, "items")
    try:
        items = await bot.plugin["xep_0030"].get_items(jid=target, timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        disco_items = items.get('disco_items', {})
        items_list = disco_items.get('items', [])
        if not items_list:
            bot.reply(msg, f"No items found for {target}")
            return
        formatted_items = []
        for item in items_list:
            if isinstance(item, tuple) and len(item) >= 1:
                jid = item[0]
                name = item[1] if len(item) > 1 else jid
                formatted_items.append(f"  • {jid} ({name})")
            else:
                formatted_items.append(f"  • {item}")
        result = f"📋 Items for {target}:\n" + "\n".join(formatted_items)
        bot.reply(msg, result)
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Items request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        if err_condition == "service-unavailable":
            bot.reply(msg, f"🔴 {target} does not support items"
                           " requests (XEP-0030).")
        else:
            bot.reply(msg, f"🔴 Items request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command(
    "xmpp contact",
    role=Role.USER,
    aliases=["x contact"],
    short="Show contact addresses from service discovery.",
    usage="{prefix}xmpp contact <jid>",
    examples=["{prefix}x contact envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_contact(bot, sender_jid, nick, args, msg, is_room):
    """
    Display contact information for an XMPP server (XEP-0030).

    Usage:
        {prefix}xmpp contact <domain>
        {prefix}x contact <domain>
    """
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if _should_block_xmpp_contact(is_room, msg, enabled_rooms):
        return

    if not args:
        bot.reply(msg, "❌ Missing domain")
        return

    target = get_domain_from_jid(args[0])
    is_valid, error_msg = _validate_domain(target)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid domain: {error_msg}")
        return

    _reply_xmpp_contact_domain_note(bot, msg, args[0], target)

    try:
        info = await bot.plugin["xep_0030"].get_info(jid=target, timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        contact_info = _extract_xmpp_contact_info(info.get("disco_info", {}))
        _reply_xmpp_contact_result(bot, msg, target, contact_info)
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Contact request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        _reply_xmpp_contact_iq_error(bot, msg, target, e)
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


def _should_block_xmpp_contact(is_room, msg, enabled_rooms):
    return ((is_room or _is_muc_pm(msg))
            and msg["from"].bare not in enabled_rooms)


def _reply_xmpp_contact_domain_note(bot, msg, raw_target, target):
    if "@" in raw_target:
        bot.reply(
            msg,
            "Note: 'contact' only works with domains."
            f" Using '{target}' from '{raw_target}'."
        )


def _extract_xmpp_contact_info(disco_info):
    form = disco_info.get("form")
    if not form:
        return {}

    contact_info = {}
    for field in form:
        label = _contact_label_for_field(field.get("var", ""))
        values = field.get("value", [])
        if label and values:
            contact_info[label] = _normalize_contact_values(values)
    return contact_info


def _contact_label_for_field(field_var):
    lowered = field_var.lower()
    mapping = (
        ("admin", "Admin"),
        ("abuse", "Abuse"),
        ("security", "Security"),
        ("feedback", "Feedback"),
        ("support", "Support"),
    )
    for needle, label in mapping:
        if needle in lowered:
            return label
    return None


def _normalize_contact_values(values):
    return values if isinstance(values, list) else [values]


def _reply_xmpp_contact_result(bot, msg, target, contact_info):
    if not contact_info:
        bot.reply(
            msg,
            f"ℹ️  {target} does not provide contact"
            "information via XEP-0030"
        )
        return

    lines = _format_xmpp_contact_lines(contact_info)
    bot.reply(msg, f"📧 Contact info for {target}:\n" + "\n".join(lines))


def _format_xmpp_contact_lines(contact_info):
    contact_types = ["Admin", "Abuse", "Security", "Feedback", "Support"]
    lines = []
    for contact_type in contact_types:
        for addr in contact_info.get(contact_type, []):
            lines.append(f"  • {contact_type}: {addr}")
    return lines


def _reply_xmpp_contact_iq_error(bot, msg, target, exc):
    err_condition = _get_iq_error_condition(exc)
    if err_condition == "service-unavailable":
        bot.reply(
            msg,
            f"🔴 {target} does not support"
            " contact requests (XEP-0030)."
        )
    else:
        bot.reply(msg, f"🔴 Contact request failed: {err_condition}")


def _format_disco_identity(ident):
    if isinstance(ident, tuple) and len(ident) >= 2:
        category = ident[0]
        ident_type = ident[1]
        name = ident[2] if len(ident) > 2 else None
        ident_str = category
        if ident_type:
            ident_str += f"/{ident_type}"
        if name:
            ident_str += f" ({name})"
        return f"  • {ident_str}"
    return None


def _extract_xmpp_info_lines(disco_info):
    identities = []
    if 'identities' in disco_info:
        for ident in disco_info['identities']:
            formatted = _format_disco_identity(ident)
            if formatted:
                identities.append(formatted)

    features = []
    if 'features' in disco_info:
        features = [f"  • {feature}" for feature in disco_info['features']]

    return identities, features


def _build_xmpp_info_result(target, identities, features):
    result = f"🔍 Info for {target}:\n"
    if identities:
        result += "\n**Identities:**\n" + "\n".join(identities)
    if features:
        result += "\n**Features:**\n" + "\n".join(features[:10])
        if len(features) > 10:
            result += f"\n  ... and {len(features) - 10} more"
    if not identities and not features:
        result += "No identities or features found."
    return result


def _reply_xmpp_info_error(bot, msg, target, exc):
    if isinstance(exc, slixmpp.exceptions.IqTimeout):
        bot.reply(msg, f"🔴 Info request to {target} timed out.")
        return

    if isinstance(exc, slixmpp.exceptions.IqError):
        err = exc.iq['error']
        err_condition = err.get('condition', 'unknown')
        if err_condition == "service-unavailable":
            bot.reply(msg, f"🔴 {target} does not support"
                           " info requests (XEP-0030).")
        else:
            bot.reply(msg, f"🔴 Info request failed: {err_condition}")
        return

    bot.reply(msg, f"🔴 Error: {exc}")


@command(
    "xmpp info",
    role=Role.USER,
    aliases=["x info"],
    short="Show service discovery identity/features.",
    usage="{prefix}xmpp info <jid>",
    examples=["{prefix}x info conference.envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_info(bot, sender_jid, nick, args, msg, is_room):
    """
    List the identities and features of an XMPP server/domain (XEP-0030).

    Usage:
        {prefix}xmpp info <domain|jid>
        {prefix}x info <domain|jid>
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    # Always extract domain and notify if JID supplied
    target = inform_if_jid(msg, target, bot, "info")

    try:
        info = await bot.plugin["xep_0030"].get_info(jid=target, timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        disco_info = info.get('disco_info', {})
        identities, features = _extract_xmpp_info_lines(disco_info)
        result = _build_xmpp_info_result(target, identities, features)
        bot.reply(msg, result)
    except Exception as e:
        _reply_xmpp_info_error(bot, msg, target, e)


@command(
    "xmpp ping",
    role=Role.USER,
    aliases=["x ping"],
    short="Ping an XMPP entity.",
    usage="{prefix}xmpp ping <jid>",
    examples=["{prefix}x ping envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_ping(bot, sender_jid, nick, args, msg, is_room):
    """
    Ping an XMPP entity (JID or domain) and report round-trip time (XEP-0199).

    Usage:
        {prefix}xmpp ping <jid|domain>
        {prefix}x ping <jid|domain>
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return
    try:
        start = time.monotonic()
        await bot.plugin["xep_0199"].ping(jid=target, timeout=XMPP_QUERY_TIMEOUT_SECONDS)
        rtt = (time.monotonic() - start) * 1000
        bot.reply(msg, f"🏓 Pong from {target} in {rtt:.1f} ms")
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Ping to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_type = err.get('type', 'unknown')
        err_condition = err.get('condition', 'unknown')
        err_text = err.get('text', '')
        bot.reply(
            msg,
            f"🔴 Ping to {target} failed: {err_type}/"
            f"{err_condition} {err_text}".strip()
        )
    except Exception as e:
        bot.reply(msg, f"🔴 Ping to {target} failed: {e}")


def _reply_xmpp_srv_missing_domain(bot, msg):
    prefix = config.get("prefix", ",")
    bot.reply(msg, f"❌ Missing domain\nUsage: {prefix}x srv <domain>")


def _reply_xmpp_srv_invalid_domain(bot, msg, error_msg):
    bot.reply(msg, f"❌ Invalid domain: {error_msg}")


def _reply_xmpp_srv_jid_notice(bot, msg, domain, original):
    bot.reply(msg, f"Note: 'srv' only works with domains."
                   f" Using '{domain}' from '{original}'.")


def _reply_xmpp_srv_dns_missing(bot, msg):
    bot.reply(msg, "🔴 DNS library not installed. Install"
                   " python-dnspython: pip install dnspython")


def _collect_srv_records(domain, service, resolver, dns_exception):
    srv_name = f"{service}.{domain}"

    try:
        answers = resolver.resolve(
            srv_name,
            "SRV",
            raise_on_no_answer=False,
        )

        if not answers:
            return "❌ Not found"

        records = []
        for rdata in answers:
            target = str(rdata.target).rstrip('.')
            records.append({
                "target": target,
                "port": rdata.port,
                "priority": rdata.priority,
                "weight": rdata.weight,
            })

        records.sort(key=lambda x: (x["priority"], -x["weight"]))

        formatted = []
        for rec in records:
            formatted.append(
                f"{rec['target']}:{rec['port']} "
                f"(priority={rec['priority']}, weight={rec['weight']})"
            )

        return "\n    ".join(formatted)

    except dns_exception.DNSException as e:
        return f"❌ Not found ({type(e).__name__})"
    except Exception as e:
        return f"❌ Error: {e}"


def _collect_all_srv_records(domain, services, resolver, dns_exception):
    return {
        service: _collect_srv_records(domain, service, resolver, dns_exception)
        for service in services
    }


async def _diagnose_xmpp_server_certificate(domain: str) -> str | None:
    """Apply the XMPP plugin configuration to the shared certificate probe."""
    return await diagnose_xmpp_server_certificate(
        domain,
        source_domain=source_domain_from_jid(config.get("jid", "")),
        timeout_seconds=XMPP_CERTIFICATE_PROBE_TIMEOUT_SECONDS,
    )


async def _xmpp_check_certificate(domain: str) -> tuple[str, str]:
    """Return one compact certificate status line for manual and full checks."""
    try:
        certificate = await _diagnose_xmpp_server_certificate(domain)
    except Exception as exc:
        return "🔴", f"certificate check failed: {exc}"
    if certificate is None:
        return "⚠️", "S2S TLS certificate could not be checked."
    if certificate.startswith(XMPP_VALID_CERTIFICATE_MESSAGE):
        return "✅", certificate
    return "🔴", certificate


@command(
    "xmpp cert",
    role=Role.USER,
    aliases=["x cert", "xmpp certificate", "x certificate"],
    short="Check an XMPP server-to-server TLS certificate.",
    usage="{prefix}xmpp cert <domain>",
    examples=["{prefix}x cert envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_cert(bot, sender_jid, nick, args, msg, is_room):
    """Check the S2S STARTTLS certificate used by an XMPP domain."""
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    if not args:
        bot.reply(
            msg,
            f"❌ Missing domain\nUsage: {config.get('prefix', ',')}x cert <domain>",
        )
        return

    raw_target = str(args[0]).strip()
    domain = get_domain_from_jid(raw_target).split("/", 1)[0]
    is_valid, error_msg = _validate_domain(domain)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid domain: {error_msg}")
        return

    if "@" in raw_target:
        bot.reply(
            msg,
            "Note: 'cert' only works with domains."
            f" Using '{domain}' from '{raw_target}'.",
        )

    status, line = await _xmpp_check_certificate(domain)
    bot.reply(
        msg,
        [
            f"🔐 S2S TLS certificate check for {domain}",
            f"{status} {line}",
        ],
    )


def _build_xmpp_srv_result(domain, services, srv_records):
    result = f"🔍 DNS SRV records for **{domain}**:\n"
    found_any = False

    for service in services:
        status = srv_records[service]
        if "Not found" not in status and "Error" not in status:
            found_any = True
            result += f"\n**{service}:**\n    {status}"
        else:
            result += f"\n**{service}:** {status}"

    if not found_any:
        result += "\n\n⚠️ No SRV records found for this domain!"

    return result


@command(
    "xmpp srv",
    role=Role.USER,
    aliases=["x srv"],
    short="Look up XMPP DNS SRV records.",
    usage="{prefix}xmpp srv <domain>",
    examples=["{prefix}x srv envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_srv(bot, sender_jid, nick, args, msg, is_room):
    """
    Perform DNS SRV lookups for XMPP services.

    Checks for:
    - _xmpp-client._tcp (Client-to-Server)
    - _xmpp-server._tcp (Server-to-Server)
    - _xmpps-client._tcp (XMPP over TLS)
    - _xmpps-server._tcp (XMPP-S Server)

    Usage:
        {prefix}xmpp srv <domain>
        {prefix}x srv <domain>

    Examples:
        {prefix}x srv example.com
        {prefix}x srv user@example.com    (uses example.com)
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    if not args or len(args) < 1:
        _reply_xmpp_srv_missing_domain(bot, msg)
        return

    domain = get_domain_from_jid(args[0])

    # Validate domain
    is_valid, error_msg = _validate_domain(domain)
    if not is_valid:
        _reply_xmpp_srv_invalid_domain(bot, msg, error_msg)
        return

    if "@" in args[0]:
        _reply_xmpp_srv_jid_notice(bot, msg, domain, args[0])

    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        _reply_xmpp_srv_dns_missing(bot, msg)
        return

    try:
        services = [
            '_xmpp-client._tcp',
            '_xmpp-server._tcp',
            '_xmpps-client._tcp',
            '_xmpps-server._tcp',
        ]

        resolver = _make_srv_resolver(dns.resolver, XMPP_QUERY_TIMEOUT_SECONDS)
        srv_records = await asyncio.to_thread(
            _collect_all_srv_records,
            domain,
            services,
            resolver,
            dns.exception,
        )

        result = _build_xmpp_srv_result(domain, services, srv_records)
        bot.reply(msg, result)

    except Exception as e:
        bot.reply(msg, f"🔴 DNS lookup failed: {e}")


def _xmpp_feature_summary(features) -> list[str]:
    feature_set = set(str(feature) for feature in (features or []))
    checks = [
        ("ping", "urn:xmpp:ping"),
        ("muc", "http://jabber.org/protocol/muc"),
        ("pubsub", "http://jabber.org/protocol/pubsub"),
        ("http-upload", "urn:xmpp:http:upload:0"),
        ("message-archive", "urn:xmpp:mam:2"),
        ("stream-mgmt", "urn:xmpp:sm:3"),
    ]
    return [name for name, feature in checks if feature in feature_set]


async def _xmpp_check_ping(bot, target: str) -> tuple[str, str]:
    try:
        start = time.monotonic()
        await bot.plugin["xep_0199"].ping(
            jid=target,
            timeout=XMPP_QUERY_TIMEOUT_SECONDS,
        )
        rtt = (time.monotonic() - start) * 1000
        return "✅", f"ping ok ({rtt:.1f} ms)"
    except slixmpp.exceptions.IqTimeout:
        return "🔴", "ping timed out"
    except slixmpp.exceptions.IqError as exc:
        return "⚠️", f"ping error: {_get_iq_error_condition(exc)}"
    except Exception as exc:
        return "🔴", f"ping failed: {exc}"


async def _xmpp_check_version(bot, target: str) -> tuple[str, str]:
    try:
        result = await bot.plugin["xep_0092"].get_version(
            jid=target,
            timeout=XMPP_QUERY_TIMEOUT_SECONDS,
        )
        name, version, os_info = _extract_xmpp_version_info(result)
        if name and version:
            return "✅", f"version: {_format_xmpp_version_info(name, version, os_info)}"
        return "ℹ️", "version: not advertised"
    except slixmpp.exceptions.IqTimeout:
        return "⚠️", "version: timed out"
    except slixmpp.exceptions.IqError as exc:
        condition = _get_iq_error_condition(exc)
        if condition == "service-unavailable":
            return "ℹ️", "version: unsupported"
        return "⚠️", f"version: {condition}"
    except Exception as exc:
        return "⚠️", f"version: {exc}"


async def _xmpp_check_disco(bot, target: str) -> tuple[str, str]:
    try:
        info = await bot.plugin["xep_0030"].get_info(
            jid=target,
            timeout=XMPP_QUERY_TIMEOUT_SECONDS,
        )
        disco_info = info.get("disco_info", {})
        identities = disco_info.get("identities", []) or []
        features = disco_info.get("features", []) or []
        known = _xmpp_feature_summary(features)
        summary = (
            f"disco ok: {len(identities)} identities, {len(features)} features"
        )
        if known:
            summary += f" ({', '.join(known)})"
        return "✅", summary
    except slixmpp.exceptions.IqTimeout:
        return "🔴", "disco timed out"
    except slixmpp.exceptions.IqError as exc:
        return "⚠️", f"disco error: {_get_iq_error_condition(exc)}"
    except Exception as exc:
        return "🔴", f"disco failed: {exc}"


def _xmpp_check_srv(domain: str) -> tuple[str, str]:
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        return "ℹ️", "SRV skipped: python-dnspython not installed"

    services = [
        '_xmpp-client._tcp',
        '_xmpp-server._tcp',
        '_xmpps-client._tcp',
        '_xmpps-server._tcp',
    ]
    try:
        resolver = _make_srv_resolver(dns.resolver, XMPP_QUERY_TIMEOUT_SECONDS)
        records = _collect_all_srv_records(domain, services, resolver, dns.exception)
    except Exception as exc:
        return "⚠️", f"SRV lookup failed: {exc}"

    found = [service for service, text in records.items() if "Not found" not in text and "Error" not in text]
    if found:
        return "✅", "SRV records: " + ", ".join(found)
    return "⚠️", "SRV records: none found"


@command(
    "xmpp check",
    role=Role.USER,
    aliases=["x check"],
    short="Run combined XMPP service and S2S TLS diagnostics.",
    usage="{prefix}xmpp check <domain|jid>",
    examples=["{prefix}x check envs.net", "{prefix}x check conference.envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_check(bot, sender_jid, nick, args, msg, is_room):
    """Run a compact XMPP health check for a domain or service JID."""
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    if not args:
        bot.reply(msg, f"❌ Missing target\nUsage: {config.get('prefix', ',')}x check <domain|jid>")
        return

    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    target = str(target).strip()
    domain = get_domain_from_jid(target).split('/', 1)[0]
    is_valid, error_msg = _validate_domain(domain)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid target: {error_msg}")
        return

    (
        (ping_status, ping_line),
        (disco_status, disco_line),
        (version_status, version_line),
        (srv_status, srv_line),
        (certificate_status, certificate_line),
    ) = await asyncio.gather(
        _xmpp_check_ping(bot, target),
        _xmpp_check_disco(bot, target),
        _xmpp_check_version(bot, target),
        asyncio.to_thread(_xmpp_check_srv, domain),
        _xmpp_check_certificate(domain),
    )

    lines = [
        f"🩺 XMPP check for {target}",
        f"{ping_status} {ping_line}",
        f"{disco_status} {disco_line}",
        f"{version_status} {version_line}",
        f"{srv_status} {srv_line}",
        f"{certificate_status} {certificate_line}",
    ]
    bot.reply(msg, lines)


@command(
    "xmpp compliance",
    role=Role.USER,
    aliases=["x compliance"],
    short="Check XMPP compliance features via disco.",
    usage="{prefix}xmpp compliance <jid>",
    examples=["{prefix}x compliance envs.net"],
    category="xmpp",
    context="any",
)
async def cmd_xmpp_compliance(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the compliance score of a server from compliance.conversations.im.

    Usage:
        {prefix}xmpp compliance <domain>
        {prefix}x compliance <domain>
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _get_enabled_rooms(bot, XMPP_KEY, "xmpp")
    if (is_room or _is_muc_pm(msg)) and msg["from"].bare not in enabled_rooms:
        return

    if not args or len(args) < 1:
        bot.reply(msg, "❌ Missing domain")
        return

    domain = get_domain_from_jid(args[0])

    # Validate domain
    is_valid, error_msg = _validate_domain(domain)
    if not is_valid:
        bot.reply(msg, f"❌ Invalid domain: {error_msg}")
        return

    if "@" in args[0]:
        bot.reply(msg, "Note: 'compliance' only works with domains. Using "
                       f"'{domain}' from '{args[0]}'.")

    try:
        url = f"https://compliance.conversations.im/server/{domain}/"
        resp = await fetch_preview(
            url,
            timeout_seconds=XMPP_HTTP_TIMEOUT_SECONDS,
            max_bytes=XMPP_COMPLIANCE_MAX_READ_BYTES,
            validator=passthrough_validator,
            raise_for_status=False,
            stop_when=_compliance_preview_complete,
        )
        if resp.status == 200:
            from bs4 import BeautifulSoup
            html_text = resp.body.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html_text, 'html.parser')
            score_elem = soup.find(class_='stat_result')
            if score_elem:
                score = score_elem.get_text(strip=True)
                result_url = (f"https://compliance.conversations.im"
                              f"/server/{domain}/")
                bot.reply(msg, f"✅ Compliance score for {domain}:"
                               f" **{score}**\nDetails: {result_url}")
            else:
                bot.reply(msg, "🔴 Could not extract compliance"
                               f" score for {domain}")
        elif resp.status == 404:
            bot.reply(msg, f"🔴 Server '{domain}' not found"
                           " in compliance database")
        else:
            bot.reply(msg, "🔴 Compliance database returned "
                           f"status {resp.status}")
    except asyncio.TimeoutError:
        bot.reply(msg, "🔴 Compliance request timed out.")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


def _enabled_rooms_from_state(state) -> set[str]:
    if not isinstance(state, dict):
        return set()
    return {
        str(room).split('/', 1)[0].strip().lower()
        for room, enabled in state.items()
        if enabled is True
    }


def _diagnostic_enabled_count(enabled_rooms: set[str], room_jid: str | None) -> int:
    if not room_jid:
        return len(enabled_rooms)
    target = str(room_jid).split('/', 1)[0].strip().lower()
    return sum(1 for room in enabled_rooms if room == target)


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int | float]:
    """Return small XMPP plugin counters for diagnostics."""
    enabled_state = await _get_enabled_rooms(
        bot, XMPP_KEY, "xmpp", [room_jid] if room_jid else ()
    )
    enabled_rooms = _enabled_rooms_from_state(enabled_state)
    return {
        "enabled_rooms": _diagnostic_enabled_count(enabled_rooms, room_jid),
        "joined_rooms": len(JOINED_ROOMS) if room_jid is None else int(str(room_jid).split('/', 1)[0].strip().lower() in JOINED_ROOMS),
        "query_timeout": XMPP_QUERY_TIMEOUT_SECONDS,
        "http_timeout": XMPP_HTTP_TIMEOUT_SECONDS,
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return XMPP plugin health lines."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ XMPP{scope}: enabled_rooms={state['enabled_rooms']}, "
        f"joined_rooms={state['joined_rooms']}, "
        f"query_timeout={state['query_timeout']:g}s, "
        f"http_timeout={state['http_timeout']:g}s"
    ]
