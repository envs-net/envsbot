"""
Pin messages in a room and list/show/search/delete/mark important stored pins.

Usage
-----
Reply to a room message and send:
    {prefix}pin add

For clients without reply support:
    {prefix}pin add last
    {prefix}pin add last <n>

Manage pins:
    {prefix}pin list [page]
    {prefix}pin search <query> [page]
    {prefix}pin find <query> [page]
    {prefix}pin show <id>
    {prefix}pin edit <id> <text>
    {prefix}pin tags <id> [tag ...]
    {prefix}pin important [list|<id> on|off]
    {prefix}pin delete <id>

Room control (MUC PM):
    {prefix}pin on|off|status
"""

from __future__ import annotations

import html
import logging
import time
from functools import partial
from typing import Any

from core_plugins._core import (
    JOINED_ROOMS,
    _is_enabled_for_room,
    extract_reply_quote,
    get_real_jid,
    get_reply_target,
    handle_room_toggle_command,
    is_room_moderator_or_admin,
    paginate_items,
)
from core_plugins.users import user_has_room_plugin_grant
from utils.audit import audit_event
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.config import config
from utils.formatting import page_size_for, parse_page_args

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "pin",
    "version": "1.3.0",
    "description": "Pin room messages with paging, search, tags, important pins and non-reply fallback.",
    "category": "utility",
    "requires": ["rooms", "_core", "users"],
    "room_state": "custom",
}

PIN_ENABLED_KEY = "PIN"
PIN_DATA_KEY = "PIN_DATA"

PINS_FIELD = "pins"
PAGE_SIZE = int(config.get("pin_page_size", 10) or 10)


async def get_pin_store(bot):
    return bot.db.users.plugin("pin")


def _prefix() -> str:
    return config.get("prefix", ",")


def _trim(text: str | None, limit: int = 700) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _trim_preview(text: str | None, max_lines: int = 1,
                  max_chars: int = 240) -> str:
    if not text:
        return ""

    lines = str(text).strip().splitlines()
    clipped_lines = lines[:max_lines]
    clipped = "\n".join(clipped_lines).strip()

    if len(lines) > max_lines:
        clipped += " …"

    if len(clipped) <= max_chars:
        return clipped

    return clipped[: max_chars - 1].rstrip() + "…"


def _is_pin_generated_text(text: str | None) -> bool:
    if not text:
        return False

    stripped = str(text).strip()

    return (
        stripped.startswith("📌 Pinned message as #")
        or stripped.startswith("📌 Pins for ")
        or stripped.startswith("📌 Pin #")
        or stripped.startswith("📌 Pin search for ")
    )


def _room_key_from_msg(msg, is_room: bool) -> str | None:
    if is_room:
        try:
            return str(msg["from"].bare)
        except Exception:
            return None

    try:
        room = str(msg["from"].bare)
        if room in JOINED_ROOMS:
            return room
    except Exception as exc:
        log.debug("[PIN] Could not resolve room from message: %s", exc)

    return None


def _body_without_quote(body: str) -> str:
    if not body:
        return ""

    lines = body.splitlines()
    idx = 0

    while idx < len(lines) and lines[idx].startswith(">"):
        idx += 1

    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    return "\n".join(lines[idx:]).strip()


def _safe_get_sender_nick(msg) -> str | None:
    try:
        return str(msg.get("mucnick") or msg["from"].resource or "")
    except Exception:
        return None


def _safe_get_sender_jid(msg, fallback=None) -> str | None:
    try:
        value = getattr(msg["from"], "bare", None)
        if value:
            return str(value)
    except Exception as exc:
        log.debug("[PIN] Could not read sender bare JID: %s", exc)

    if fallback is not None:
        try:
            return str(fallback)
        except Exception:
            return None

    return None


def _normalize_pin_data(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}

    normalized = {}

    for room, room_data in state.items():
        if not isinstance(room_data, dict):
            room_data = {}

        pins = room_data.get(PINS_FIELD, [])
        if not isinstance(pins, list):
            pins = []

        normalized[str(room)] = {
            PINS_FIELD: pins,
        }

    return normalized


async def _load_pin_data(bot) -> dict[str, Any]:
    store = await get_pin_store(bot)
    state = await store.get_global(PIN_DATA_KEY, default={})
    return _normalize_pin_data(state)


async def _save_pin_data(bot, state: dict[str, Any]) -> None:
    store = await get_pin_store(bot)
    await store.set_global(PIN_DATA_KEY, state)


def _room_bucket(state: dict[str, Any], room: str) -> dict[str, Any]:
    if room not in state:
        state[room] = {
            PINS_FIELD: [],
        }
    return state[room]


async def _sender_can_manage_pins_in_room(bot, msg, room_jid: str) -> bool:
    """True if sender can manage pins in this room.

    Existing room moderators/admins/owners keep their permissions. Users with
    a ``pin`` plugin grant may also manage pins, but only when a live MUC
    affiliation query or cache confirms they are owner/admin in the room.
    """
    nick = msg.get("mucnick") or msg["from"].resource or ""
    if await is_room_moderator_or_admin(bot, room_jid, str(nick)):
        return True

    sender_jid, _, _ = await get_real_jid(bot, msg)
    if not sender_jid:
        return False

    return await user_has_room_plugin_grant(
        bot,
        sender_jid,
        "pin",
        room_jid,
    )


def _format_timestamp(ts: int | float | None) -> str:
    if not ts:
        return "unknown"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(ts)))
    except Exception:
        return "unknown"


def _format_pin_line(entry: dict[str, Any]) -> str:
    pin_id = entry.get("id", "?")
    actor_nick = entry.get("actor_nick") or "unknown"
    created_at = _format_timestamp(entry.get("created_at"))
    target_nick = entry.get("target_nick") or "unknown"
    preview = _trim_preview(entry.get("preview") or entry.get("target_text")
                            or "—", max_lines=1, max_chars=240)
    tags = _format_pin_tags(entry.get("tags"))
    tag_suffix = f" | tags: {tags}" if tags else ""
    marker = "⭐ " if entry.get("important") else "• "
    return (f"{marker}#{pin_id} by {actor_nick} at {created_at} "
            f"| target: {target_nick} | {preview}{tag_suffix}")


def _normalize_pin_tags(raw: Any) -> list[str]:
    """Return normalized unique pin tags without leading ``#``."""
    if raw is None:
        return []
    if isinstance(raw, str):
        pieces = raw.replace(",", " ").split()
    else:
        try:
            pieces = []
            for item in raw:
                pieces.extend(str(item).replace(",", " ").split())
        except TypeError:
            pieces = str(raw).replace(",", " ").split()

    tags: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        tag = piece.strip().strip("#").casefold()
        tag = "".join(ch for ch in tag if ch.isalnum() or ch in {"-", "_"})
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _format_pin_tags(raw: Any) -> str:
    """Return display text for normalized pin tags."""
    tags = _normalize_pin_tags(raw)
    return " ".join(f"#{tag}" for tag in tags)

def _parse_pin_search_args(args: list[Any]):
    """Return ``(query, page_request)`` for ``pin search/find`` arguments.

    A trailing ``all``, ``last`` or positive integer is treated as paging only
    when there is at least one query token before it, so ``pin search 123``
    still searches for ``123``.
    """
    if len(args) < 2:
        return None

    query_parts = [str(part).strip() for part in args[1:] if str(part).strip()]
    if not query_parts:
        return None

    page_args: list[str] = []
    if len(query_parts) > 1:
        last = query_parts[-1].lower()
        if last in {"all", "last"} or last.isdigit():
            page_args = [query_parts.pop()]

    query = " ".join(query_parts).strip()
    if not query:
        return None

    return query, parse_page_args(page_args)


def _format_pin_page(title: str, pins: list[dict[str, Any]], page_request, next_hint: str) -> list[str]:
    """Return formatted pin list output honoring global default pagination."""
    if page_request.all:
        lines = [f"{title} - all", ""]
        lines.extend(_format_pin_line(entry) for entry in pins)
        return lines

    page_size = page_size_for(PAGE_SIZE, page_request)
    page_items, page, total_pages, _total = paginate_items(
        pins,
        page_request.page,
        page_size,
    )
    lines = [f"{title} - Page {page}/{total_pages}", ""]
    lines.extend(_format_pin_line(entry) for entry in page_items)
    if page < total_pages:
        lines.append("")
        lines.append(f"Use {next_hint} {page + 1} for the next page.")
    return lines


def _pin_search_haystack(entry: dict[str, Any]) -> str:
    pin_id = entry.get("id", "")
    values = [
        str(pin_id),
        f"#{pin_id}" if pin_id != "" else "",
        entry.get("actor_nick"),
        entry.get("target_nick"),
        entry.get("preview"),
        entry.get("target_text"),
        entry.get("source"),
        _format_pin_tags(entry.get("tags")),
        _format_timestamp(entry.get("created_at")),
    ]
    return "\n".join(str(value) for value in values if value).casefold()


def _pin_matches_query(entry: dict[str, Any], query: str) -> bool:
    terms = [term.casefold() for term in str(query).split() if term.strip()]
    if not terms:
        return False

    haystack = _pin_search_haystack(entry)
    return all(term in haystack for term in terms)


def _find_pin(bucket: dict[str, Any], pin_id: int) -> dict[str, Any] | None:
    for entry in bucket.get(PINS_FIELD, []):
        try:
            if int(entry.get("id")) == pin_id:
                return entry
        except Exception:
            continue
    return None


def _delete_pin(bucket: dict[str, Any], pin_id: int) -> bool:
    pins = bucket.get(PINS_FIELD, [])
    for idx, entry in enumerate(pins):
        try:
            if int(entry.get("id")) == pin_id:
                pins.pop(idx)
                return True
        except Exception:
            continue
    return False


def _next_free_pin_id(bucket: dict[str, Any]) -> int:
    used_ids = set()

    for entry in bucket.get(PINS_FIELD, []):
        try:
            used_ids.add(int(entry.get("id")))
        except Exception:
            continue

    pin_id = 1
    while pin_id in used_ids:
        pin_id += 1

    return pin_id


def _is_pin_command_message(body: str) -> bool:
    prefix = _prefix()
    stripped = body.strip().lower()
    return stripped == f"{prefix}pin" or stripped.startswith(f"{prefix}pin ")


def _is_pin_add_command_body(body: str) -> bool:
    prefix = _prefix()
    stripped = body.strip().lower()
    return stripped == f"{prefix}pin add"


def _recent_cache_entries(bot, room: str) -> list[dict[str, Any]]:
    return bot.message_cache.get_messages(room)


def _get_recent_target(bot, room: str, offset: int = 1) -> dict[str, Any] | None:
    if offset < 1:
        return None

    entries = _recent_cache_entries(bot, room)
    if not entries:
        return None

    filtered: list[dict[str, Any]] = []
    for entry in entries:
        body = entry.get("body") or ""
        if not body.strip():
            continue
        if _is_pin_command_message(_body_without_quote(body)):
            continue
        if _is_pin_generated_text(body):
            continue
        filtered.append(entry)

    if not filtered:
        return None

    if offset > len(filtered):
        return None

    return filtered[-offset]


async def _create_pin_entry(
    bot,
    msg,
    room: str,
    sender_jid,
    nick,
    target_text: str,
    target_nick: str,
    target_stanza_id: str | None,
    reply_id: str | None,
    quote_text: str | None,
    cmd_body: str,
    source: str,
):
    if not target_text:
        bot.reply(msg, "❌ Could not resolve the target message.")
        return True

    if _is_pin_generated_text(target_text):
        bot.reply(msg, "❌ Pin-generated bot messages cannot be pinned.")
        return True

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)

    pin_id = _next_free_pin_id(bucket)
    sender_nick = _safe_get_sender_nick(msg) or nick or "unknown"
    sender_real_jid = _safe_get_sender_jid(msg, fallback=sender_jid)

    preview_source = target_text or quote_text or "target message"
    preview = _trim_preview(
        html.unescape(str(preview_source).replace("\xa0", " ")),
        max_lines=2,
        max_chars=240,
    )

    entry = {
        "id": pin_id,
        "room": room,
        "target_room": room,
        "created_at": int(time.time()),
        "actor_nick": str(sender_nick),
        "actor_jid": sender_real_jid,
        "reply_id": str(reply_id) if reply_id else None,
        "target_reply_to": str(reply_id) if reply_id else None,
        "target_stanza_id": target_stanza_id,
        "target_nick": target_nick,
        "target_text": _trim(target_text, 4000) if target_text else None,
        "preview": preview,
        "pin_command_body": _trim(cmd_body, 500),
        "source": source,
        "client_quote_available": bool(quote_text),
        "raw_body_excerpt": _trim(msg.get("body", "") or "", 1000),
        "pinned_via": "pin_command",
    }

    bucket[PINS_FIELD].append(entry)
    await _save_pin_data(bot, state)
    await audit_event(
        bot,
        "pin_added",
        actor=sender_real_jid,
        target=room,
        details={"pin_id": pin_id, "source": source},
    )

    bot.reply(
        msg,
        [
            f"📌 Pinned message as #{entry['id']}.",
            f"Source: {entry['source']}",
            f"Reply target id: {reply_id or 'none'}",
            f"Target nick: {target_nick}",
            f"Preview: {preview}",
        ],
        mention=False,
    )
    return True


async def _handle_reply_pin_add(bot, msg):
    try:
        body = msg.get("body", "") or ""
        if not body.strip():
            return False

        if msg.get("type") != "groupchat":
            return False

        room = str(msg["from"].bare)
        if room not in JOINED_ROOMS:
            return False

        if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
            return False

        # permission guard for reply-based pin add
        if not await _sender_can_manage_pins_in_room(bot, msg, room):
            return False

        quote_text = extract_reply_quote(body)
        if not quote_text:
            return False

        cmd_body = _body_without_quote(body)
        if not _is_pin_add_command_body(cmd_body):
            return False

        reply_id = get_reply_target(msg)
        cached_entry = None
        target_text = None
        target_nick = "unknown"
        target_stanza_id = None
        source = "quote"

        if reply_id:
            cached_entry = bot.message_cache.get_by_id(room, reply_id)
            if cached_entry:
                target_text = cached_entry.get("body")
                target_nick = cached_entry.get("nick") or "unknown"
                target_stanza_id = (cached_entry.get("stanza_id")
                                    or str(reply_id))
                source = "reply-cache"

        if not target_text and quote_text:
            target_text = quote_text
            target_stanza_id = str(reply_id) if reply_id else None
            source = "quote"

        return await _create_pin_entry(
            bot=bot,
            msg=msg,
            room=room,
            sender_jid=msg["from"],
            nick=_safe_get_sender_nick(msg),
            target_text=str(target_text),
            target_nick=target_nick,
            target_stanza_id=target_stanza_id,
            reply_id=reply_id,
            quote_text=quote_text,
            cmd_body=cmd_body,
            source=source,
        )
    except Exception:
        log.exception("[PIN] Error handling reply-based pin add")
        return False


async def _on_groupchat_message(bot, msg):
    """Handle clients that place a plain-text reply quote before `,pin add`."""
    try:
        await _handle_reply_pin_add(bot, msg)
    except Exception:
        log.exception("[PIN] Error in reply fallback handler")


@command(
    "pin",
    role=Role.USER,
    short="Pin, list, search, mark important, edit, tag or delete room pins.",
    usage=(
        "{prefix}pin <add|list|important|search|find|show|edit|tags|"
        "delete|del|remove|rm|on|off|status> ..."
    ),
    subcommands=[
        help_subcommand(
            "add",
            "{prefix}pin add [last [n]]",
            "Pin the replied-to message or a recent room message.",
            examples=[
                help_example(
                    "{prefix}pin add",
                    "Pin the message you replied to.",
                ),
                help_example(
                    "{prefix}pin add last 2",
                    "Pin the second most recent eligible room message.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "list",
            "{prefix}pin list [page|last|all]",
            "List stored pins for the current room.",
            examples=[
                help_example(
                    "{prefix}pin list",
                    "Show the first page of pins for the room.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "search",
            "{prefix}pin search <query> [page|last|all]",
            "Search pin text, tags, authors and metadata.",
            aliases=("find",),
            examples=[
                help_example(
                    "{prefix}pin search ssh key",
                    "Find room pins containing the words 'ssh key'.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "show",
            "{prefix}pin show <id>",
            "Show one pin with its complete metadata.",
            examples=[
                help_example(
                    "{prefix}pin show 3",
                    "Display pin number 3.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "edit",
            "{prefix}pin edit <id> <text>",
            "Replace the stored text of a pin.",
            examples=[
                help_example(
                    "{prefix}pin edit 3 Updated room info",
                    "Replace pin 3 with updated text.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "tags",
            "{prefix}pin tags <id> [tag ...]",
            "Set or clear searchable tags on a pin.",
            aliases=("tag",),
            examples=[
                help_example(
                    "{prefix}pin tags 3 mail support",
                    "Set the tags 'mail' and 'support' on pin 3.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "important",
            "{prefix}pin important [list|<id> on|off]",
            "List important pins or change a pin's important flag.",
            aliases=("star", "unstar"),
            examples=[
                help_example(
                    "{prefix}pin important 3 on",
                    "Mark pin 3 as important.",
                ),
                help_example(
                    "{prefix}pin important list",
                    "List only important room pins.",
                ),
            ],
            context="room or MUC PM",
        ),
        help_subcommand(
            "delete",
            "{prefix}pin delete <id>",
            "Delete one stored room pin.",
            aliases=("del", "remove", "rm"),
            examples=[
                help_example(
                    "{prefix}pin delete 3",
                    "Delete pin number 3.",
                ),
            ],
            context="room or MUC PM",
        ),
        *room_toggle_subcommands("pin", "the pin plugin"),
    ],
    examples=[
        "{prefix}pin status",
        "{prefix}pin list",
        "{prefix}pin search mail",
        "{prefix}pin search ssh key",
        "{prefix}pin edit 3 Updated room info",
        "{prefix}pin tags 3 mail support",
        "{prefix}pin important 3 on",
        "{prefix}pin important list",
        "{prefix}rooms enable pin",
    ],
    category="rooms",
    context="any",
)
async def pin_command(bot, sender_jid, nick, args, msg, is_room):
    if not args:
        bot.reply(
            msg,
            (
                f"Usage: {_prefix()}pin add [last [n]] | {_prefix()}pin "
                "list [page] | "
                f"{_prefix()}pin search <query> [page] | "
                f"{_prefix()}pin show <id> | "
                f"{_prefix()}pin edit <id> <text> | "
                f"{_prefix()}pin tags <id> [tag ...] | "
                f"{_prefix()}pin important [list|<id> on|off] | "
                f"{_prefix()}pin delete|del|remove|rm <id> | "
                f"{_prefix()}pin on|off|status"
            ),
            mention=False,
        )
        return

    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_pin_store,
        key=PIN_ENABLED_KEY,
        label="Pin plugin",
        plugin="pin",
        storage="dict",
        log_prefix="[PIN]",
    )
    if handled:
        return

    room = _room_key_from_msg(msg, is_room)
    if not room:
        bot.reply(
            msg,
            "ℹ️ This command only works in rooms or MUC private messages.",
        )
        return

    subcmd = str(args[0]).lower()

    if subcmd == "list":
        await _pin_command_list(bot, msg, room, args)
        return

    if subcmd in {"search", "find"}:
        await _pin_command_search(bot, msg, room, args)
        return

    if subcmd == "show":
        await _pin_command_show(bot, msg, room, args)
        return

    if subcmd == "edit":
        await _pin_command_edit(bot, msg, room, args)
        return

    if subcmd in {"tag", "tags"}:
        await _pin_command_tags(bot, msg, room, args)
        return

    if subcmd in {"important", "star", "unstar"}:
        await _pin_command_important(bot, msg, room, args)
        return

    if subcmd in {"delete", "del", "remove", "rm"}:
        await _pin_command_delete(bot, msg, room, args)
        return

    if subcmd != "add":
        bot.reply(
            msg,
            (
                f"Unknown subcommand '{subcmd}'. "
                f"Use {_prefix()}pin add|list|important|search|show|edit|tags|"
                "delete|del|remove|rm|on|off|status"
            ),
            mention=False,
        )
        return

    await _pin_command_add(bot, sender_jid, nick, msg, room, is_room, args)


async def _pin_command_list(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if len(args) >= 2 and str(args[1]).lower() not in {"all", "last"} and not str(args[1]).isdigit():
        bot.reply(msg, f"❌ Usage: {_prefix()}pin list [page|last|all]")
        return
    page_request = parse_page_args(args[1:2])

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    pins = list(bucket.get(PINS_FIELD, []))
    pins.sort(key=lambda x: (bool(x.get("important")), int(x.get("id", 0))), reverse=True)

    if not pins:
        bot.reply(msg, "📌 No pinned messages stored for this room.",
                  mention=False)
        return

    lines = _format_pin_page(
        f"📌 Pins for {room} ({len(pins)})",
        pins,
        page_request,
        f"{_prefix()}pin list",
    )

    bot.reply(msg, lines, mention=False)


async def _pin_command_search(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    parsed = _parse_pin_search_args(args)
    if parsed is None:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin search <query> [page]")
        return

    query, page_request = parsed
    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    pins = list(bucket.get(PINS_FIELD, []))
    matches = [entry for entry in pins if _pin_matches_query(entry, query)]
    matches.sort(key=lambda x: (bool(x.get("important")), int(x.get("id", 0))), reverse=True)

    if not matches:
        bot.reply(
            msg,
            f'📌 No pins matching "{query}" found for this room.',
            mention=False,
        )
        return

    lines = _format_pin_page(
        f'📌 Pin search for {room}: "{query}" ({len(matches)} matches)',
        matches,
        page_request,
        f"{_prefix()}pin search {query}",
    )

    bot.reply(msg, lines, mention=False)


async def _pin_command_show(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if len(args) < 2:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin show <id>")
        return

    try:
        pin_id = int(args[1])
    except ValueError:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin show <id>")
        return

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    entry = _find_pin(bucket, pin_id)

    if not entry:
        bot.reply(msg, f"❌ Pin #{pin_id} not found in this room.")
        return

    lines = [
        f"📌 Pin #{entry.get('id')}",
        f"Room: {entry.get('room') or room}",
        f"Created: {_format_timestamp(entry.get('created_at'))}",
        f"Important: {'yes' if entry.get('important') else 'no'}",
        f"Pinned by: {entry.get('actor_nick') or 'unknown'}"
        f" ({entry.get('actor_jid') or 'unknown'})",
        f"Target nick: {entry.get('target_nick') or 'unknown'}",
        f"Reply target id: {entry.get('reply_id') or 'unknown'}",
        f"Target stanza id: {entry.get('target_stanza_id') or 'unknown'}",
        f"Source: {entry.get('source') or 'unknown'}",
    ]

    tags = _format_pin_tags(entry.get("tags"))
    if tags:
        lines.append(f"Tags: {tags}")

    preview = entry.get("preview")
    if preview:
        lines.extend(["", "Preview:", preview])

    full_text = entry.get("target_text")
    if full_text:
        lines.extend(["", "Pinned text:", full_text])

    bot.reply(msg, lines, mention=False)


async def _pin_command_edit(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if not await _sender_can_manage_pins_in_room(bot, msg, room):
        bot.reply(
            msg,
            "⛔ Only room moderators/admins/owners can edit pins.",
            mention=False,
        )
        return

    if len(args) < 3:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin edit <id> <text>")
        return

    try:
        pin_id = int(args[1])
    except ValueError:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin edit <id> <text>")
        return

    text = " ".join(str(part) for part in args[2:]).strip()
    if not text:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin edit <id> <text>")
        return

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    entry = _find_pin(bucket, pin_id)
    if not entry:
        bot.reply(msg, f"❌ Pin #{pin_id} not found in this room.")
        return

    entry["target_text"] = text
    entry["preview"] = _trim_preview(text)
    entry["updated_at"] = int(time.time())
    entry["source"] = entry.get("source") or "manual-edit"
    await _save_pin_data(bot, state)
    await audit_event(
        bot,
        "pin_edited",
        actor=getattr(msg.get("from"), "bare", None),
        target=room,
        details={"pin_id": pin_id},
    )
    bot.reply(msg, f"✅ Updated pin #{pin_id}.", mention=False)


async def _pin_command_tags(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if len(args) < 2:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin tags <id> [tag ...]")
        return

    try:
        pin_id = int(args[1])
    except ValueError:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin tags <id> [tag ...]")
        return

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    entry = _find_pin(bucket, pin_id)
    if not entry:
        bot.reply(msg, f"❌ Pin #{pin_id} not found in this room.")
        return

    if len(args) == 2:
        tags = _format_pin_tags(entry.get("tags"))
        bot.reply(msg, f"📌 Pin #{pin_id} tags: {tags or 'none'}", mention=False)
        return

    if not await _sender_can_manage_pins_in_room(bot, msg, room):
        bot.reply(
            msg,
            "⛔ Only room moderators/admins/owners can change pin tags.",
            mention=False,
        )
        return

    normalized_tags = _normalize_pin_tags(args[2:])
    entry["tags"] = normalized_tags
    entry["updated_at"] = int(time.time())
    await _save_pin_data(bot, state)
    await audit_event(
        bot,
        "pin_tags_changed",
        actor=getattr(msg.get("from"), "bare", None),
        target=room,
        details={"pin_id": pin_id, "tags": normalized_tags},
    )
    bot.reply(
        msg,
        f"✅ Updated tags for pin #{pin_id}: {_format_pin_tags(normalized_tags) or 'none'}.",
        mention=False,
    )


async def _pin_command_important(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    action = str(args[0]).lower() if args else "important"
    if action == "unstar":
        args = ["important", *(args[1:]), "off"]
    elif action == "star":
        args = ["important", *(args[1:]), "on"]

    if len(args) == 1 or str(args[1]).lower() in {"list", "ls"}:
        if len(args) >= 3 and str(args[2]).lower() not in {"all", "last"} and not str(args[2]).isdigit():
            bot.reply(msg, f"❌ Usage: {_prefix()}pin important [list [page|last|all]|<id> on|off]")
            return
        page_request = parse_page_args(args[2:3])

        state = await _load_pin_data(bot)
        bucket = _room_bucket(state, room)
        pins = [
            entry for entry in bucket.get(PINS_FIELD, [])
            if isinstance(entry, dict) and entry.get("important")
        ]
        pins.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
        if not pins:
            bot.reply(msg, "⭐ No important pins stored for this room.", mention=False)
            return
        lines = _format_pin_page(
            f"⭐ Important pins for {room} ({len(pins)})",
            pins,
            page_request,
            f"{_prefix()}pin important list",
        )
        bot.reply(msg, lines, mention=False)
        return

    if len(args) not in (2, 3):
        bot.reply(msg, f"❌ Usage: {_prefix()}pin important [list [page|last|all]|<id> on|off]")
        return

    if not await _sender_can_manage_pins_in_room(bot, msg, room):
        bot.reply(
            msg,
            "⛔ Only room moderators/admins/owners can mark important pins.",
            mention=False,
        )
        return

    try:
        pin_id = int(args[1])
    except ValueError:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin important [list [page|last|all]|<id> on|off]")
        return

    value = str(args[2]).lower() if len(args) == 3 else "on"
    if value not in {"on", "off", "yes", "no", "true", "false", "1", "0"}:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin important [list [page|last|all]|<id> on|off]")
        return
    important = value in {"on", "yes", "true", "1"}

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)
    entry = _find_pin(bucket, pin_id)
    if not entry:
        bot.reply(msg, f"❌ Pin #{pin_id} not found in this room.")
        return

    if bool(entry.get("important")) == important:
        state_text = "important" if important else "normal"
        bot.reply(msg, f"ℹ️ Pin #{pin_id} is already marked as {state_text}.", mention=False)
        return

    entry["important"] = important
    entry["updated_at"] = int(time.time())
    await _save_pin_data(bot, state)
    await audit_event(
        bot,
        "pin_importance_changed",
        actor=getattr(msg.get("from"), "bare", None),
        target=room,
        details={"pin_id": pin_id, "important": important},
    )
    bot.reply(
        msg,
        f"✅ Pin #{pin_id} marked as {'important' if important else 'normal'}.",
        mention=False,
    )


async def _pin_command_delete(bot, msg, room, args):
    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if not await _sender_can_manage_pins_in_room(bot, msg, room):
        bot.reply(
            msg,
            "⛔ Only room moderators/admins/owners can delete pins.",
            mention=False,
        )
        return

    if len(args) < 2:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin delete <id>")
        return

    try:
        pin_id = int(args[1])
    except ValueError:
        bot.reply(msg, f"❌ Usage: {_prefix()}pin delete <id>")
        return

    state = await _load_pin_data(bot)
    bucket = _room_bucket(state, room)

    if not _delete_pin(bucket, pin_id):
        bot.reply(msg, f"❌ Pin #{pin_id} not found in this room.")
        return

    await _save_pin_data(bot, state)
    await audit_event(
        bot,
        "pin_deleted",
        actor=getattr(msg.get("from"), "bare", None),
        target=room,
        details={"pin_id": pin_id},
    )
    bot.reply(msg, f"✅ Deleted pin #{pin_id}.", mention=False)


async def _pin_command_add(bot, sender_jid, nick, msg, room, is_room, args):
    if not is_room:
        bot.reply(
            msg,
            f"ℹ️ To create a pin, use {_prefix()}pin add as a reply"
            f" or {_prefix()}pin add last",
        )
        return

    if not await _is_enabled_for_room(bot, PIN_ENABLED_KEY, "pin", room):
        bot.reply(msg, "ℹ️ Pin plugin is disabled in this room.")
        return

    if not await _sender_can_manage_pins_in_room(bot, msg, room):
        bot.reply(
            msg,
            "⛔ Only room moderators/admins/owners can add pins.",
            mention=False,
        )
        return

    if len(args) >= 2 and str(args[1]).lower() == "last":
        await _pin_command_add_last(bot, sender_jid, nick, msg, room, args)
        return

    bot.reply(
        msg,
        f"❌ Reply to a room message and then send {_prefix()}pin add, or"
        f" use {_prefix()}pin add last",
        mention=False,
    )


async def _pin_command_add_last(bot, sender_jid, nick, msg, room, args):
    offset = 1
    if len(args) >= 3:
        try:
            offset = int(args[2])
            if offset < 1:
                raise ValueError
        except ValueError:
            bot.reply(msg, f"❌ Usage: {_prefix()}pin add last [n]")
            return

    recent_entry = _get_recent_target(bot, room, offset=offset)
    if not recent_entry:
        if offset == 1:
            bot.reply(msg, f"❌ No suitable cached message found for"
                           f" {_prefix()}pin add last")
        else:
            bot.reply(msg, f"❌ No suitable cached message found for"
                           f" {_prefix()}pin add last {offset}")
        return

    await _create_pin_entry(
        bot=bot,
        msg=msg,
        room=room,
        sender_jid=sender_jid,
        nick=nick,
        target_text=str(recent_entry.get("body") or ""),
        target_nick=recent_entry.get("nick") or "unknown",
        target_stanza_id=recent_entry.get("stanza_id"),
        reply_id=None,
        quote_text=None,
        cmd_body=msg.get("body", "") or "",
        source=f"last-{offset}",
    )


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return pin health diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    pins = int(state.get("pins", 0) or 0)
    rooms = int(state.get("rooms", 0) or 0)
    if room_jid and rooms == 0:
        return [f"ℹ️ Pin{scope}: no stored pins"]
    return [f"✅ Pin{scope}: rooms={rooms}, pins={pins}"]

async def on_load(bot):
    bot.bot_plugins.register_event(
        "pin",
        "groupchat_message",
        partial(_on_groupchat_message, bot),
    )


async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]:
    """Remove all pin data for a deleted room."""
    target = str(room_jid or "").split("/", 1)[0].strip().lower()
    state = await _load_pin_data(bot)
    matching = next(
        (room for room in state if str(room).split("/", 1)[0].strip().lower() == target),
        None,
    )
    if matching is None:
        return {"rooms": 0}
    state.pop(matching, None)
    await _save_pin_data(bot, state)
    return {"rooms": 1}


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return small pin counters for diagnostics."""
    state = await _load_pin_data(bot)
    if room_jid:
        target = str(room_jid or "").split("/", 1)[0].strip().lower()
        matching = next(
            (
                room for room in state
                if str(room).split("/", 1)[0].strip().lower() == target
            ),
            None,
        )
        bucket = state.get(matching, {}) if matching else {}
        return {"rooms": 1 if matching else 0, "pins": len(bucket.get(PINS_FIELD, []))}
    return {
        "rooms": len(state),
        "pins": sum(len(bucket.get(PINS_FIELD, [])) for bucket in state.values()),
    }
