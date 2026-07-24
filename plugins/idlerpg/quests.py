"""Split module for plugins/idlerpg.py: quests."""

from __future__ import annotations
import random
from typing import Any


def _quest_online_seconds(player: dict[str, Any], now: int) -> int:
    try:
        last_login = int(player.get("last_login", 0) or 0)
    except (TypeError, ValueError):
        last_login = 0
    if 0 < last_login <= int(now):
        return max(0, int(now) - last_login)
    try:
        return max(0, int(player.get("idled", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _quest_candidate_is_eligible(
    room_jid: str,
    jid: str,
    player: dict[str, Any],
    now: int,
) -> bool:
    return (
        _dep_state._is_player_online(room_jid, jid, player)
        and int(player.get("level", 0) or 0) >= _dep_config.QUEST_MIN_LEVEL
        and _quest_online_seconds(player, now) >= max(0, int(_dep_config.QUEST_MIN_ONLINE_SECONDS or 0))
    )


def _quest_type(quest: dict[str, Any] | None) -> str:
    """Return the active quest type, keeping older persisted quests usable."""
    if not isinstance(quest, dict):
        return "grid"
    explicit = str(quest.get("type") or "").strip().lower()
    if explicit in {"grid", "time"}:
        return explicit
    return "grid" if _dep_map._quest_route_points(quest) else "time"


def _quest_type_weights() -> list[tuple[str, float]]:
    """Return enabled quest types with sane positive fallback weights."""
    raw: list[tuple[str, float]] = []
    if _dep_config.QUEST_GRID_ENABLED:
        raw.append(("grid", max(0.0, float(_dep_config.QUEST_GRID_WEIGHT or 0.0))))
    if _dep_config.QUEST_TIME_ENABLED:
        raw.append(("time", max(0.0, float(_dep_config.QUEST_TIME_WEIGHT or 0.0))))
    if not raw:
        return []
    if sum(weight for _kind, weight in raw) <= 0:
        return [(kind, 1.0) for kind, _weight in raw]
    return raw


def _choose_quest_type() -> str | None:
    choices = _quest_type_weights()
    if not choices:
        return None
    total = sum(weight for _kind, weight in choices)
    pick = random.random() * total
    seen = 0.0
    for kind, weight in choices:
        seen += weight
        if pick <= seen:
            return kind
    return choices[-1][0]


def _quest_participants_online(
    room: dict[str, Any],
    room_jid: str,
    quest: dict[str, Any],
) -> bool:
    players = room.get("players", {})
    if not isinstance(players, dict):
        return False
    questers = [str(jid) for jid in quest.get("questers", [])]
    if not questers:
        return False
    for jid in questers:
        player = players.get(jid)
        if not isinstance(player, dict) or not _dep_state._is_player_online(room_jid, jid, player):
            return False
    return True


def _quest_reward_players(
    room: dict[str, Any],
    quest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[tuple[dict[str, Any], int]]]:
    players = room.get("players", {})
    questers = [str(jid) for jid in quest.get("questers", [])]
    completed_players: list[dict[str, Any]] = []
    names: list[str] = []
    reward_per_player: list[tuple[dict[str, Any], int]] = []
    for jid in questers:
        player = players.get(jid)
        if isinstance(player, dict):
            reward_percent = _dep_config.QUEST_REWARD_PERCENT + _dep_items._unique_bonus_percent(player, "quest_reward_bonus")
            player["next"] = int(int(player.get("next", 0)) * max(0, 100 - reward_percent) / 100)
            _dep_leveling._award(player, "quest_hero")
            _dep_leveling._inc_stat(player, "quests_completed", 1, room)
            names.append(_dep_formatting._display_player(player))
            completed_players.append(player)
            reward_per_player.append((player, reward_percent))
    return completed_players, names, reward_per_player


def _complete_quest(room: dict[str, Any], quest: dict[str, Any], now: int, messages: list[str]) -> None:
    completed_players, names, reward_per_player = _quest_reward_players(room, quest)
    if names:
        rewards = sorted({percent for _player, percent in reward_per_player})
        reward_text = f"{rewards[0]}%" if len(rewards) == 1 else f"{min(rewards)}-{max(rewards)}%"
        quest_label = "time-based quest" if _quest_type(quest) == "time" else "quest"
        messages.append(
            f"🧭 {', '.join(names)} completed their {quest_label}! "
            f"{reward_text} of their burden is removed."
        )
        for player in completed_players:
            messages.append(_dep_formatting._next_level_line(player))
    room["quest"] = {"active": False, "next_at": now + _dep_config.QUEST_INTERVAL}


def _fail_quest(
    room: dict[str, Any],
    room_jid: str,
    now: int,
    messages: list[str],
    *,
    detail: str | None = None,
) -> None:
    quest = room.get("quest") if isinstance(room.get("quest"), dict) else {}
    quest_kind = _quest_type(quest)
    players = room.get("players", {})
    questers = [str(jid) for jid in quest.get("questers", [])]
    penalized: list[str] = []
    for jid in dict.fromkeys(questers):
        player = players.get(jid) if isinstance(players, dict) else None
        if not isinstance(player, dict):
            continue
        changed = _dep_leveling._add_time(player, _dep_leveling._penalty_amount_for(player, 15, "quest"))
        penalties = player.setdefault("penalties", {})
        if isinstance(penalties, dict):
            penalties["quest"] = int(penalties.get("quest", 0) or 0) + changed
        _dep_leveling._inc_stat(player, "quest_failures", 1, room)
        penalized.append(_dep_formatting._display_player(player))
    if detail:
        base = detail.rstrip(".") + "."
    elif quest_kind == "time":
        base = "The time-based quest failed before the party could finish idling."
    else:
        base = "The quest failed before the route was completed."
    if penalized:
        messages.append(f"🧭 {base} {', '.join(penalized)} receive a p15 penalty.")
    else:
        messages.append(f"🧭 {base}")
    room["quest"] = {"active": False, "next_at": now + _dep_config.QUEST_INTERVAL}


def _maybe_fail_time_quest_for_penalty(
    room: dict[str, Any],
    room_jid: str,
    jid: str,
    now: int,
    messages: list[str],
    *,
    reason: str = "penalty",
) -> bool:
    quest = room.get("quest") if isinstance(room.get("quest"), dict) else None
    if not isinstance(quest, dict) or not quest.get("active") or _quest_type(quest) != "time":
        return False
    if str(jid) not in {str(value) for value in quest.get("questers", [])}:
        return False
    player = room.get("players", {}).get(str(jid)) if isinstance(room.get("players"), dict) else None
    name = _dep_formatting._display_player(player) if isinstance(player, dict) else str(jid)
    reason_text = str(reason or "penalty").replace("_", " ")
    _fail_quest(
        room,
        room_jid,
        now,
        messages,
        detail=f"{name} received a {reason_text} penalty, so the time-based quest failed",
    )
    return True


def _maybe_complete_time_quest(
    room: dict[str, Any],
    room_jid: str,
    quest: dict[str, Any],
    now: int,
    messages: list[str],
) -> bool:
    """Complete or fail an active time-based quest when its timer expires."""
    if now < int(quest.get("complete_at", 0) or 0):
        return True
    if not _quest_participants_online(room, room_jid, quest):
        _fail_quest(
            room,
            room_jid,
            now,
            messages,
            detail="The time-based quest reached its end, but not all questers were still online",
        )
        return True
    _complete_quest(room, quest, now, messages)
    return True


def _maybe_advance_grid_quest(
    room: dict[str, Any],
    room_jid: str,
    quest: dict[str, Any],
    now: int,
    messages: list[str],
) -> bool:
    """Advance or complete an active grid quest.

    Returns True when the active quest state was handled and no further quest
    processing should happen in the current tick.
    """
    points = _dep_map._quest_route_points(quest)
    if not points:
        if now >= int(quest.get("complete_at", 0) or 0):
            _fail_quest(
                room,
                room_jid,
                now,
                messages,
                detail="The grid quest had no route to complete",
            )
        return True

    if _dep_map._questers_at_target(room.get("players", {}), quest, room_jid=room_jid):
        route_index = max(0, int(quest.get("route_index", 0) or 0))
        target = points[min(route_index, len(points) - 1)]
        if route_index + 1 >= len(points):
            _complete_quest(room, quest, now, messages)
        else:
            quest["route_index"] = route_index + 1
            next_target = points[route_index + 1]
            messages.append(
                f"🧭 The quest party reached [{target[0]},{target[1]}] "
                f"and now heads for [{next_target[0]},{next_target[1]}]."
            )
        return True

    if now >= int(quest.get("complete_at", 0) or 0):
        _fail_quest(room, room_jid, now, messages)
    return True


def _quester_names(room: dict[str, Any], questers: list[str]) -> list[str]:
    names = []
    players = room.get("players", {}) if isinstance(room.get("players"), dict) else {}
    for jid in questers:
        player = players.get(jid)
        if isinstance(player, dict):
            _dep_leveling._award(player, "quester")
            names.append(str(player.get("name", jid)))
    return names


def _start_time_quest(
    room: dict[str, Any],
    room_jid: str,
    questers: list[str],
    quest_text: str,
    now: int,
    messages: list[str],
) -> None:
    min_duration = max(1, int(_dep_config.QUEST_TIME_MIN_DURATION or 1))
    max_duration = max(min_duration, int(_dep_config.QUEST_TIME_MAX_DURATION or min_duration))
    duration = random.randint(min_duration, max_duration)
    room["quest"] = {
        "active": True,
        "type": "time",
        "questers": questers,
        "text": quest_text,
        "started_at": now,
        "complete_at": now + duration,
    }
    names = _quester_names(room, questers)
    quest_url = _dep_export._website_url("quest")
    url_part = f" See {quest_url} to monitor the quest." if quest_url else ""
    messages.append(
        f"🧭 {', '.join(names)} have been chosen to {quest_text}. "
        f"This is a time-based quest: no quester may receive a penalty for {_dep_formatting._duration_clock(duration)}."
        f"{url_part}"
    )


def _start_grid_quest(
    room: dict[str, Any],
    room_jid: str,
    questers: list[str],
    quest_text: str,
    now: int,
    messages: list[str],
) -> None:
    min_duration = max(1, int(_dep_config.QUEST_MIN_DURATION or 1))
    max_duration = max(min_duration, int(_dep_config.QUEST_MAX_DURATION or min_duration))
    duration = random.randint(min_duration, max_duration)
    route = [
        [random.randint(0, _dep_config.MAP_X), random.randint(0, _dep_config.MAP_Y)],
        [random.randint(0, _dep_config.MAP_X), random.randint(0, _dep_config.MAP_Y)],
    ]
    room["quest"] = {
        "active": True,
        "type": "grid",
        "questers": questers,
        "text": quest_text,
        "started_at": now,
        "complete_at": now + duration,
        "route": route,
        "route_index": 0,
    }
    names = _quester_names(room, questers)
    first_region = _dep_map._map_region_name(route[0][0], route[0][1])
    second_region = _dep_map._map_region_name(route[1][0], route[1][1])
    quest_url = _dep_export._website_url("quest")
    url_part = f" See {quest_url} to monitor their journey." if quest_url else ""
    messages.append(
        f"🧭 {', '.join(names)} have been chosen to {quest_text}. "
        f"This is a grid-based quest: participants must first reach "
        f"[{route[0][0]},{route[0][1]}] near {first_region}, then "
        f"[{route[1][0]},{route[1][1]}] near {second_region}. "
        f"Quest deadline in {_dep_formatting._duration_clock(duration)}.{url_part}"
    )


async def _maybe_run_quest(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    quest = room.setdefault("quest", {"active": False, "next_at": _dep_formatting._now() + _dep_config.QUEST_INTERVAL})
    now = _dep_formatting._now()
    if not isinstance(quest, dict):
        quest = {"active": False, "next_at": now + _dep_config.QUEST_INTERVAL}
        room["quest"] = quest

    if quest.get("active"):
        if _quest_type(quest) == "time":
            _maybe_complete_time_quest(room, room_jid, quest, now, messages)
        else:
            _maybe_advance_grid_quest(room, room_jid, quest, now, messages)
        return

    if now < int(quest.get("next_at", now + _dep_config.QUEST_INTERVAL) or 0):
        return

    quest_type = _choose_quest_type()
    if quest_type is None:
        quest["next_at"] = now + _dep_config.QUEST_INTERVAL
        return

    candidates = [
        str(jid)
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
        and _quest_candidate_is_eligible(room_jid, str(jid), player, now)
    ]
    if len(candidates) < 4:
        quest["next_at"] = now + _dep_config.QUEST_INTERVAL
        return
    random.shuffle(candidates)
    questers = candidates[:4]
    quest_text = random.choice(_dep_constants.QUEST_TEXTS)
    if quest_type == "time":
        _start_time_quest(room, room_jid, questers, quest_text, now, messages)
    else:
        _start_grid_quest(room, room_jid, questers, quest_text, now, messages)

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import export as _dep_export  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import items as _dep_items  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import map as _dep_map  # noqa: E402
from . import state as _dep_state  # noqa: E402
