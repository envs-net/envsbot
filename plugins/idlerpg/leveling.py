"""Split module for plugins/idlerpg.py: leveling."""

from __future__ import annotations

from typing import Any


def _add_time(player: dict[str, Any], amount: int | float) -> int:
    amount = max(0, int(amount or 0))
    player["next"] = max(0, int(player.get("next", 0) or 0)) + amount
    return amount


def _remove_time(player: dict[str, Any], amount: int | float) -> int:
    amount = max(0, int(amount or 0))
    current = max(0, int(player.get("next", 0) or 0))
    removed = min(current, amount)
    player["next"] = current - removed
    return removed


def _ttl_for_level(level: int) -> int:
    """Return the original IdleRPG TTL for a level.

    Classic IdleRPG uses ``600 * 1.16^level`` through level 60 and then
    switches to a linear +1 day increment for each level beyond 60.  The
    linear high-level tail avoids exponential values becoming absurdly huge.
    """
    level = max(0, int(level))
    if level <= 60:
        return max(1, int(_dep_config.RP_BASE * (_dep_config.RP_STEP ** level)))
    level_60_ttl = max(1, int(_dep_config.RP_BASE * (_dep_config.RP_STEP ** 60)))
    return level_60_ttl + ((level - 60) * 86400)


def _penalty_for(level: int, base: int) -> int:
    value = max(0, int(base * (_dep_config.PENALTY_STEP ** max(0, int(level)))))
    if _dep_config.MAX_PENALTY and value > _dep_config.MAX_PENALTY:
        return _dep_config.MAX_PENALTY
    return value


def _penalty_amount_for(player: dict[str, Any], base: int, reason: str) -> int:
    amount = _penalty_for(int(player.get("level", 0)), base)
    if reason == "message":
        amount = _dep_items._adjust_percent_amount(amount, player, "message_penalty_reduction")
    elif reason == "logout":
        amount = _dep_items._adjust_percent_amount(amount, player, "logout_penalty_reduction")
    return amount


def _stats(player: dict[str, Any]) -> dict[str, int]:
    stats = player.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        player["stats"] = stats
    cleaned: dict[str, int] = {}
    for key, value in stats.items():
        try:
            cleaned[str(key)] = max(0, int(value or 0))
        except (TypeError, ValueError):
            cleaned[str(key)] = 0
    player["stats"] = cleaned
    return cleaned


def _inc_stat(
    player: dict[str, Any],
    key: str,
    amount: int = 1,
    room: dict[str, Any] | None = None,
) -> list[str]:
    stats = _stats(player)
    stats[key] = max(0, int(stats.get(key, 0) or 0) + int(amount or 0))
    return _check_level_achievements(player, room)


def _achievement_catalog() -> list[dict[str, str]]:
    return [
        {"key": key, "title": title, "description": description}
        for key, (title, description) in sorted(_dep_constants.ACHIEVEMENTS.items())
    ]


def _season_gate_passed(room: dict[str, Any] | None, required_days: int) -> bool:
    if room is None or not _dep_config.SEASON_ACHIEVEMENT_GATES_ENABLED or required_days <= 0:
        return True
    return _dep_seasons._season_age_days(room) >= required_days


def _achievement_keys(player: dict[str, Any]) -> set[str]:
    achievements = player.get("achievements")
    if not isinstance(achievements, list):
        return set()
    return {str(value) for value in achievements if str(value) in _dep_constants.ACHIEVEMENTS}


def _achievement_announcement(player: dict[str, Any], achievement: str) -> str:
    title = _achievement_title(achievement)
    description = _achievement_description(achievement)
    detail = f" — {description}" if description else ""
    return f"🏅 {_dep_formatting._display_player(player)} unlocked achievement: {title}{detail}."


def _achievement_announcements(
    player: dict[str, Any],
    previous: set[str] | list[str] | tuple[str, ...],
) -> list[str]:
    previous_keys = {str(value) for value in previous if str(value) in _dep_constants.ACHIEVEMENTS}
    new_keys = sorted(_achievement_keys(player) - previous_keys)
    return [_achievement_announcement(player, key) for key in new_keys]


def _award(player: dict[str, Any], achievement: str) -> bool:
    if achievement not in _dep_constants.ACHIEVEMENTS:
        return False
    current = player.setdefault("achievements", [])
    if not isinstance(current, list):
        current = []
        player["achievements"] = current
    if achievement in current:
        return False
    current.append(achievement)
    current.sort()
    return True


def _achievement_title(achievement: str) -> str:
    return _dep_constants.ACHIEVEMENTS.get(achievement, (achievement, ""))[0]


def _achievement_description(achievement: str) -> str:
    return _dep_constants.ACHIEVEMENTS.get(achievement, (achievement, ""))[1]


def _check_level_achievements(player: dict[str, Any], room: dict[str, Any] | None = None) -> list[str]:
    previous = _achievement_keys(player)
    level = int(player.get("level", 0) or 0)
    if level >= 10:
        _award(player, "level_10")
    if level >= 25:
        _award(player, "level_25")
    if level >= 50 and _season_gate_passed(room, 3):
        _award(player, "level_50")
    if level >= _dep_config.LEVEL_REWARD_MIN_LEVEL and _season_gate_passed(room, 3):
        _award(player, "level_reward_50")
    if level >= 75 and _season_gate_passed(room, 7):
        _award(player, "level_75")
        _award(player, "level_reward_75")
    if level >= 100 and _season_gate_passed(room, 14):
        _award(player, "level_100")
    idled = int(player.get("idled", 0) or 0)
    if idled >= 86400:
        _award(player, "silent_24h")
    if idled >= 3 * 86400 and _season_gate_passed(room, 3):
        _award(player, "season_day_3")
    if idled >= 604800 and _season_gate_passed(room, 7):
        _award(player, "silent_week")
        _award(player, "season_week_1")
    item_sum = _dep_items._item_sum(player)
    if item_sum >= 100:
        _award(player, "collector")
    if item_sum >= 500:
        _award(player, "hoarder")
    stats = _stats(player)
    if stats.get("battles_won", 0) >= 10:
        _award(player, "battle_scarred")
    if stats.get("team_battles_won", 0) >= 5:
        _award(player, "team_veteran")
    if stats.get("bosses_defeated", 0) >= 5:
        _award(player, "boss_veteran")
    if stats.get("quests_completed", 0) >= 3 and _season_gate_passed(room, 7):
        _award(player, "quest_walker")
    if stats.get("godsends", 0) >= 10:
        _award(player, "very_lucky")
    if stats.get("calamities", 0) >= 10:
        _award(player, "the_unlucky")
    unique_items = player.get("unique_items", {})
    if isinstance(unique_items, dict) and len(unique_items) >= 3:
        _award(player, "artifact_finder")
    return sorted(_achievement_keys(player) - previous)


def _apply_logout_penalty(player: dict[str, Any], room: dict[str, Any] | None = None) -> int:
    changed = _add_time(player, _penalty_amount_for(player, _dep_config.LOGOUT_PENALTY, "logout"))
    penalties = player.setdefault("penalties", {})
    penalties["logout"] = int(penalties.get("logout", 0) or 0) + changed
    player["pending_logout_penalty"] = {}
    _inc_stat(player, "logouts", 1, room)
    return changed


def _maybe_apply_pending_logout_penalty(
    player: dict[str, Any],
    messages: list[str],
    room: dict[str, Any] | None = None,
    *,
    room_jid: str | None = None,
    jid: str | None = None,
) -> None:
    pending = player.get("pending_logout_penalty")
    if not isinstance(pending, dict) or not pending:
        return
    due_at = int(pending.get("due_at", 0) or 0)
    if due_at > _dep_formatting._now():
        return
    changed = _apply_logout_penalty(player, room)
    name = _dep_formatting._display_player(player)
    messages.append(
        f"👋 {name} stayed logged out past the grace period. "
        f"{_dep_formatting._duration_clock(changed)} is added to {_dep_formatting._possessive(name)} clock."
    )
    messages.append(_dep_formatting._next_level_line(player))
    if room is not None and room_jid and jid and changed:
        _dep_quests._maybe_fail_time_quest_for_penalty(
            room,
            str(room_jid),
            str(jid),
            _dep_formatting._now(),
            messages,
            reason="logout",
        )


async def _penalize_player(
    bot,
    room_jid: str,
    jid: str,
    reason: str,
    amount: int,
    *,
    announce: bool = False,
) -> int:
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _player_jid, player = _dep_state._find_player(room, jid)
    if not player:
        return 0
    player = _dep_state._normalize_player(jid, player)
    penalty = _penalty_amount_for(player, amount, reason)
    changed = _add_time(player, penalty)
    penalties = player.setdefault("penalties", {})
    penalties[reason] = int(penalties.get(reason, 0) or 0) + changed
    if reason == "message":
        _inc_stat(player, "messages", 1, room)
    quest_messages: list[str] = []
    if changed:
        _dep_quests._maybe_fail_time_quest_for_penalty(
            room,
            room_jid,
            str(_player_jid or jid),
            _dep_formatting._now(),
            quest_messages,
            reason=reason,
        )
        for text in quest_messages:
            _dep_export._record_event(room, "quest", text)
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    if announce and changed:
        _dep_formatting._system_reply(
            bot,
            room_jid,
            f"⏳ {_dep_formatting._display_player(player)} is penalized {_dep_formatting._duration_clock(changed)} for {reason}. "
            + _dep_formatting._next_level_line(player),
        )
    for text in quest_messages:
        _dep_formatting._system_reply(bot, room_jid, text)
    return changed

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import export as _dep_export  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import items as _dep_items  # noqa: E402
from . import quests as _dep_quests  # noqa: E402
from . import seasons as _dep_seasons  # noqa: E402
from . import state as _dep_state  # noqa: E402
