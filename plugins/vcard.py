"""
vCard Lookup Plugin

Command: {prefix}vcard <nick>
Look up the vCard for a user by MUC nick (using only the MUC JID).

- Only available in groupchats or MUC PMs.
- Only uses the MUC JID (nick@room), never the real JID!
- Never displays or logs the user's real JID.
"""

import logging
import textwrap
from xml.etree import ElementTree as ET
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "vcard",
    "version": "0.1.0",
    "description": "Lookup and display vCard of a MUC occupant by MUC JID only",
    "category": "info",
    "requires": ["rooms"],
}


def _is_muc_pm(msg):
    """Returns True if msg is a MUC direct message (not public groupchat)."""
    return (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


def _get_all_field_values_by_tag(vcard, tag):
    """Extract all string values for the field 'tag' from vcard stanza children."""
    values = []
    for child in vcard.xml:
        # Check both namespace-tag form and plain tag
        if child.tag.endswith(tag) and child.text:
            values.append(child.text.strip())
    return values


def _format_vcard_reply(vcard, nick, muc_jid):
    lines = [f"📄 vCard for {nick} ({muc_jid}):"]

    fn = vcard.get("FN")
    if fn:
        lines.append(f"• Name: {fn}")
    nickname = vcard.get("NICKNAME")
    if nickname:
        lines.append(f"• Nickname: {nickname}")
    bday = vcard.get("BDAY")
    if bday:
        lines.append(f"• Birthday: {bday}")

    # All URLs
    urls = _get_all_field_values_by_tag(vcard, "URL")
    if urls: lines.append("")
    for url in urls:
        lines.append(f"• URL: {url}")

    # All Notes with wrapping
    notes = _get_all_field_values_by_tag(vcard, "NOTE")
    if notes: lines.append("")
    for note in notes:
        wrapped = textwrap.fill(
            note,
            width=70,
            initial_indent="• Note: ",
            subsequent_indent="        "
        )
        lines.append(wrapped)

    email = vcard.get("EMAIL")
    if email: lines.append("")  # Blank line before email
    if email is not None and hasattr(email, "get"):
        email_addr = email.get("USERID")
        if email_addr:
            lines.append(f"• Email: {email_addr}")

    adr = vcard.get("ADR")
    if adr:
        locality = adr.get("LOCALITY")
        if locality: lines.append("")  # Blank line before address
        ctry = adr.get("CTRY")
        vals = [val for val in (locality, ctry) if val]
        if vals:
            lines.append(f"• Address: {' '.join(vals)}")

    if len(lines) == 1:
        lines.append("  (no public vCard fields found)")
    return lines


@command("vcard", role=Role.USER)
async def vcard_command(bot, sender_jid, sender_nick, args, msg, is_room):
    """
    Look up the vCard of a user by MUC nick (MUC JID only), never real JID!

    Usage: {prefix}vcard <nick>
    Only available in groupchats or MUC DMs, and only for nicks present in
    this room.
    """
    prefix = config.get("prefix", ",")
    if not (is_room or _is_muc_pm(msg)):
        bot.reply(msg, f"🔴 This command is only available in groupchats or MUC DMs.")
        return

    if not args:
        bot.reply(msg, f"Usage: {prefix}vcard <nick>")
        return
    target_nick = " ".join(args).strip()

    room = msg["from"].bare  # MUC JID
    joined = JOINED_ROOMS.get(room, {})
    nicks = joined.get("nicks", {})
    if target_nick not in nicks:
        bot.reply(msg, f"🔴 Nick '{target_nick}' not found in this room.")
        log.info(f"[VCARD] Lookup failed: Nick '{target_nick}' not found in room {room}")
        return

    muc_jid = f"{room}/{target_nick}"
    log.info(f"[VCARD] Attempting vCard lookup for nick '{target_nick}' with MUC JID '{muc_jid}' in room '{room}'")

    try:
        vcard_plugin = bot.plugin.get("xep_0054", None)
        if not vcard_plugin:
            bot.reply(msg, "🔴 vCard support (xep_0054) is not enabled in this bot.")
            log.error("[VCARD] vCard XEP-0054 plugin not available")
            return
        result = await vcard_plugin.get_vcard(jid=muc_jid, cached=False, timeout=10)
        if not result:
            bot.reply(msg, f"ℹ️ No vCard found for {target_nick} ({muc_jid}).")
            log.info(f"[VCARD] No vCard found for '{target_nick}' ({muc_jid})")
            return

        vcard = result["vcard_temp"]
        lines = _format_vcard_reply(vcard, target_nick, muc_jid)
        bot.reply(msg, lines)
        log.info(f"[VCARD] vCard for '{target_nick}' ({muc_jid}) sent (never real jid!).")
    except Exception as e:
        bot.reply(msg, f"🔴 Failed to fetch vCard for {target_nick}: {e}")
        log.error(f"[VCARD] Exception during vCard lookup for '{target_nick}' ({muc_jid}): {e}")
