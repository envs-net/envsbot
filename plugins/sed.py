"""
SED plugin for message correction.

This plugin allows users to correct their previous messages using sed-like syntax.
Keeps only the last 10 messages per room in memory.

Commands:
    s/<pattern>/<replacement>/<flags> - Correct last message
    s#<pattern>#<replacement>#<flags> - Alternative delimiter
    {prefix}sed <pattern> <replacement> [flags] - Alternative syntax
    {prefix}sed on/off - Enable/disable sed plugin in this room (moderator only)
    {prefix}sed status - Show if sed is enabled in this room
"""
import re
import logging
import threading
from functools import partial
from collections import deque, defaultdict
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "sed",
    "version": "0.3.1",
    "description": "Message correction using sed-like syntax",
    "category": "tools",
    "requires": ["rooms"],
}

SED_KEY = "SED"
REGEX_TIMEOUT = 1.0  # second for regex substitution (0.2 - 2.0 good values)

# Store only last 10 messages per room
MESSAGE_CACHE = defaultdict(lambda: deque(maxlen=10))

# Track processed messages to avoid duplicates (use stanza_id instead of object id)
PROCESSED_STANZAS = set()


def get_stanza_id(msg):
    """Extract the stanza_id from a message."""
    stanza_id = msg.get('stanza_id')
    if stanza_id:
        return stanza_id.get('id')
    return None


def get_reply_target(msg):
    """Get the ID of the message this is a reply to."""
    if 'reply' in msg:
        reply = msg.get('reply')
        if reply:
            return reply.get('id')
    return None


def extract_reply_quote(body):
    """Extract the original message from a reply quote."""
    lines = body.strip().split('\n')
    quoted_lines = []

    for line in lines:
        if line.startswith('>'):
            # Remove the '> ' prefix
            quoted_lines.append(line[2:] if len(line) > 1 else "")
        else:
            break

    return '\n'.join(quoted_lines) if quoted_lines else None


def cache_message(room, nick, body, stanza_id):
    """Add message to cache (only keeps last 10 per room)."""
    MESSAGE_CACHE[room].append({
        'nick': nick,
        'body': body,
        'stanza_id': stanza_id
    })


def get_last_message(room):
    """Get the last message from cache."""
    if not MESSAGE_CACHE[room]:
        return None
    return MESSAGE_CACHE[room][-1]['body']


def get_message_by_id(room, msg_id):
    """Get a message by its stanza_id from cache."""
    if not MESSAGE_CACHE[room]:
        return None

    for msg_data in MESSAGE_CACHE[room]:
        if msg_data['stanza_id'] == msg_id:
            return msg_data['body']

    return None


def read_until_delimiter(raw_statement: str, delimiter: str, require: bool = True):
    """
    Read string until unescaped delimiter is found.
    Handles escaped delimiters (\\/).
    """
    value = ""
    while True:
        try:
            sep_index = raw_statement.index(delimiter)
        except ValueError:
            if require:
                raise ValueError(f"Delimiter '{delimiter}' not found")
            return raw_statement, value

        if sep_index == 0:
            return value, raw_statement[1:]
        elif raw_statement[sep_index - 1] == "\\":
            # Escaped delimiter, include it
            value += raw_statement[:sep_index - 1] + delimiter
            raw_statement = raw_statement[sep_index + 1:]
        else:
            # Unescaped delimiter found
            value += raw_statement[:sep_index]
            raw_statement = raw_statement[sep_index + 1:]
            return value, raw_statement


def parse_sed_command(text):
    """
    Parse sed-like command: s/pattern/replacement/flags or s#pattern#replacement#flags
    Returns (pattern, replacement, flags) or (None, None, None) on error
    """
    if not text.startswith('s'):
        return None, None, None

    if len(text) < 2:
        return None, None, None

    delimiter = text[1]

    # Only allow / or # as delimiters
    if delimiter not in ('/', '#'):
        return None, None, None

    try:
        raw_statement = text[2:]
        pattern, raw_statement = read_until_delimiter(raw_statement, delimiter)
        replacement, flags_str = read_until_delimiter(raw_statement, delimiter, require=False)
        return pattern, replacement, flags_str
    except ValueError:
        return None, None, None


def apply_sed(original_text, pattern, replacement, flags_str):
    """
    Apply sed substitution to text with timeout protection using threading.
    Thread-safe alternative to signal-based timeout.

    Flags:
        i - case insensitive
        m - multiline
        s - dotall
        g - global replace
        l - literal mode (treat pattern as literal string, not regex)
    """
    try:
        re_flags = 0
        global_replace = False
        literal_mode = False

        for flag in flags_str.lower():
            if flag == 'i':
                re_flags |= re.IGNORECASE
            elif flag == 'm':
                re_flags |= re.MULTILINE
            elif flag == 's':
                re_flags |= re.DOTALL
            elif flag == 'g':
                global_replace = True
            elif flag == 'l':
                literal_mode = True

        if literal_mode:
            pattern = re.escape(pattern)

        # Thread-safe timeout using threading.Timer
        result = [None, None]
        exception = [None]

        def do_regex():
            try:
                if global_replace:
                    result[0], result[1] = re.subn(pattern, replacement, original_text, flags=re_flags)
                else:
                    result[0], result[1] = re.subn(pattern, replacement, original_text, count=1, flags=re_flags)
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=do_regex, daemon=True)
        thread.start()
        thread.join(timeout=REGEX_TIMEOUT)

        if thread.is_alive():
            log.warning("[SED] Regex timeout - possible ReDoS attack: pattern=%s", pattern)
            return None, -1

        if exception[0]:
            if isinstance(exception[0], re.error):
                return None, 0
            raise exception[0]

        return result[0], result[1]
    except Exception as e:
        log.exception("[SED] Unexpected error in apply_sed: %s", e)
        return None, 0


async def get_sed_store(bot):
    """Get the database store for sed settings."""
    return bot.db.users.plugin("sed")


def is_sed_command(body):
    """Check if a message is a sed command (ignores reply quotes)."""
    lines = body.strip().split('\n')
    for line in lines:
        if not line.startswith('>'):
            # Check for s/pattern/replacement/ format
            if line.startswith('s') and len(line) > 2 and line[1] in ('/', '#'):
                return True
            # Check for ;sed CORRECTION format (not ;sed on/off/status)
            if line.startswith(';sed '):
                parts = line[5:].strip().split(None, 2)
                # Only treat as sed command if there are at least 2 parts (pattern + replacement)
                if len(parts) >= 2:
                    return True
    return False


def extract_sed_command(body):
    """Extract sed command from message body (removes reply quote if present)."""
    lines = body.strip().split('\n')
    for line in lines:
        if not line.startswith('>'):
            # If it's a ;sed command, convert it to s/pattern/replacement/ format
            if line.startswith(';sed '):
                # Extract the pattern and replacement from ";sed pattern replacement [flags]"
                parts = line[5:].strip().split(None, 2)
                if len(parts) >= 2:
                    pattern = parts[0]
                    replacement = parts[1]
                    flags = parts[2] if len(parts) > 2 else ""
                    return f"s/{pattern}/{replacement}/{flags}"
            return line.strip()
    return body.strip()


async def process_sed_correction(bot, nick, msg, is_room, pattern, replacement, flags_str):
    """Process a sed correction."""
    if is_room:
        room = msg['from'].bare
    else:
        # For DMs: remove the resource-ID
        room_full = str(msg['from'])
        room = room_full.split('/')[0] if '/' in room_full else room_full

    body = msg.get("body", "").strip()

    last_msg = None

    # 1. Try to extract from reply quote first (works for both rooms and DMs)
    if body.startswith('>'):
        quoted_msg = extract_reply_quote(body)
        if quoted_msg:
            last_msg = quoted_msg

    # 2. Try to get message from reply target ID (fallback)
    if not last_msg and is_room:
        reply_target_id = get_reply_target(msg)
        if reply_target_id:
            last_msg = get_message_by_id(room, reply_target_id)

    # 3. Fall back to last message in cache (works for both rooms and DMs)
    if not last_msg:
        last_msg = get_last_message(room)

    if not last_msg:
        bot.reply(msg, "❌ No previous message found to correct.")
        return

    try:
        new_msg, num_replacements = apply_sed(last_msg, pattern, replacement, flags_str)
    except Exception as e:
        bot.reply(msg, f"❌ Error applying sed: {e}")
        return

    if num_replacements == -1:
        # Timeout occurred
        bot.reply(msg, "⏱️ Regex timeout - pattern took too long to process!")
        return

    if new_msg is None:
        bot.reply(msg, f"❌ Regex error. Check your pattern: {pattern}")
        return

    if num_replacements == 0:
        bot.reply(msg, f"❌ Pattern '{pattern}' not found in last message.")
        return

    if is_room:
        response = f"> {last_msg}\n\n{new_msg}"
    else:
        response = new_msg

    bot.reply(msg, response, mention=False)


@command("sed", role=Role.USER)
async def cmd_sed_handler(bot, sender_jid, nick, args, msg, is_room):
    """
    Handle sed corrections or enable/disable sed in a room.

    Usage:
        {prefix}sed on|off              - Enable/disable sed (MUC DM only)
        {prefix}sed status              - Show if sed is enabled in this room (MUC DM only)
        {prefix}sed <pattern> <replacement> [flags] - Apply correction

    Examples:
        {prefix}sed hello hi
        {prefix}sed test prod g
        {prefix}sed -- xxx l
        {prefix}sed ERROR Error i
    """
    from_jid = msg["from"].bare
    is_muc_pm = from_jid in JOINED_ROOMS

    # Handle status command (MUC PM ONLY)
    if args and args[0] == "status":
        if is_room or not is_muc_pm:
            bot.reply(msg, "🔴 This command can only be used in a MUC DM.")
            return

        store = await get_sed_store(bot)
        enabled_rooms = await store.get_global(SED_KEY, default={})

        if from_jid in enabled_rooms and enabled_rooms[from_jid]:
            bot.reply(msg, "✅ SED corrections are **enabled** in this room.")
        else:
            bot.reply(msg, "🛑 SED corrections are **disabled** in this room.")
        return

    # Handle on/off commands (MUC PM ONLY)
    if args and args[0] in ("on", "off"):
        if is_room or not is_muc_pm:
            bot.reply(msg, "🔴 This command can only be used in a MUC DM.")
            return

        store = await get_sed_store(bot)
        enabled_rooms = await store.get_global(SED_KEY, default={})

        if args[0] == "on":
            if from_jid not in enabled_rooms or not enabled_rooms[from_jid]:
                enabled_rooms[from_jid] = True
                await store.set_global(SED_KEY, enabled_rooms)
                bot.reply(msg, "✅ SED corrections enabled in this room.")
                log.info(f"[SED] Room {from_jid} enabled")
            else:
                bot.reply(msg, "ℹ️ SED corrections already enabled.")
        else:
            if from_jid in enabled_rooms and enabled_rooms[from_jid]:
                del enabled_rooms[from_jid]
                await store.set_global(SED_KEY, enabled_rooms)
                bot.reply(msg, "🛑 SED corrections disabled in this room.")
                log.info(f"[SED] Room {from_jid} disabled")
            else:
                bot.reply(msg, "ℹ️ SED corrections already disabled.")
        return

    if not args or len(args) < 2:
        bot.reply(msg, "❌ Usage: {prefix}sed <pattern> <replacement> [flags]")
        return

    pattern = args[0]
    replacement = args[1]
    flags_str = args[2] if len(args) > 2 else ""

    await process_sed_correction(bot, msg.get("mucnick"), msg, is_room, pattern, replacement, flags_str)


async def on_message(bot, msg):
    """Handle sed commands and cache messages."""
    try:
        body = msg.get("body", "").strip()

        if not body:
            return

        if msg.get("from") == bot.boundjid:
            return

        # Use stanza_id for tracking instead of object id (more reliable)
        stanza_id = get_stanza_id(msg)
        if stanza_id and stanza_id in PROCESSED_STANZAS:
            return

        if stanza_id:
            PROCESSED_STANZAS.add(stanza_id)
            if len(PROCESSED_STANZAS) > 10000:
                PROCESSED_STANZAS.clear()

        is_room = msg.get("type") == "groupchat"
        nick = msg.get("mucnick") if is_room else None

        if is_room:
            room = msg['from'].bare
        else:
            # For DMs: remove the resource-ID
            room_full = str(msg['from'])
            room = room_full.split('/')[0] if '/' in room_full else room_full

        # Check if sed is enabled in rooms (always enabled for DMs)
        if is_room:
            store = await get_sed_store(bot)
            enabled_rooms = await store.get_global(SED_KEY, default={})
            if room not in enabled_rooms:
                return

            # Check if message is from the bot itself
            bot_nick = bot.presence.joined_rooms.get(room)
            if bot_nick and bot_nick == nick:
                return

        # Handle sed command BEFORE caching
        if is_sed_command(body):
            sed_cmd = extract_sed_command(body)
            pattern, replacement, flags_str = parse_sed_command(sed_cmd)

            if pattern is not None:
                await process_sed_correction(bot, nick, msg, is_room, pattern, replacement, flags_str)

            # Don't cache sed commands!
            return

        # Cache non-sed messages (keeps last 10 per room/user for both rooms and DMs)
        cache_message(room, nick, body, stanza_id)

    except Exception as e:
        log.exception("[SED] Error in on_message: %s", e)


async def on_load(bot):
    """Register the message event handler."""
    bot.bot_plugins.register_event(
        "sed",
        "groupchat_message",
        partial(on_message, bot)
    )

    bot.bot_plugins.register_event(
        "sed",
        "message",
        partial(on_message, bot)
    )
