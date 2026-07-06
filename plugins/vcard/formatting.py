"""Split module for plugins/vcard.py: formatting."""

import logging
import textwrap
import pytz
import datetime
import urllib
from slixmpp.exceptions import IqError
from core_plugins import _core
from utils.command import command, Role
from utils.config import config
from core_plugins.rooms import JOINED_ROOMS


def _format_vcard_header(label, display_name, rooms=None):
    if rooms:
        return f"{label} - {display_name} in {', '.join(rooms)}:"
    return f"{label} - {display_name}:"


def _append_empty_vcard_value(lines):
    lines.append("    • —")


def _append_vcard_list_values(lines, values):
    for v in values:
        lines.append(f"    • {v}")


def _append_vcard_note_values(lines, note_value):
    # Preserve newlines in notes, wrap and indent each paragraph after
    # the bullet
    note_paragraphs = note_value.splitlines() or [""]
    first_line = True

    for para in note_paragraphs:
        wrapped = textwrap.wrap(para, width=70) or [""]
        for line in wrapped:
            if first_line:
                lines.append(f"    • {line}")
                first_line = False
            else:
                lines.append(f"      {line}")


async def _format_vcard_field_for_nick(field, label, values,
                                       display_name, rooms=None):
    lines = [_format_vcard_header(label, display_name, rooms)]

    if field == "URL":
        if values and isinstance(values, list):
            for v in values:
                lines.append(f"    • {urllib.parse.unquote(v)}")
        else:
            _append_empty_vcard_value(lines)
        return lines

    if field in ["EMAIL", "NICKNAME", "ORG", "NOTE"]:
        if values and isinstance(values, list):
            for v in values:
                if field == "NOTE":
                    _append_vcard_note_values(lines, v)
                else:
                    lines.append(f"    • {v}")
        else:
            _append_empty_vcard_value(lines)
        return lines

    # For any other field, output the value(s) in a readable way
    if values is None or values == "" or values == []:
        _append_empty_vcard_value(lines)
    elif isinstance(values, list):
        _append_vcard_list_values(lines, values)
    else:
        lines.append(f"    • {values}")

    return lines


def _vcard_value_is_empty(value):
    return value is None or value == "" or value == []


def _vcard_should_format_field(field):
    return field in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL",
                     "ORG", "NOTE", "EMAIL"]


def _vcard_reply_missing_nick(bot, msg, target_nick, room, own=False):
    if own:
        bot.reply(msg, f"🔴  Your Nick '{target_nick}' not found in this room.")
    else:
        bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")


def _vcard_reply_missing_field(bot, msg, label, target_nick, room):
    bot.reply(msg, f"🔴  No {label} found in vCard for nick '{target_nick}'.")


def _vcard_reply_empty_requested_user(bot, msg, label, target_nick):
    bot.reply(msg, f"ℹ️ No {label} set for nick '{target_nick}'.")


async def _vcard_reply_result(bot, msg, sender_jid, field, label,
                              value, display_name, room):
    log.info(f"[VCARD] {sender_jid} looking up {field} for"
             f"'{display_name}'")
    if _vcard_should_format_field(field):
        lines = await _format_vcard_field_for_nick(field, label, value,
                                                   display_name, [room])
        bot.reply(msg, lines)
    else:
        bot.reply(msg, f"{label} for {display_name}: {value}")


def _vcard_handle_missing_nick(bot, msg, target_nick, room, own=False):
    _vcard_reply_missing_nick(bot, msg, target_nick, room, own=own)


def _format_vcard_reply(vcard, nick, muc_jid):
    c = {}
    lines = [f"📄 vCard for {nick} ({muc_jid}):"]

    _append_name_info(vcard, lines, c)
    _append_nickname_info(vcard, lines, c)
    _append_birthday_info(vcard, lines, c)
    _append_url_info(vcard, lines, c)
    _append_org_info(vcard, lines, c)
    _append_note_info(vcard, lines, c)
    _append_email_info(vcard, lines, c)
    _append_address_info(vcard, lines, c)

    if len(lines) == 1:
        lines.append("  (no public vCard fields found)")
    return lines, c


def _append_name_info(vcard, lines, c):
    fn = vcard.get("FN")
    c["FN"] = None
    if fn:
        lines.append(f"• Name: {fn}")
        c["FN"] = fn


def _append_nickname_info(vcard, lines, c):
    nicknames = _get_all_field_values_by_tag(vcard, "NICKNAME")
    c["NICKNAME"] = []
    if nicknames:
        lines.append(f"• Nicknames: {nicknames}")
        c["NICKNAME"] = nicknames


def _append_birthday_info(vcard, lines, c):
    c["BDAY"] = None
    bday = vcard["BDAY"]
    if bday:
        lines.append(f"• Birthday: {bday}")
        c["BDAY"] = bday


def _append_url_info(vcard, lines, c):
    c["URL"] = []
    urls = _get_all_field_values_by_tag(vcard, "URL")
    if urls:
        lines.append("")
        c["URL"] = urls
    for url in urls:
        lines.append(f"• URL: {url}")


def _append_org_info(vcard, lines, c):
    c["ORG"] = []
    org_names = _get_nested_field_values_by_tag(vcard, "ORG", "ORGNAME")
    if org_names:
        lines.append("")
        for org in org_names:
            lines.append(f"• Organization: {org}")
            c["ORG"].append(org)


def _append_note_info(vcard, lines, c):
    c["NOTE"] = []
    notes = _get_all_field_values_by_tag(vcard, "NOTE")
    if notes:
        lines.append("")
        c["NOTE"] = notes
    for note in notes:
        note_paragraphs = note.splitlines() or [""]
        first_line = True
        for para in note_paragraphs:
            wrapped = textwrap.wrap(para, width=70)
            if not wrapped:
                wrapped = [""]
            for line in wrapped:
                if first_line:
                    lines.append(f"• Note: {line}")
                    first_line = False
                else:
                    lines.append(f"        {line}")


def _append_email_info(vcard, lines, c):
    c["EMAIL"] = []
    emails = _extract_email_addresses(vcard)
    if emails:
        lines.append("")
        c["EMAIL"] = emails
        for email_addr in emails:
            lines.append(f"• Email: {email_addr}")


def _append_address_info(vcard, lines, c):
    adr = vcard.get("ADR")
    c["LOCALITY"] = None
    c["REGION"] = None
    c["CTRY"] = None
    if adr:
        lines.append("")  # Blank line before address
        locality = adr.get("LOCALITY")
        if locality:
            c["LOCALITY"] = locality
        region = adr.get("REGION")
        if region:
            c["REGION"] = region
        ctry = adr.get("CTRY")
        if ctry:
            c["CTRY"] = ctry
        vals = [val for val in (locality, region, ctry) if val]
        if vals:
            lines.append(f"• Address: {' '.join(vals)}")
