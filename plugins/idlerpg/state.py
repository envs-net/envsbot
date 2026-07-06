"""Split module for plugins/idlerpg.py: state."""

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


def _blank_room() -> dict[str, Any]:
    now = _now()
    return {
        "players": {},
        "name_index": {},
        "quest": {"active": False, "next_at": now + QUEST_INTERVAL},
        "season": _blank_season(now),
        "hall_of_fame": [],
        "events": [],
        "last_tick": now,
        "next_top_announce_at": now + ANNOUNCE_TOP_INTERVAL if ANNOUNCE_TOP_INTERVAL > 0 else 0,
        "next_topic_update_at": now + TOPIC_UPDATE_INTERVAL if TOPIC_UPDATE_INTERVAL > 0 else 0,
        "created_at": now,
    }


async def _get_data(bot) -> dict[str, Any]:
    store = await get_idlerpg_store(bot)
    data = await store.get_global(IDLERPG_DATA_KEY, default={})
    return data if isinstance(data, dict) else {}


async def _set_data(bot, data: dict[str, Any]) -> None:
    store = await get_idlerpg_store(bot)
    await store.set_global(IDLERPG_DATA_KEY, data)
    _export_public_state(data)


def _room_bucket(data: dict[str, Any], room_jid: str) -> dict[str, Any]:
    rooms = data.setdefault("rooms", {})
    if not isinstance(rooms, dict):
        rooms = {}
        data["rooms"] = rooms
    room = rooms.setdefault(room_jid, _blank_room())
    if not isinstance(room, dict):
        room = _blank_room()
        rooms[room_jid] = room
    room.setdefault("players", {})
    room.setdefault("name_index", {})
    room.setdefault("quest", {"active": False, "next_at": _now() + QUEST_INTERVAL})
    room.setdefault("season", _blank_season(_now()))
    room.setdefault("hall_of_fame", [])
    room.setdefault("events", [])
    _prune_events(room)
    room.setdefault("last_tick", _now())
    room.setdefault("next_top_announce_at", _now() + ANNOUNCE_TOP_INTERVAL if ANNOUNCE_TOP_INTERVAL > 0 else 0)
    room.setdefault("next_topic_update_at", _now() + TOPIC_UPDATE_INTERVAL if TOPIC_UPDATE_INTERVAL > 0 else 0)
    return room


def _normalize_player(jid: str, player: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    items = player.get("items")
    if not isinstance(items, dict):
        items = {}
    for item in ITEMS:
        try:
            items[item] = int(items.get(item, 0) or 0)
        except (TypeError, ValueError):
            items[item] = 0

    unique_items = player.get("unique_items")
    if not isinstance(unique_items, dict):
        unique_items = {}
    unique_items = {str(k): str(v) for k, v in unique_items.items() if str(k) in ITEMS and str(v).strip()}

    penalties = player.get("penalties")
    if not isinstance(penalties, dict):
        penalties = {}

    stats = player.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    cleaned_stats: dict[str, int] = {}
    for key, value in stats.items():
        try:
            cleaned_stats[str(key)] = max(0, int(value or 0))
        except (TypeError, ValueError):
            cleaned_stats[str(key)] = 0

    pending_logout = player.get("pending_logout_penalty")
    if not isinstance(pending_logout, dict):
        pending_logout = {}

    try:
        level = int(player.get("level", 0) or 0)
    except (TypeError, ValueError):
        level = 0

    try:
        ttl = int(player.get("next", _ttl_for_level(level)) or 0)
    except (TypeError, ValueError):
        ttl = _ttl_for_level(level)

    achievements = player.get("achievements")
    if not isinstance(achievements, list):
        achievements = []
    achievements = sorted({str(value) for value in achievements if str(value) in ACHIEVEMENTS})
    title = str(player.get("title") or "")
    if title not in achievements:
        title = ""

    player.update({
        "jid": str(player.get("jid") or jid),
        "name": _safe_name(str(player.get("name") or jid.split("@", 1)[0])) or "player",
        "class": _safe_class(str(player.get("class") or "idler")) or "idler",
        "level": max(0, level),
        "next": max(0, ttl),
        "idled": int(player.get("idled", 0) or 0),
        "created_at": int(player.get("created_at", now) or now),
        "last_login": int(player.get("last_login", now) or now),
        "last_seen": int(player.get("last_seen", now) or now),
        "alignment": str(player.get("alignment") or "n")[:1].lower(),
        "items": items,
        "unique_items": unique_items,
        "penalties": penalties,
        "stats": cleaned_stats,
        "pending_logout_penalty": pending_logout,
        "logged_out_at": int(player.get("logged_out_at", 0) or 0),
        "achievements": achievements,
        "title": title,
        "x": int(player.get("x", random.randint(0, MAP_X)) or 0),
        "y": int(player.get("y", random.randint(0, MAP_Y)) or 0),
        "logged_out": bool(player.get("logged_out", False)),
    })
    if player["alignment"] not in {"g", "n", "e"}:
        player["alignment"] = "n"
    player["x"] %= max(1, MAP_X + 1)
    player["y"] %= max(1, MAP_Y + 1)
    return player


def _rebuild_name_index(room: dict[str, Any]) -> dict[str, str]:
    players = room.get("players", {})
    index: dict[str, str] = {}
    for jid, player in players.items():
        if isinstance(player, dict):
            name = str(player.get("name") or "").lower()
            if name:
                index[name] = str(jid)
    room["name_index"] = index
    return index


def _find_player(room: dict[str, Any], name_or_jid: str | None) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    if not name_or_jid:
        return None, None
    players = room.get("players", {})
    value = str(name_or_jid).strip()
    if value in players and isinstance(players[value], dict):
        return value, players[value]
    index = room.get("name_index")
    if not isinstance(index, dict):
        index = _rebuild_name_index(room)
    jid = index.get(value.lower())
    if jid and isinstance(players.get(jid), dict):
        return jid, players[jid]
    return None, None


def _online_jids(room_jid: str) -> set[str]:
    room = JOINED_ROOMS.get(room_jid, {})
    nicks = room.get("nicks", {}) if isinstance(room, dict) else {}
    result: set[str] = set()
    if not isinstance(nicks, dict):
        return result
    for info in nicks.values():
        if isinstance(info, dict) and info.get("jid"):
            result.add(str(info["jid"]).split("/", 1)[0])
    return result


def _is_player_online(room_jid: str, jid: str, player: dict[str, Any]) -> bool:
    return not bool(player.get("logged_out")) and str(jid) in _online_jids(room_jid)


def _format_player_status(room_jid: str, jid: str, player: dict[str, Any]) -> str:
    online = "online" if _is_player_online(room_jid, jid, player) else "offline"
    title = _display_title(player)
    title_part = f" [{title}]" if title else ""
    return (
        f"{_display_player(player)}{title_part}, the level {player.get('level', 0)} "
        f"{player.get('class', 'idler')} ({_alignment_name(player.get('alignment'))}); "
        f"Status: {online}; TTL: {_duration(player.get('next', 0))}; "
        f"Idled: {_duration(player.get('idled', 0))}; "
        f"Map: [{player.get('x', 0)},{player.get('y', 0)}]; "
        f"Achievements: {len(player.get('achievements', []) if isinstance(player.get('achievements'), list) else [])}; "
        f"Item sum: {sum(int(v or 0) for v in player.get('items', {}).values())}"
    )


def _ranked_players(room: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    players = [
        (str(jid), _normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
    ]
    players.sort(
        key=lambda item: (
            -int(item[1].get("level", 0) or 0),
            int(item[1].get("next", 0) or 0),
            str(item[1].get("name", "")).lower(),
        )
    )
    return players


def _choose_two_players(players: list[tuple[str, dict[str, Any]]]) -> tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]] | None:
    if len(players) < 2:
        return None
    first = random.choice(players)
    remaining = [item for item in players if item[0] != first[0]]
    if not remaining:
        return None
    return first, random.choice(remaining)


def _room_from_context(msg, is_room: bool) -> str | None:
    if is_room and msg.get("type") == "groupchat":
        return str(msg["from"].bare)
    if msg.get("type") in ("chat", "normal"):
        room = str(getattr(msg["from"], "bare", ""))
        if room in JOINED_ROOMS and getattr(msg["from"], "resource", None):
            return room
    return None


async def _sender_can_manage_room(bot, sender_jid: str | None, room_jid: str | None) -> bool:
    if not sender_jid:
        return False
    get_role = getattr(bot, "get_user_role", None)
    if not callable(get_role):
        return False
    try:
        if room_jid:
            role = await get_role(str(sender_jid), room_jid)
        else:
            role = await get_role(str(sender_jid))
        # IdleRPG admin actions mutate game state and public exports. Keep those
        # operations limited to room owners/admins, not normal moderators.
        return role <= Role.ADMIN
    except Exception:
        log.debug("[IDLERPG] Could not resolve sender role", exc_info=True)
        return False


async def _enabled_rooms(bot) -> dict[str, bool]:
    store = await get_idlerpg_store(bot)
    state = await store.get_global(IDLERPG_ENABLED_KEY, default={})
    if not isinstance(state, dict):
        return {}
    return {str(room_jid): bool(enabled) for room_jid, enabled in state.items()}
