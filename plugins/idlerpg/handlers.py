"""IdleRPG message and presence event handlers."""

from __future__ import annotations

from typing import Any

from core_plugins import _core

from .config import COUNT_COMMAND_MESSAGES, MESSAGE_PENALTY, log
from .constants import IDLERPG_ENABLED_KEY, PLUGIN_NAME
from .formatting import _command_prefix, _now
from .leveling import _penalize_player
from .state import _get_data, _room_bucket

_MESSAGE_PENALTY_DEDUPE_TTL = 30
_MESSAGE_PENALTY_SEEN: dict[str, int] = {}

def _message_penalty_dedupe_key(msg) -> str:
    """Return a stable key for one inbound groupchat stanza.

    The plugin registers both ``groupchat_message`` and the generic
    ``message`` event so deployments where only one event fires still apply
    penalties.  When both events fire for the same stanza, this key prevents a
    double penalty.
    """
    try:
        room = str(getattr(msg["from"], "bare", "") or "")
        nick = str(msg.get("mucnick") or getattr(msg["from"], "resource", "") or "")
        stanza_id = str(msg.get("id") or msg.get("stanza_id") or "")
        if stanza_id:
            return f"id:{room}|{nick}|{stanza_id}"
    except Exception:
        return f"obj:{id(msg)}"
    return f"obj:{id(msg)}"

def _message_penalty_seen(msg) -> bool:
    now = _now()
    cutoff = now - _MESSAGE_PENALTY_DEDUPE_TTL
    for key, seen_at in list(_MESSAGE_PENALTY_SEEN.items()):
        if seen_at < cutoff:
            _MESSAGE_PENALTY_SEEN.pop(key, None)
    key = _message_penalty_dedupe_key(msg)
    if key in _MESSAGE_PENALTY_SEEN:
        return True
    _MESSAGE_PENALTY_SEEN[key] = now
    return False

def _safe_message_value(getter) -> Any:
    try:
        return getter()
    except Exception:
        return None

def _message_actor_nick(msg) -> str:
    """Return the MUC nickname for a public room message.

    Different Slixmpp paths expose the nickname in slightly different ways.
    Use all cheap sources before falling back to parsing the full JID string.
    """
    getter = getattr(msg, "get_mucnick", None)
    raw_from = _safe_message_value(lambda: str(msg["from"]))
    candidates: list[Any] = [
        getter() if callable(getter) else None,
        _safe_message_value(lambda: msg.get("mucnick")),
        _safe_message_value(lambda: msg["mucnick"]),
        _safe_message_value(lambda: getattr(msg["from"], "resource", None)),
        str(raw_from).rsplit("/", 1)[1] if raw_from and "/" in str(raw_from) else None,
    ]

    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""

def _remember_player_nick(player: dict[str, Any], msg) -> None:
    nick = _message_actor_nick(msg)
    if nick:
        player["last_nick"] = nick[:128]

def _real_bare_jid(value: Any, room_jid: str) -> str:
    if not value:
        return ""
    try:
        bare = getattr(value, "bare", None)
        candidate = str(bare if bare else value).split("/", 1)[0].strip()
    except Exception:
        return ""
    if not candidate or candidate == room_jid or "@" not in candidate:
        return ""
    return candidate

def _identity_values_match(value: Any, needle: str) -> bool:
    candidate = str(value or "").strip().lower()
    return bool(candidate) and candidate == needle

def _find_player_by_message_identity(
    room: dict[str, Any],
    *,
    sender_jid: str = "",
    actor_nick: str = "",
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    """Find a player from a live room message without trusting stale indexes.

    Some real MUC deployments do not expose the occupant's real JID for every
    message.  Existing players may also have been registered before we stored
    ``last_nick``.  Therefore message penalties must do a direct player scan and
    compare all stable identity fields instead of relying only on ``name_index``.
    """
    jid_needle = str(sender_jid or "").strip().lower()
    nick_needle = str(actor_nick or "").strip().lower()
    if not jid_needle and not nick_needle:
        return None, None

    players = room.get("players", {})
    if not isinstance(players, dict):
        return None, None

    for jid, player in players.items():
        if not isinstance(player, dict):
            continue
        if jid_needle and (
            _identity_values_match(jid, jid_needle)
            or _identity_values_match(player.get("jid"), jid_needle)
        ):
            return str(jid), player

        if nick_needle:
            seen_nicks = [
                player.get("name"),
                player.get("character"),
                player.get("last_nick"),
                player.get("nick"),
                player.get("current_nick"),
            ]
            extra = player.get("nicks")
            if isinstance(extra, (list, tuple, set)):
                seen_nicks.extend(extra)
            if any(_identity_values_match(value, nick_needle) for value in seen_nicks):
                return str(jid), player
    return None, None

async def _message_penalty_target_jid(bot, msg, room_jid: str, actor_nick: str) -> str:
    sender_jid, _, _ = await _core.get_real_jid(bot, msg)
    sender_jid = _real_bare_jid(sender_jid, room_jid)

    if not sender_jid:
        lookup = getattr(bot, "_lookup_muc_occupant_jid", None)
        if callable(lookup):
            try:
                sender_jid = _real_bare_jid(lookup(room_jid, actor_nick), room_jid)
            except Exception:
                sender_jid = ""

    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    jid, player = _find_player_by_message_identity(
        room,
        sender_jid=sender_jid,
        actor_nick=actor_nick,
    )
    if player and jid:
        return str(jid)

    return ""

async def on_message(bot, msg):
    try:
        body = str(msg.get("body", "") or "").strip()
        if not body or msg.get("type") != "groupchat":
            return
        room_jid = str(msg["from"].bare)
        if not await _core._is_enabled_for_room(bot, IDLERPG_ENABLED_KEY, PLUGIN_NAME, room_jid):
            return
        bot_nick = getattr(getattr(bot, "presence", None), "joined_rooms", {}).get(room_jid)
        actor_nick = _message_actor_nick(msg)
        if bot_nick and actor_nick and str(bot_nick).lower() == str(actor_nick).lower():
            return
        if not COUNT_COMMAND_MESSAGES and body.startswith(_command_prefix(bot)):
            return
        target_jid = await _message_penalty_target_jid(bot, msg, room_jid, str(actor_nick or ""))
        if not target_jid:
            log.debug(
                "[IDLERPG] Message penalty skipped: no player for room=%s nick=%s",
                room_jid,
                actor_nick,
            )
            return
        if _message_penalty_seen(msg):
            return
        await _penalize_player(
            bot,
            room_jid,
            target_jid,
            "message",
            max(1, len(body)) * MESSAGE_PENALTY,
            announce=True,
        )
    except Exception:
        log.exception("[IDLERPG] Error in on_message")

async def on_muc_presence(bot, pres):
    from .tasks import _ensure_game_task

    try:
        room_jid = str(pres["from"].bare)
        if not await _core._is_enabled_for_room(bot, IDLERPG_ENABLED_KEY, PLUGIN_NAME, room_jid):
            return
        await _ensure_game_task(bot, room_jid)
    except Exception:
        log.debug("[IDLERPG] Presence handling failed", exc_info=True)
