"""Split module for plugins/idlerpg.py: formatting."""

from __future__ import annotations
import re
import time
from typing import Any
from utils.config import config
from utils.task_supervisor import create_plugin_task


def _command_prefix(bot=None) -> str:
    return str(getattr(bot, "prefix", None) or config.get("prefix", ",") or ",")


async def get_idlerpg_store(bot):
    return bot.db.users.plugin(_dep_constants.PLUGIN_NAME)


def _reply(bot, msg, text: str):
    bot.reply(msg, text, mention=False, thread=True)


def _system_room_message(room_jid: str) -> dict[str, Any]:
    return {
        "from": type("From", (), {"bare": room_jid, "resource": None})(),
        "type": "groupchat",
    }


def _system_reply(bot, room_jid: str, text: str):
    bot.reply(
        _system_room_message(room_jid),
        text,
        mention=False,
        thread=True,
        rate_limit=False,
        ephemeral=False,
    )


def _now() -> int:
    return int(time.time())


def _duration(seconds: int | float | None) -> str:
    seconds = max(0, int(seconds or 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _duration_clock(seconds: int | float | None) -> str:
    seconds = max(0, int(seconds or 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    day_word = "day" if days == 1 else "days"
    return f"{days} {day_word}, {hours:02d}:{minutes:02d}:{secs:02d}"


def _possessive(name: str) -> str:
    return f"{name}'" if str(name).endswith("s") else f"{name}'s"


def _next_level_line(player: dict[str, Any]) -> str:
    return f"{_display_player(player)} reaches next level in {_duration_clock(player.get('next', 0))}."


def _created_at(player: dict[str, Any]) -> int:
    value = player.get("created_at")
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _played_for(player: dict[str, Any]) -> str:
    created_at = _created_at(player)
    if created_at <= 0:
        return "unknown"
    return _duration_clock(max(0, _now() - created_at))


def _playing_since(player: dict[str, Any]) -> str:
    created_at = _created_at(player)
    if created_at <= 0:
        return "unknown"
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(created_at))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(value or "").strip())[:30]


def _safe_class(value: str) -> str:
    clean = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "").strip())
    clean = re.sub(r"\s+", " ", clean)
    return clean[:40]


def _display_player(player: dict[str, Any]) -> str:
    return str(player.get("name") or "unknown")


def _alignment_name(value: str | None) -> str:
    return _dep_constants._ALIGNMENT_NAMES.get(str(value or "n")[:1].lower(), "neutral")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return slug[:80] or "idlerpg"


def _room_slug(room_jid: str) -> str:
    return _slug(room_jid.replace("@", "_at_"))


def _display_title(player: dict[str, Any]) -> str:
    title = str(player.get("title") or "").strip()
    achievements = player.get("achievements")
    if title and isinstance(achievements, list) and title in achievements:
        return _dep_leveling._achievement_title(title)
    return ""


def _display_character(player: dict[str, Any]) -> str:
    title = _display_title(player)
    name = _display_player(player)
    return f"{name}, {title}" if title else name


def _player_presence_label(room_jid: str | None, jid: str, player: dict[str, Any]) -> str:
    """Return a compact online/offline marker for top lists."""
    if room_jid and _dep_state._is_player_online(room_jid, jid, player):
        return "🟢 online"
    return "⚫ offline"


def _format_top_lines(room: dict[str, Any], *, limit: int | None = None, room_jid: str | None = None) -> list[str]:
    limit = max(1, int(limit or _dep_config.ANNOUNCE_TOP_LIMIT or 5))
    ranked = _dep_state._ranked_players(room)[:limit]
    if not ranked:
        return ["No IdleRPG players yet."]
    lines = [f"IdleRPG Top {limit} Players:"]
    for rank, (jid, player) in enumerate(ranked, start=1):
        presence = _player_presence_label(room_jid, jid, player)
        lines.append(
            f"{presence} · {_display_character(player)}, the level {player.get('level', 0)} "
            f"{player.get('class', 'idler')}, is #{rank}! Next level in {_duration_clock(player.get('next', 0))}."
        )
    return lines


def _topic_text(room: dict[str, Any], custom_text: str | None = None) -> str:
    ranked = _dep_state._ranked_players(room)[:3]
    top = "; ".join(
        f"#{rank}: {_display_character(player)}, lv. {player.get('level', 0)} {player.get('class', 'idler')}"
        for rank, (_jid, player) in enumerate(ranked, start=1)
    )
    prefix = (custom_text if custom_text is not None else _dep_config.TOPIC_CUSTOM_TEXT).strip()
    if not prefix:
        prefix = "IdleRPG"
    return f"{prefix} {top}" if top else str(prefix)


def _maybe_set_room_topic(
    bot,
    room_jid: str,
    room: dict[str, Any],
    *,
    custom_text: str | None = None,
    force: bool = False,
) -> None:
    if not _dep_config.UPDATE_ROOM_TOPIC and not force:
        return
    topic = _topic_text(room, custom_text=custom_text)[:250]
    xep_muc = getattr(bot, "plugin", {}).get("xep_0045") if isinstance(getattr(bot, "plugin", {}), dict) else None
    setter = getattr(xep_muc, "set_subject", None)
    try:
        if callable(setter):
            result = setter(room_jid, topic)
            if hasattr(result, "__await__"):
                # Fire-and-forget is intentional here: topic updates are best-effort only.
                create_plugin_task(bot, _dep_constants.PLUGIN_NAME, result, name=f"idlerpg-topic-{room_jid}")
            return
        sender = getattr(bot, "send_message", None)
        if callable(sender):
            sender(mto=room_jid, msubject=topic, mtype="groupchat")
    except Exception:
        _dep_config.log.debug("[IDLERPG] Failed to update room topic for %s", room_jid, exc_info=True)


def _maybe_periodic_announcements(bot, room_jid: str, room: dict[str, Any], messages: list[str]) -> None:
    now = _now()
    if _dep_config.ANNOUNCE_TOP_INTERVAL > 0:
        next_at = int(room.get("next_top_announce_at", 0) or 0)
        if now >= next_at:
            messages.append("\n".join(_format_top_lines(room, limit=_dep_config.ANNOUNCE_TOP_LIMIT, room_jid=room_jid)))
            room["next_top_announce_at"] = now + _dep_config.ANNOUNCE_TOP_INTERVAL
    if _dep_config.UPDATE_ROOM_TOPIC and _dep_config.TOPIC_UPDATE_INTERVAL > 0:
        next_at = int(room.get("next_topic_update_at", 0) or 0)
        if now >= next_at:
            _maybe_set_room_topic(bot, room_jid, room)
            room["next_topic_update_at"] = now + _dep_config.TOPIC_UPDATE_INTERVAL


def _usage(bot) -> str:
    prefix = _command_prefix(bot)
    return (
        "🎲 IdleRPG usage:\n"
        "Player commands:\n"
        f"{prefix}idlerpg register <character> <class>\n"
        f"{prefix}idlerpg login|logout|remove-me\n"
        f"{prefix}idlerpg status [character]\n"
        f"{prefix}idlerpg top|players [page|last|all]\n"
        f"{prefix}idlerpg items|profile|achievements [character]\n"
        f"{prefix}idlerpg achievements list\n"
        f"{prefix}idlerpg title <achievement|none>\n"
        f"{prefix}idlerpg align <good|neutral|evil>\n"
        f"{prefix}idlerpg duel <character>\n"
        f"{prefix}idlerpg quest|map|hof|season\n"
        f"{prefix}idlerpg events [page|last|all]\n"
        f"{prefix}idlerpg help\n"
        "Room owner/admin commands:\n"
        f"{prefix}idlerpg on|off|enabled\n"
        f"{prefix}idlerpg stats\n"
        f"{prefix}idlerpg push <character> <duration>\n"
        f"{prefix}idlerpg setlevel <character> <level>\n"
        f"{prefix}idlerpg reset <character>\n"
        f"{prefix}idlerpg delete <character>\n"
        f"{prefix}idlerpg delold <days> [confirm]\n"
        f"{prefix}idlerpg announce top\n"
        f"{prefix}idlerpg topic update [custom text]\n"
        f"{prefix}idlerpg export\n"
        f"{prefix}idlerpg season end\n"
        f"{prefix}idlerpg season reset\n"
        f"{prefix}idlerpg season discard confirm\n"
        f"{prefix}idlerpg season extend [duration|manual]\n"
        f"{prefix}idlerpg season clear-end\n"
        f"{prefix}idlerpg hof clear confirm"
    )

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import state as _dep_state  # noqa: E402
