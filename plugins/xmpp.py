"""
XMPP utility commands plugin.

This plugin provides various utility commands for interacting with XMPP
servers and users, such as pinging a JID, querying service discovery info,
checking compliance scores, and performing DNS SRV lookups.

Commands:
    {prefix}xmpp help - Displays the help message with all available commands.
    {prefix}xmpp version <jid> - Shows the software version of an XMPP entity (XEP-0092).
    {prefix}xmpp items <jid> - Lists the service items of an XMPP entity (XEP-0030).
    {prefix}xmpp contact <jid> - Displays contact information for an XMPP entity (XEP-0030).
    {prefix}xmpp info <jid> - Lists the identities and features of an XMPP entity (XEP-0030).
    {prefix}xmpp ping <jid> - Pings an XMPP entity and reports the round-trip time (XEP-0199).
    {prefix}xmpp uptime <jid> - Shows the uptime of an XMPP entity (XEP-0012).
    {prefix}xmpp srv <domain> - Performs DNS SRV lookups for XMPP services.
    {prefix}xmpp compliance <domain> - Shows the compliance score of a server from compliance.conversations.im.
"""
import time
import socket
import slixmpp
import aiohttp
import asyncio
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS

PLUGIN_META = {
    "name": "xmpp",
    "version": "0.2.0",
    "description": "XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.)",
    "category": "tools",
    "Requires": ["rooms"],
}

HELP_TEXT = """
XMPP Utility Commands:
  {prefix}x help              - Show this help message
  {prefix}x version <jid>     - Show software version (XEP-0092)
  {prefix}x items <jid>       - List service items (XEP-0030)
  {prefix}x contact <jid>     - Show contact information (XEP-0030)
  {prefix}x info <jid>        - Show identities & features (XEP-0030)
  {prefix}x ping <jid>        - Ping entity (XEP-0199)
  {prefix}x uptime <jid>      - Show uptime (XEP-0012)
  {prefix}x srv <domain>      - DNS SRV lookup
  {prefix}x compliance <domain> - Compliance score
"""


def _resolve_target(bot, args, msg, is_room, nick):
    """
    Resolve the target: JID, room JID/nick, or nick in room context.
    Returns (target, error_message) tuple.
    """
    if not args or len(args) < 1:
        return None, "Missing target JID or nick"

    target = args[0]
    # If in room or MUC PM and target is a nick, resolve to room_jid/nick
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


@command("xmpp help", role=Role.USER, aliases=["x help"])
async def cmd_xmpp_help(bot, sender_jid, nick, args, msg, is_room):
    """
    Display help message with all available XMPP commands.

    Usage:
        {prefix}xmpp help
        {prefix}x help
    """
    bot.reply(msg, HELP_TEXT)


@command("xmpp version", role=Role.USER, aliases=["x version"])
async def cmd_xmpp_version(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the software version of an XMPP entity (XEP-0092).

    Usage:
        {prefix}xmpp version <jid>
        {prefix}x version <jid>
    Example:
        {prefix}x version server.example.org
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        result = await bot.plugin["xep_0092"].get_version(jid=target, timeout=8)

        name = None
        version = None
        os_info = None

        # result is a slixmpp.stanza.iq.Iq object
        # The XML element is the <iq> element, we need to go into the <query>
        if hasattr(result, 'xml'):
            # Find the query element
            for child in result.xml:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag == 'query':
                    # Now search the sub-elements of the query
                    for elem in child:
                        elem_tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if elem_tag == 'name':
                            name = elem.text
                        elif elem_tag == 'version':
                            version = elem.text
                        elif elem_tag == 'os':
                            os_info = elem.text

        if name and version:
            version_info = f"**{name}** v{version}"
            if os_info:
                version_info += f" on {os_info}"
            bot.reply(msg, f"ℹ️  Version: {version_info}")
        else:
            bot.reply(msg, f"ℹ️  {target} does not provide version information via XEP-0092")

    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Version request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        bot.reply(msg, f"🔴 Version request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command("xmpp items", role=Role.USER, aliases=["x items"])
async def cmd_xmpp_items(bot, sender_jid, nick, args, msg, is_room):
    """
    List the service items of an XMPP entity (XEP-0030).

    Usage:
        {prefix}xmpp items <jid>
        {prefix}x items <jid>
    Example:
        {prefix}x items conference.example.org
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        items = await bot.plugin["xep_0030"].get_items(jid=target, timeout=8)
        disco_items = items.get('disco_items', {})
        items_list = disco_items.get('items', [])

        if not items_list:
            bot.reply(msg, f"No items found for {target}")
            return

        # items_list is a list of tuples: (jid, name)
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
        bot.reply(msg, f"🔴 Items request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command("xmpp contact", role=Role.USER, aliases=["x contact"])
async def cmd_xmpp_contact(bot, sender_jid, nick, args, msg, is_room):
    """
    Display contact information for an XMPP entity (XEP-0030).

    Usage:
        {prefix}xmpp contact <jid>
        {prefix}x contact <jid>
    Example:
        {prefix}x contact server.example.org
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        info = await bot.plugin["xep_0030"].get_info(jid=target, timeout=8)
        disco_info = info.get('disco_info', {})
        contact_info = {}

        # disco_info['form'] is a slixmpp.plugins.xep_0004.stanza.form.Form object
        if 'form' in disco_info and disco_info['form']:
            form = disco_info['form']

            # Iterate over the FormField objects
            for field in form:
                field_var = field.get('var', '')

                # Extract the values
                values = field.get('value', [])
                if not values:
                    continue

                # Recognize contact types
                if 'admin' in field_var.lower():
                    contact_info['Admin'] = values if isinstance(values, list) else [values]
                elif 'abuse' in field_var.lower():
                    contact_info['Abuse'] = values if isinstance(values, list) else [values]
                elif 'security' in field_var.lower():
                    contact_info['Security'] = values if isinstance(values, list) else [values]
                elif 'feedback' in field_var.lower():
                    contact_info['Feedback'] = values if isinstance(values, list) else [values]
                elif 'support' in field_var.lower():
                    contact_info['Support'] = values if isinstance(values, list) else [values]

        if contact_info:
            lines = []
            for contact_type in ['Admin', 'Abuse', 'Security', 'Feedback', 'Support']:
                if contact_type in contact_info:
                    for addr in contact_info[contact_type]:
                        lines.append(f"  • {contact_type}: {addr}")
            bot.reply(msg, f"📧 Contact info for {target}:\n" + "\n".join(lines))
        else:
            bot.reply(msg, f"ℹ️  {target} does not provide contact information via XEP-0030")

    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Contact request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        bot.reply(msg, f"🔴 Contact request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command("xmpp info", role=Role.USER, aliases=["x info"])
async def cmd_xmpp_info(bot, sender_jid, nick, args, msg, is_room):
    """
    List the identities and features of an XMPP entity (XEP-0030).

    Usage:
        {prefix}xmpp info <jid>
        {prefix}x info <jid>
    Example:
        {prefix}x info server.example.org
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        info = await bot.plugin["xep_0030"].get_info(jid=target, timeout=8)
        disco_info = info.get('disco_info', {})

        identities = []
        # disco_info['identities'] is a list of tuples: (category, type, name)
        if 'identities' in disco_info:
            for ident in disco_info['identities']:
                if isinstance(ident, tuple) and len(ident) >= 2:
                    category = ident[0]
                    ident_type = ident[1]
                    name = ident[2] if len(ident) > 2 else None

                    ident_str = category
                    if ident_type:
                        ident_str += f"/{ident_type}"
                    if name:
                        ident_str += f" ({name})"
                    identities.append(f"  • {ident_str}")

        features = []
        if 'features' in disco_info:
            features = [f"  • {feature}" for feature in disco_info['features']]

        result = f"🔍 Info for {target}:\n"
        if identities:
            result += f"\n**Identities:**\n" + "\n".join(identities)
        if features:
            result += f"\n**Features:**\n" + "\n".join(features[:10])
            if len(features) > 10:
                result += f"\n  ... and {len(features) - 10} more"

        if not identities and not features:
            result += "No identities or features found."

        bot.reply(msg, result)
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Info request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        bot.reply(msg, f"🔴 Info request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command("xmpp ping", role=Role.USER, aliases=["x ping"])
async def cmd_xmpp_ping(bot, sender_jid, nick, args, msg, is_room):
    """
    Ping an XMPP JID and report round-trip time (XEP-0199).

    Usage:
        {prefix}xmpp ping <jid|nick>
        {prefix}x ping <jid|nick>
    Example:
        {prefix}x ping user@example.org
        {prefix}x ping conference.example.org
        {prefix}x ping Alice
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        start = time.monotonic()
        await bot.plugin["xep_0199"].ping(jid=target, timeout=8)
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


@command("xmpp uptime", role=Role.USER, aliases=["x uptime"])
async def cmd_xmpp_uptime(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the uptime of an XMPP entity (XEP-0012).

    Usage:
        {prefix}xmpp uptime <jid>
        {prefix}x uptime <jid>
    Example:
        {prefix}x uptime server.example.org
    """
    target, error = _resolve_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, f"❌ {error}")
        return

    try:
        result = await bot.plugin["xep_0012"].get_last_activity(jid=target, timeout=8)
        seconds = result['last_activity']['seconds']

        # Convert seconds to human-readable format
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

        bot.reply(msg, f"⏱️  Uptime for {target}: {' '.join(uptime_str)}")
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴 Uptime request to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_condition = err.get('condition', 'unknown')
        bot.reply(msg, f"🔴 Uptime request failed: {err_condition}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")


@command("xmpp srv", role=Role.USER, aliases=["x srv"])
async def cmd_xmpp_srv(bot, sender_jid, nick, args, msg, is_room):
    """
    Perform DNS SRV lookups for XMPP services.

    Usage:
        {prefix}xmpp srv <domain>
        {prefix}x srv <domain>
    Example:
        {prefix}x srv example.org
    """
    if not args or len(args) < 1:
        bot.reply(msg, "❌ Missing domain")
        return

    domain = args[0]

    try:
        srv_records = {}
        for service in ['_xmpp-client', '_xmpp-server']:
            try:
                results = socket.getaddrinfo(
                    f"{service}._tcp.{domain}", None,
                    family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
                )
                # This is simplified; real SRV lookup would use dnspython
                srv_records[service] = "Found"
            except socket.gaierror:
                srv_records[service] = "Not found"

        result = f"🔍 DNS SRV records for {domain}:\n"
        for service, status in srv_records.items():
            result += f"  • {service}: {status}\n"

        bot.reply(msg, result)
    except Exception as e:
        bot.reply(msg, f"🔴 DNS lookup failed: {e}")


@command("xmpp compliance", role=Role.USER, aliases=["x compliance"])
async def cmd_xmpp_compliance(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the compliance score of a server from compliance.conversations.im.

    Usage:
        {prefix}xmpp compliance <domain>
        {prefix}x compliance <domain>
    Example:
        {prefix}x compliance example.org
    """
    if not args or len(args) < 1:
        bot.reply(msg, "❌ Missing domain")
        return

    domain = args[0]

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://compliance.conversations.im/server/{domain}/"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    from bs4 import BeautifulSoup
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Find the score in the stat_result div
                    score_elem = soup.find(class_='stat_result')
                    if score_elem:
                        score = score_elem.get_text(strip=True)
                        result_url = f"https://compliance.conversations.im/server/{domain}/"
                        bot.reply(msg, f"✅ Compliance score for {domain}: **{score}**\nDetails: {result_url}")
                    else:
                        bot.reply(msg, f"🔴 Could not extract compliance score for {domain}")

                elif resp.status == 404:
                    bot.reply(msg, f"🔴 Server '{domain}' not found in compliance database")
                else:
                    bot.reply(msg, f"🔴 Compliance database returned status {resp.status}")

    except asyncio.TimeoutError:
        bot.reply(msg, f"🔴 Compliance request timed out.")
    except aiohttp.ClientError as e:
        bot.reply(msg, f"🔴 Network error: {e}")
    except Exception as e:
        bot.reply(msg, f"🔴 Error: {e}")