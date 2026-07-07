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
        _is_player_online(room_jid, jid, player)
        and int(player.get("level", 0) or 0) >= QUEST_MIN_LEVEL
        and _quest_online_seconds(player, now) >= max(0, int(QUEST_MIN_ONLINE_SECONDS or 0))
    )


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
            reward_percent = QUEST_REWARD_PERCENT + _unique_bonus_percent(player, "quest_reward_bonus")
            player["next"] = int(int(player.get("next", 0)) * max(0, 100 - reward_percent) / 100)
            _award(player, "quest_hero")
            _inc_stat(player, "quests_completed", 1, room)
            names.append(_display_player(player))
            completed_players.append(player)
            reward_per_player.append((player, reward_percent))
    return completed_players, names, reward_per_player


def _complete_quest(room: dict[str, Any], quest: dict[str, Any], now: int, messages: list[str]) -> None:
    completed_players, names, reward_per_player = _quest_reward_players(room, quest)
    if names:
        rewards = sorted({percent for _player, percent in reward_per_player})
        reward_text = f"{rewards[0]}%" if len(rewards) == 1 else f"{min(rewards)}-{max(rewards)}%"
        messages.append(
            f"🧭 {', '.join(names)} completed their quest! "
            f"{reward_text} of their burden is removed."
        )
        for player in completed_players:
            messages.append(_next_level_line(player))
    room["quest"] = {"active": False, "next_at": now + QUEST_INTERVAL}


def _fail_quest(room: dict[str, Any], room_jid: str, now: int, messages: list[str]) -> None:
    players = room.get("players", {})
    penalized: list[str] = []
    for jid, player in players.items():
        if not isinstance(player, dict) or not _is_player_online(room_jid, str(jid), player):
            continue
        changed = _add_time(player, _penalty_amount_for(player, 15, "quest"))
        penalties = player.setdefault("penalties", {})
        if isinstance(penalties, dict):
            penalties["quest"] = int(penalties.get("quest", 0) or 0) + changed
        _inc_stat(player, "quest_failures", 1, room)
        penalized.append(_display_player(player))
    if penalized:
        messages.append(
            f"🧭 The quest failed before the route was completed. "
            f"{', '.join(penalized)} receive a p15 penalty."
        )
    else:
        messages.append("🧭 The quest failed before the route was completed.")
    room["quest"] = {"active": False, "next_at": now + QUEST_INTERVAL}


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
    points = _quest_route_points(quest)
    if not points:
        if now >= int(quest.get("complete_at", 0) or 0):
            _complete_quest(room, quest, now, messages)
        return True

    if _questers_at_target(room.get("players", {}), quest, room_jid=room_jid):
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


async def _maybe_run_quest(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    quest = room.setdefault("quest", {"active": False, "next_at": _now() + QUEST_INTERVAL})
    now = _now()
    if not isinstance(quest, dict):
        quest = {"active": False, "next_at": now + QUEST_INTERVAL}
        room["quest"] = quest

    if quest.get("active"):
        _maybe_advance_grid_quest(room, room_jid, quest, now, messages)
        return

    if now < int(quest.get("next_at", now + QUEST_INTERVAL) or 0):
        return

    candidates = [
        str(jid)
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
        and _quest_candidate_is_eligible(room_jid, str(jid), player, now)
    ]
    if len(candidates) < 4:
        quest["next_at"] = now + QUEST_INTERVAL
        return
    random.shuffle(candidates)
    questers = candidates[:4]
    duration = random.randint(max(1, QUEST_MIN_DURATION), max(QUEST_MIN_DURATION, QUEST_MAX_DURATION))
    quest_text = random.choice(QUEST_TEXTS)
    route = [
        [random.randint(0, MAP_X), random.randint(0, MAP_Y)],
        [random.randint(0, MAP_X), random.randint(0, MAP_Y)],
    ]
    room["quest"] = {
        "active": True,
        "questers": questers,
        "text": quest_text,
        "started_at": now,
        "complete_at": now + duration,
        "route": route,
        "route_index": 0,
    }
    names = []
    for jid in questers:
        player = room["players"].get(jid)
        if isinstance(player, dict):
            _award(player, "quester")
            names.append(player.get("name", jid))
    first_region = _map_region_name(route[0][0], route[0][1])
    second_region = _map_region_name(route[1][0], route[1][1])
    quest_url = _public_url(_room_slug(room_jid), "map.json")
    url_part = f" See {quest_url} to monitor their journey." if quest_url else ""
    messages.append(
        f"🧭 {', '.join(names)} have been chosen to {quest_text}. "
        f"Participants must first reach [{route[0][0]},{route[0][1]}] near {first_region}, "
        f"then [{route[1][0]},{route[1][1]}] near {second_region}. "
        f"Quest deadline in {_duration_clock(duration)}.{url_part}"
    )
