"""Reply-aware reminder message event handlers."""

from __future__ import annotations

from utils.config import config
from utils import message_cache
from bot.room_state import JOINED_ROOMS
from core_plugins._core import (
    extract_reply_quote,
    get_reply_target,
    get_stanza_id,
    remember_stanza,
)

from .config import REMINDER_REPLY_FALLBACK_NAMESPACE
from .runtime import log
def _body_without_reply_quote(body: str) -> str:
    """Remove a leading XEP-0461 plain-text fallback quote."""
    lines = str(body or "").splitlines()
    index = 0

    while index < len(lines) and lines[index].startswith(">"):
        index += 1

    while index < len(lines) and not lines[index].strip():
        index += 1

    return "\n".join(lines[index:]).strip()
def _is_remind_command_body(body: str) -> bool:
    """Return whether a body contains a reminder command or alias."""
    prefix = str(config.get("prefix", ",") or ",")
    stripped = str(body or "").strip().lower()
    commands = ("remind", "rem", "reminder")
    return any(
        stripped == f"{prefix}{name}"
        or stripped.startswith(f"{prefix}{name} ")
        for name in commands
    )
def _is_own_room_message(bot, msg) -> bool:
    """Return True when a room stanza was sent by the bot itself."""
    try:
        room = str(msg["from"].bare)
        sender_nick = str(msg.get("mucnick") or msg["from"].resource or "")
        joined_rooms = getattr(
            getattr(bot, "presence", None),
            "joined_rooms",
            {},
        )
        bot_nick = str(
            joined_rooms.get(room) or getattr(bot, "nick", "") or ""
        )
        return bool(sender_nick and bot_nick and sender_nick == bot_nick)
    except Exception:
        return False
def _reply_message_text(bot, msg, is_room: bool) -> str | None:
    """Resolve the replied-to message from the shared cache or fallback quote."""
    reply_id = get_reply_target(msg)
    if reply_id:
        conversation = message_cache.conversation_key(
            msg,
            is_room=is_room,
            joined_rooms=JOINED_ROOMS,
        )
        cache = getattr(bot, "message_cache", None)
        get_by_id = getattr(cache, "get_by_id", None)
        if conversation and callable(get_by_id):
            cached = get_by_id(conversation, reply_id)
            if cached:
                text = str(cached.get("body") or "").strip()
                if text:
                    return text

    return extract_reply_quote(str(msg.get("body", "") or ""))
async def _redispatch_reply_fallback(bot, msg, *, is_room: bool) -> None:
    """Redispatch a quoted XEP-0461 reminder command through normal routing."""
    try:
        msg_type = str(msg.get("type") or "")
        if is_room:
            if msg_type != "groupchat" or _is_own_room_message(bot, msg):
                return
        elif msg_type not in {"chat", "normal"}:
            return

        body = str(msg.get("body", "") or "").strip()
        if not body or not extract_reply_quote(body):
            return

        command_body = _body_without_reply_quote(body)
        if not _is_remind_command_body(command_body):
            return

        stanza_id = get_stanza_id(msg)
        if not remember_stanza(REMINDER_REPLY_FALLBACK_NAMESPACE, stanza_id):
            return

        nick = None
        if is_room:
            nick = msg.get("mucnick") or getattr(msg["from"], "resource", None)
        await bot.handle_command(
            command_body,
            msg["from"],
            nick,
            msg,
            is_room,
        )
    except Exception:
        log.exception("[REMINDER] Error handling reply fallback command")
async def _on_groupchat_message(bot, msg) -> None:
    await _redispatch_reply_fallback(bot, msg, is_room=True)
async def _on_private_message(bot, msg) -> None:
    await _redispatch_reply_fallback(bot, msg, is_room=False)
