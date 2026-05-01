"""
Room-local karma plugin with nick++ / nick-- tracking.

Provides simple room-local karma tracking using patterns like:

    nick++
    nick--

Control:
    {prefix}karma on|off|status   - Enable/disable karma in this room (MUC DM only)

Queries:
    {prefix}karma <nick>          - Show karma for a nick in this room
    {prefix}karma top             - Show top karma in this room
    {prefix}karma bottom          - Show lowest karma in this room

Behavior:
- Karma processing only works in public MUCs.
- on/off/status only works in MUC private messages to the bot.
- Karma is tracked per room.
- Default should be OFF via plugins.rooms PLUGIN_DEFAULTS.
- Self-karma is ignored.
- Bot-karma is ignored.
- Duplicate karma for the same nick in a single message is ignored.
"""

import logging
import re

from functools import partial
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS
from plugins import _core

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "karma",
    "version": "1.0.0",
    "description": "Room-local karma tracking with nick++ / nick--",
    "category": "fun",
    "requires": ["rooms", "_core"],
}

KARMA_ENABLED_KEY = "KARMA"
KARMA_SCORES_KEY = "scores"

# Find candidate ++ / -- operators in the text.
# Nick resolution is done separately against known room nicks.
OP_RE = re.compile(r"(\+\+|--)")

# Characters we trim from fallback nick matches.
TRIM_CHARS = " \t\r\n,;:!?.()[]{}<>\"'“”„‚`´"


async def get_karma_store(bot):
    return bot.db.users.plugin("karma")


async def _get_enabled_rooms(bot) -> dict:
    store = await get_karma_store(bot)
    data = await store.get_global(KARMA_ENABLED_KEY, default={})
    return data if isinstance(data, dict) else {}


async def _is_enabled_for_room(bot, room_jid: str) -> bool:
    enabled = await _get_enabled_rooms(bot)
    return bool(enabled.get(room_jid))


async def _get_room_scores(bot, room_jid: str) -> dict:
    store = await get_karma_store(bot)
    data = await store.get_global(KARMA_SCORES_KEY, default={})

    if not isinstance(data, dict):
        data = {}

    room_scores = data.get(room_jid, {})
    if not isinstance(room_scores, dict):
        room_scores = {}

    normalized = {}
    for nick, value in room_scores.items():
        try:
            normalized[str(nick)] = int(value)
        except Exception:
            normalized[str(nick)] = 0

    return normalized


async def _set_room_scores(bot, room_jid: str, scores: dict):
    store = await get_karma_store(bot)
    data = await store.get_global(KARMA_SCORES_KEY, default={})

    if not isinstance(data, dict):
        data = {}

    data[room_jid] = scores
    await store.set_global(KARMA_SCORES_KEY, data)


def _is_public_muc(msg, is_room: bool) -> bool:
    return is_room and msg.get("type") == "groupchat"


def _get_bot_nick(room_jid: str) -> str | None:
    room = JOINED_ROOMS.get(room_jid, {})
    nick = room.get("nick")
    return str(nick) if nick else None


def _known_room_nicks(room_jid: str) -> list[str]:
    nicks = JOINED_ROOMS.get(room_jid, {}).get("nicks", {})
    result = [str(nick) for nick in nicks.keys() if str(nick).strip()]

    # Make longest-first so "array in the matrix" wins over "array"
    result.sort(key=lambda n: (-len(n), n.lower()))
    return result


def _canonical_nick(room_jid: str, nick: str) -> str:
    """
    Resolve nick to the currently known room nick casing if possible.
    Falls back to the original nick.
    """
    target_lower = nick.strip().lower()

    for known_nick in _known_room_nicks(room_jid):
        if known_nick.lower() == target_lower:
            return known_nick

    return nick.strip()


def _normalize_lookup(scores: dict, target: str):
    """
    Case-insensitive lookup in the score dict.
    Returns (canonical_key, score) or (None, 0)
    """
    target_lower = target.lower()

    for nick, score in scores.items():
        if str(nick).lower() == target_lower:
            return nick, int(score)

    return None, 0


def _format_entry(idx: int, nick: str, score: int) -> str:
    return f"#{idx} {nick} ({score})"


def _format_ranking(entries: list[tuple[str, int]]) -> str:
    if not entries:
        return "none yet"

    parts = []
    for i, (nick, score) in enumerate(entries, 1):
        parts.append(_format_entry(i, nick, score))
    return " · ".join(parts)


def _left_boundary_ok(text: str, start: int) -> bool:
    """
    Ensure the nick starts at a reasonable boundary.
    """
    if start <= 0:
        return True

    prev = text[start - 1]
    return prev.isspace() or prev in "([{'\"“”„‚<>|/,:;*-"


def _match_known_nick_before_operator(text: str, op_start: int, room_jid: str) -> str | None:
    """
    Try to match a known room nick immediately before ++/--.
    Longest nick wins.
    """
    prefix = text[:op_start]

    for known_nick in _known_room_nicks(room_jid):
        if len(prefix) < len(known_nick):
            continue

        candidate = prefix[-len(known_nick):]
        if candidate.lower() != known_nick.lower():
            continue

        start = op_start - len(known_nick)
        if _left_boundary_ok(text, start):
            return known_nick

    return None


def _fallback_nick_before_operator(text: str, op_start: int) -> str | None:
    """
    Conservative fallback parser if the nick is not currently present in
    JOINED_ROOMS.

    Strategy:
    - take only the nearest phrase before ++/--
    - stop at strong separators / sentence boundaries
    - keep support for spaces and apostrophes
    - avoid swallowing whole sentences
    """
    if op_start <= 0:
        return None

    left = text[:op_start].rstrip()
    if not left:
        return None

    # Hard boundaries: only consider the text after the last such separator
    hard_separators = [".", "!", "?", "\n", "\t", "(", ")", "[", "]", "{", "}", "<", ">", "|"]
    cut = -1
    for sep in hard_separators:
        pos = left.rfind(sep)
        if pos > cut:
            cut = pos

    if cut >= 0:
        left = left[cut + 1:].strip()

    # Soft separators: if present, prefer the last chunk after them
    for sep in [",", ";", ":"]:
        pos = left.rfind(sep)
        if pos != -1:
            left = left[pos + 1:].strip()

    candidate = left.strip(TRIM_CHARS).strip()
    if not candidate:
        return None

    # Prevent huge accidental captures
    if len(candidate) > 48:
        return None

    # Require at least one visible non-operator char
    if candidate in {"+", "-", "++", "--"}:
        return None

    return candidate


def _extract_karma_events(body: str, room_jid: str) -> list[tuple[str, int]]:
    """
    Extract karma events from a message body.

    Resolution strategy:
    1. Prefer exact case-insensitive match against currently known room nicks.
    2. Fallback to a heuristic phrase directly before ++ / --.

    Returns:
        list of (nick, delta)
    """
    events = []

    for match in OP_RE.finditer(body):
        op = match.group(1)
        op_start = match.start(1)

        nick = _match_known_nick_before_operator(body, op_start, room_jid)
        if nick is None:
            nick = _fallback_nick_before_operator(body, op_start)

        if not nick:
            continue

        delta = 1 if op == "++" else -1
        events.append((nick, delta))

    return events


@command("karma", role=Role.USER)
async def karma_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Karma control and queries.

    Usage:
        {prefix}karma on
        {prefix}karma off
        {prefix}karma status
        {prefix}karma <nick>
        {prefix}karma top
        {prefix}karma bottom
    """
    handled = await _core.handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_karma_store,
        key=KARMA_ENABLED_KEY,
        label="Karma",
        storage="dict",
        log_prefix="[KARMA]",
    )
    if handled:
        return

    is_muc_pm = _core._is_muc_pm(msg)
    is_public_room = _is_public_muc(msg, is_room)

    if not is_public_room:
        if is_muc_pm:
            bot.reply(
                msg,
                "ℹ️ Use 'karma on/off/status' here. Karma queries work in the public room.",
            )
        return

    room_jid = msg["from"].bare
    if not await _is_enabled_for_room(bot, room_jid):
        return

    if not args:
        bot.reply(
            msg,
            f"Usage: {bot.prefix}karma <on|off|status|top|bottom|nick>",
        )
        return

    sub = " ".join(args).strip()
    scores = await _get_room_scores(bot, room_jid)

    if len(args) == 1 and args[0].lower() == "top":
        entries = sorted(
            scores.items(),
            key=lambda item: (-int(item[1]), item[0].lower())
        )[:10]
        bot.reply(msg, f"🏆 Karma top for this room: {_format_ranking(entries)}")
        return

    if len(args) == 1 and args[0].lower() == "bottom":
        entries = sorted(
            scores.items(),
            key=lambda item: (int(item[1]), item[0].lower())
        )[:10]
        bot.reply(msg, f"💀 Karma bottom for this room: {_format_ranking(entries)}")
        return

    target = _canonical_nick(room_jid, sub)
    canonical, score = _normalize_lookup(scores, target)
    display = canonical or target

    bot.reply(msg, f"📊 Karma for {display}: {score}")


async def on_message(bot, msg):
    try:
        body = msg.get("body", "").strip()
        if not body:
            return

        if msg.get("from") == bot.boundjid:
            return

        if msg.get("type") != "groupchat":
            return

        room_jid = msg["from"].bare
        if room_jid not in JOINED_ROOMS:
            return

        if not await _is_enabled_for_room(bot, room_jid):
            return

        actor_nick = msg.get("mucnick") or msg["from"].resource
        if not actor_nick:
            return

        bot_nick = _get_bot_nick(room_jid)
        events = _extract_karma_events(body, room_jid)

        if not events:
            return

        scores = await _get_room_scores(bot, room_jid)
        changed = False
        seen_targets = set()

        for raw_target, delta in events:
            target_nick = _canonical_nick(room_jid, raw_target)
            target_lower = target_nick.lower()

            # Anti-abuse: same target only once per message
            if target_lower in seen_targets:
                continue
            seen_targets.add(target_lower)

            # Ignore self-karma
            if target_lower == str(actor_nick).lower():
                continue

            # Ignore bot-karma
            if bot_nick and target_lower == bot_nick.lower():
                continue

            current_key, current_score = _normalize_lookup(scores, target_nick)
            key = current_key or target_nick
            scores[key] = int(current_score) + delta
            changed = True

            log.info(
                "[KARMA] room=%s actor=%s target=%s delta=%s total=%s",
                room_jid,
                actor_nick,
                key,
                delta,
                scores[key],
            )

        if changed:
            await _set_room_scores(bot, room_jid, scores)

    except Exception:
        log.exception("[KARMA] Error in on_message")


async def on_load(bot):
    log.info("[KARMA] Plugin loading...")
    bot.bot_plugins.register_event(
        "karma",
        "groupchat_message",
        partial(on_message, bot),
    )
    log.info("[KARMA] Plugin loaded")


async def on_unload(bot):
    log.info("[KARMA] Plugin unloaded")
