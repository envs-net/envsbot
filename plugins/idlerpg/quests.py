"""Split module for plugins/idlerpg.py: quests."""

from __future__ import annotations
import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from functools import partial
from typing import Any
from utils.audit import audit_event
from utils.command import Role, command
from utils.config import BASE_DIR, config
from utils.formatting import format_page, parse_page_args
from utils.task_supervisor import create_plugin_task
from core_plugins import _core
from core_plugins.rooms import JOINED_ROOMS


async def _maybe_run_quest(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    quest = room.setdefault("quest", {"active": False, "next_at": _now() + QUEST_INTERVAL})
    now = _now()
    if not isinstance(quest, dict):
        quest = {"active": False, "next_at": now + QUEST_INTERVAL}
        room["quest"] = quest

    if quest.get("active"):
        if now < int(quest.get("complete_at", 0) or 0):
            return
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
                _inc_stat(player, "quests_completed", 1)
                names.append(_display_player(player))
                completed_players.append(player)
                reward_per_player.append((player, reward_percent))
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
        return

    if now < int(quest.get("next_at", now + QUEST_INTERVAL) or 0):
        return

    candidates = [
        str(jid)
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
        and _is_player_online(room_jid, str(jid), player)
        and int(player.get("level", 0) or 0) >= QUEST_MIN_LEVEL
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
        f"Quest completes in {_duration_clock(duration)}.{url_part}"
    )
