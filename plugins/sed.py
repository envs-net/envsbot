"""SED plugin for message correction.

Allows users to correct previous messages using sed-like syntax.

IMPORTANT: You must enable SED corrections in a room for this to work.
Use this command to turn it on/off or show its status:
    {prefix}sed <on|off|status>

Commands:
• s/pattern/replacement/flags
• s#pattern#replacement#flags
• {prefix}sed <pattern> <replacement> [flags]
• {prefix}sed on/off/status

Flags:
• i - case insensitive
• m - multiline
• s - dotall
• g - global replace
• l - literal mode
"""

import logging
import multiprocessing
import queue
import re
import shlex
from collections.abc import Collection
from functools import partial

from core_plugins import _core
from utils import message_cache
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.config import config

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "sed",
    "version": "0.5.0",
    "description": "Message correction using sed-like syntax",
    "category": "tools",
    "requires": ["rooms", "_core"],
}

SED_KEY = "SED"
HANDLER_NAMESPACE = "sed-handler"

# Hard timeout for regex substitution.
REGEX_TIMEOUT = float(config.get("sed_regex_timeout", 1.0) or 1.0)

# Practical limits to reduce abuse.
MAX_PATTERN_LENGTH = int(config.get("sed_max_pattern_length", 256) or 256)
MAX_REPLACEMENT_LENGTH = int(config.get("sed_max_replacement_length", 1000) or 1000)
MAX_INPUT_LENGTH = int(config.get("sed_max_input_length", 5000) or 5000)
MAX_OUTPUT_LENGTH = int(config.get("sed_max_output_length", 8000) or 8000)


def _is_sed_command_entry(entry: dict) -> bool:
    body = str(entry.get("body") or "").strip()
    pattern, _replacement, _flags = parse_any_sed_command(body)
    return pattern is not None


def get_last_message(
    bot,
    conversation: str,
    *,
    exclude_stanza_id: str | None = None,
):
    """Get the latest non-sed message from the central cache."""
    entry = bot.message_cache.get_last(
        conversation,
        predicate=lambda cached: not _is_sed_command_entry(cached),
        exclude_stanza_id=exclude_stanza_id,
    )
    if not entry:
        return None
    return entry.get("body")


def get_message_by_id(bot, conversation: str, msg_id: str):
    """Get a message by stanza ID from the central cache."""
    entry = bot.message_cache.get_by_id(conversation, msg_id)
    if not entry:
        return None
    return entry.get("body")


def _room_key_from_msg(bot, msg, is_room: bool) -> str | None:
    return message_cache.conversation_key(
        msg,
        is_room=is_room,
        joined_rooms=bot.presence.joined_rooms,
    )


# ============================================================================
# SED PARSING
# ============================================================================

def read_until_delimiter(raw_statement: str, delimiter: str,
                         require: bool = True):
    """Read until an unescaped delimiter is found."""
    value = ""

    while True:
        try:
            sep_index = raw_statement.index(delimiter)
        except ValueError as exc:
            if require:
                raise ValueError(f"Delimiter '{delimiter}' not found") from exc

            return raw_statement, value

        if sep_index == 0:
            return value, raw_statement[1:]

        if raw_statement[sep_index - 1] == "\\":
            value += raw_statement[:sep_index - 1] + delimiter
            raw_statement = raw_statement[sep_index + 1:]
        else:
            value += raw_statement[:sep_index]
            raw_statement = raw_statement[sep_index + 1:]
            return value, raw_statement


def parse_sed_command(text: str):
    """Parse s/pattern/replacement/flags or s#pattern#replacement#flags.

    Returns:
        (pattern, replacement, flags) or (None, None, None)
    """
    if not text.startswith("s"):
        return None, None, None

    if len(text) < 2:
        return None, None, None

    delimiter = text[1]

    if delimiter not in ("/", "#"):
        return None, None, None

    try:
        raw_statement = text[2:]
        pattern, raw_statement = read_until_delimiter(raw_statement, delimiter)
        replacement, flags_str = read_until_delimiter(
            raw_statement,
            delimiter,
            require=False,
        )
        return pattern, replacement, flags_str

    except ValueError:
        return None, None, None


def _command_prefix() -> str:
    return config.get("prefix", ",")


def parse_prefixed_sed_command(text: str):
    """
    Parse '{prefix}sed <pattern> <replacement> [flags]' with shell-like
    quoting.

    Examples:
        ,sed foo bar
        ,sed 'lat(.*)' ''
        ,sed '++' '--' l
        ,sed "\\+\\+" -- g
    """
    prefix = _command_prefix()
    prefixed = f"{prefix}sed "

    if not text.startswith(prefixed):
        return None, None, None

    rest = text[len(prefixed):].strip()

    if not rest:
        return None, None, None

    try:
        parts = shlex.split(rest)
    except ValueError:
        return None, None, None

    if not parts:
        return None, None, None

    cmd = parts[0].lower()

    if cmd in {"on", "off", "status"} and len(parts) == 1:
        return None, None, None

    if len(parts) < 2:
        return None, None, None

    pattern = parts[0]
    replacement = parts[1]
    flags_str = "".join(parts[2:]) if len(parts) > 2 else ""

    return pattern, replacement, flags_str


def parse_any_sed_command(body: str):
    """Parse either inline sed syntax or prefixed sed syntax.

    Ignores leading reply quote lines.
    """
    lines = body.strip().split("\n")

    for line in lines:
        if line.startswith(">"):
            continue

        stripped = line.strip()

        if not stripped:
            continue

        pattern, replacement, flags_str = parse_sed_command(stripped)

        if pattern is not None:
            return pattern, replacement, flags_str

        pattern, replacement, flags_str = parse_prefixed_sed_command(stripped)

        if pattern is not None:
            return pattern, replacement, flags_str

        return None, None, None

    return None, None, None


def is_sed_command(body: str) -> bool:
    """Check if a message is a sed command, ignoring reply quotes."""
    pattern, replacement, flags_str = parse_any_sed_command(body)
    return pattern is not None


# ============================================================================
# REGEX APPLICATION
# ============================================================================

def _regex_worker(result_queue, original_text, pattern, replacement,
                  flags_str):
    """Run regex substitution in a child process.

    This gives us a real timeout: the parent can terminate the process.
    """
    try:
        re_flags = 0
        global_replace = False
        literal_mode = False

        for flag in flags_str.lower():
            if flag == "i":
                re_flags |= re.IGNORECASE
            elif flag == "m":
                re_flags |= re.MULTILINE
            elif flag == "s":
                re_flags |= re.DOTALL
            elif flag == "g":
                global_replace = True
            elif flag == "l":
                literal_mode = True

        if literal_mode:
            pattern = re.escape(pattern)

        count = 0 if global_replace else 1
        new_text, num_replacements = re.subn(
            pattern,
            replacement,
            original_text,
            count=count,
            flags=re_flags,
        )

        result_queue.put(("ok", new_text, num_replacements))

    except re.error as exc:
        result_queue.put(("regex_error", str(exc), 0))

    except Exception as exc:
        result_queue.put(("error", str(exc), 0))


def _validate_sed_inputs(original_text: str, pattern: str, replacement: str,
                         flags_str: str):
    if len(original_text) > MAX_INPUT_LENGTH:
        original_text = original_text[:MAX_INPUT_LENGTH]

    if len(pattern) > MAX_PATTERN_LENGTH:
        return None, None, None, None, (None, 0)

    if len(replacement) > MAX_REPLACEMENT_LENGTH:
        return None, None, None, None, (None, 0)

    valid_flags = {"i", "m", "s", "g", "l"}
    for flag in flags_str.lower():
        if flag not in valid_flags:
            return None, None, None, None, (None, 0)

    return original_text, pattern, replacement, flags_str, None


def _apply_literal_sed_direct(original_text: str, pattern: str, replacement: str, flags_str: str):
    """Apply literal-mode sed without process startup overhead."""
    re_flags = 0
    global_replace = False
    for flag in flags_str.lower():
        if flag == "i":
            re_flags |= re.IGNORECASE
        elif flag == "m":
            re_flags |= re.MULTILINE
        elif flag == "s":
            re_flags |= re.DOTALL
        elif flag == "g":
            global_replace = True
    count = 0 if global_replace else 1
    try:
        new_text, num_replacements = re.subn(
            re.escape(pattern),
            replacement,
            original_text,
            count=count,
            flags=re_flags,
        )
    except re.error:
        return None, 0
    if len(new_text) > MAX_OUTPUT_LENGTH:
        new_text = new_text[:MAX_OUTPUT_LENGTH] + "…"
    return new_text, num_replacements

def _multiprocessing_context():
    """Return a safe multiprocessing context for regex isolation.

    Avoid the plain fork start method: in a threaded asyncio bot, Python
    3.13 warns that forking can deadlock.  Prefer forkserver where
    available because it keeps the fast copy-on-write behavior without
    forking the active bot process; fall back to spawn on platforms that
    do not offer forkserver.
    """
    available_methods = multiprocessing.get_all_start_methods()

    for method in ("forkserver", "spawn"):
        if method in available_methods:
            return multiprocessing.get_context(method)

    return multiprocessing.get_context()


def _run_sed_worker(original_text: str, pattern: str, replacement: str,
                    flags_str: str):
    ctx = _multiprocessing_context()
    result_queue = ctx.Queue(maxsize=1)

    process = ctx.Process(
        target=_regex_worker,
        args=(
            result_queue,
            original_text,
            pattern,
            replacement,
            flags_str,
        ),
    )

    process.start()
    process.join(REGEX_TIMEOUT)

    if process.is_alive():
        process.terminate()
        process.join(0.2)

        if process.is_alive():
            process.kill()
            process.join(0.2)

        return None, -1, pattern

    return result_queue, 0, pattern


def _collect_sed_result(result_queue, pattern: str):
    try:
        status, value, num_replacements = result_queue.get_nowait()
    except queue.Empty:
        return None, 0

    if status == "ok":
        if len(value) > MAX_OUTPUT_LENGTH:
            value = value[:MAX_OUTPUT_LENGTH] + "…"
        return value, num_replacements

    if status == "regex_error":
        log.debug("[SED] Regex error for pattern=%r: %s", pattern, value)
        return None, 0

    log.warning("[SED] Regex worker error for pattern=%r: %s", pattern, value)
    return None, 0


def apply_sed(original_text: str, pattern: str, replacement: str,
              flags_str: str):
    """Apply sed substitution with hard timeout protection.

    Returns:
        (new_text, num_replacements)
        (None, -1) on timeout
        (None, 0) on regex/validation error
    """
    try:
        original_text, pattern, replacement, flags_str, early_return = (
            _validate_sed_inputs(original_text, pattern, replacement,
                                 flags_str)
        )
        if early_return is not None:
            return early_return

        if "l" in flags_str.lower():
            return _apply_literal_sed_direct(
                original_text, pattern, replacement, flags_str
            )

        result_queue, timeout_code, pattern = _run_sed_worker(
            original_text, pattern, replacement, flags_str
        )
        if timeout_code == -1:
            log.warning("[SED] Regex timeout - possible ReDoS pattern=%r",
                        pattern)
            return None, -1

        return _collect_sed_result(result_queue, pattern)

    except Exception as exc:
        log.exception("[SED] Unexpected error in apply_sed: %s", exc)
        return None, 0


# ============================================================================
# BOT INTEGRATION
# ============================================================================

async def get_sed_store(bot):
    """Get the database store for sed settings."""
    return bot.db.users.plugin("sed")


def _is_direct_dm(msg, is_room: bool) -> bool:
    """Return True for normal 1:1 DMs, but not MUC PMs."""
    return (not is_room) and (msg["from"].bare not in _core.JOINED_ROOMS)


def _sed_reply(bot, msg, text: str, is_room: bool):
    """Reply from sed.

    Disable thread in normal DMs to avoid duplicate rendering.
    """
    bot.reply(
        msg,
        text,
        mention=False,
        thread=not _is_direct_dm(msg, is_room),
    )


async def process_sed_correction(
    bot,
    nick,
    msg,
    is_room: bool,
    pattern: str,
    replacement: str,
    flags_str: str,
):
    """Process a sed correction."""
    room = _room_key_from_msg(bot, msg, is_room)
    body = msg.get("body", "").strip()
    last_msg = None

    if body.startswith(">"):
        quoted_msg = _core.extract_reply_quote(body)

        if quoted_msg:
            last_msg = quoted_msg

    if not last_msg and is_room:
        reply_target_id = _core.get_reply_target(msg)

        if reply_target_id and room:
            last_msg = get_message_by_id(bot, room, reply_target_id)

    if not last_msg and room:
        last_msg = get_last_message(
            bot,
            room,
            exclude_stanza_id=_core.get_stanza_id(msg),
        )

    if not last_msg:
        _sed_reply(bot, msg,
                   "❌ No previous message found to correct.", is_room)
        return

    new_msg, num_replacements = apply_sed(
        last_msg,
        pattern,
        replacement,
        flags_str,
    )

    if num_replacements == -1:
        _sed_reply(
            bot,
            msg,
            "⏱️ Regex timeout - pattern took too long to process.",
            is_room,
        )
        return

    if new_msg is None:
        _sed_reply(
            bot,
            msg,
            f"❌ Regex error or invalid sed expression. Check your pattern: {
                pattern}",
            is_room,
        )
        return

    if num_replacements == 0:
        _sed_reply(
            bot,
            msg,
            f"❌ Pattern '{pattern}' not found in last message.",
            is_room,
        )
        return

    if is_room:
        response = f"> {last_msg}\n\n{new_msg}"
    else:
        response = new_msg

    _sed_reply(bot, msg, response, is_room)


@command(
    "sed",
    role=Role.USER,
    short="Apply sed-style corrections or control room access to sed.",
    usage="{prefix}s/old/new/ or {prefix}sed <on|off|status>",
    subcommands=[
        help_subcommand(
            "<correction>",
            "{prefix}s/old/new/[flags]",
            "Correct your most recent matching message with sed-style syntax.",
            examples=[
                help_example(
                    "{prefix}s/teh/the/",
                    "Replace 'teh' with 'the' in your latest matching message.",
                )
            ],
        ),
        *room_toggle_subcommands("sed", "sed corrections"),
    ],
    examples=[
        "{prefix}s/teh/the/",
        "{prefix}sed status",
        "{prefix}rooms enable sed",
    ],
    category="utility",
    context="any",
)
async def cmd_sed_handler(bot, sender_jid, nick, args, msg, is_room):
    """Handle sed corrections or enable/disable sed in a room."""
    if await _core.handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_sed_store,
        key=SED_KEY,
        label="SED corrections",
        plugin="sed",
        storage="dict",
        log_prefix="[SED]",
    ):
        return

    prefix = _command_prefix()
    pattern, replacement, flags_str = parse_prefixed_sed_command(
        msg.get("body", "").strip()
    )

    if pattern is None:
        bot.reply(
            msg,
            f"❌ Usage: {prefix}sed <pattern> <replacement> [flags]",
        )
        return

    await process_sed_correction(
        bot,
        msg.get("mucnick"),
        msg,
        is_room,
        pattern,
        replacement,
        flags_str,
    )


async def on_message(bot, msg):
    """Handle sed commands; the core owns message caching."""
    try:
        body = msg.get("body", "").strip()

        if not body:
            return

        if msg.get("from") == bot.boundjid:
            return

        stanza_id = _core.get_stanza_id(msg)

        if not _core.remember_stanza(HANDLER_NAMESPACE, stanza_id):
            return

        is_room = msg.get("type") == "groupchat"
        nick = msg.get("mucnick") if is_room else None
        room = _room_key_from_msg(bot, msg, is_room)

        if is_room:
            if not room:
                return
            if not await _core._is_enabled_for_room(
                bot, SED_KEY, "sed", room
            ):
                return

            bot_nick = bot.presence.joined_rooms.get(room)

            if bot_nick and bot_nick == nick:
                return

        pattern, replacement, flags_str = parse_any_sed_command(body)

        if pattern is not None:
            await process_sed_correction(
                bot,
                nick,
                msg,
                is_room,
                pattern,
                replacement,
                flags_str,
            )
            return

    except Exception as exc:
        log.exception("[SED] Error in on_message: %s", exc)


async def on_load(bot):
    """Register the message event handlers."""
    bot.bot_plugins.register_event(
        "sed",
        "groupchat_message",
        partial(on_message, bot),
    )
    bot.bot_plugins.register_event(
        "sed",
        "message",
        partial(on_message, bot),
    )


def _diagnostic_enabled_count(enabled_rooms: Collection[str], room_jid: str | None) -> int:
    if not room_jid:
        return len(enabled_rooms)
    target = str(room_jid).split('/', 1)[0].strip().lower()
    return sum(
        1 for room in enabled_rooms
        if str(room).split('/', 1)[0].strip().lower() == target
    )


def _sed_cache_counts(bot, room_jid: str | None = None) -> tuple[int, int]:
    stats = bot.message_cache.stats(room_jid)
    return int(stats["conversations"]), int(stats["messages"])


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int | float]:
    """Return small sed counters for diagnostics."""
    enabled_rooms = await _core._get_enabled_rooms(
        bot, SED_KEY, "sed", [room_jid] if room_jid else ()
    )
    cached_rooms, cached_messages = _sed_cache_counts(bot, room_jid)
    return {
        "enabled_rooms": _diagnostic_enabled_count(enabled_rooms, room_jid),
        "cached_rooms": cached_rooms,
        "cached_messages": cached_messages,
        "cache_size": bot.message_cache.max_messages,
        "regex_timeout": REGEX_TIMEOUT,
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return sed plugin health lines."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ Sed{scope}: enabled_rooms={state['enabled_rooms']}, "
        f"cached_rooms={state['cached_rooms']}, "
        f"cached_messages={state['cached_messages']}, "
        f"cache_size={state['cache_size']}, "
        f"regex_timeout={state['regex_timeout']:g}s"
    ]
