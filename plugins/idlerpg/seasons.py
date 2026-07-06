"""Split module for plugins/idlerpg.py: seasons."""

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


def _season_id(ts: int | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(int(ts or _now())))


def _season_duration_seconds() -> int:
    return max(0, int(SEASON_DURATION_DAYS) * 86400)


def _season_age_days(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    season = room.get("season")
    if not isinstance(season, dict):
        return 0
    started_at = int(season.get("started_at", _now()) or _now())
    return max(0, int((_now() - started_at) // 86400))


def _blank_season(now: int | None = None) -> dict[str, Any]:
    now = int(now or _now())
    duration = _season_duration_seconds()
    return {
        "id": _season_id(now),
        "started_at": now,
        "ends_at": now + duration if duration else 0,
    }


def _season_snapshot(room_jid: str, room: dict[str, Any], ended_at: int | None = None) -> dict[str, Any]:
    ended_at = int(ended_at or _now())
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(ended_at)
    ranked = _ranked_players(room)[:SEASON_HOF_SIZE]
    return {
        "id": season.get("id") or _season_id(ended_at),
        "room": room_jid,
        "started_at": int(season.get("started_at", 0) or 0),
        "ended_at": ended_at,
        "champion": _display_player(ranked[0][1]) if ranked else "",
        "top": [
            _player_public_record(room_jid, jid, player, rank=rank)
            for rank, (jid, player) in enumerate(ranked, start=1)
        ],
    }


def _reset_player_for_new_season(player: dict[str, Any]) -> None:
    player["level"] = 0
    player["next"] = _ttl_for_level(0)
    player["idled"] = 0
    player["items"] = {item: 0 for item in ITEMS}
    player["unique_items"] = {}
    player["penalties"] = {}
    player["achievements"] = []
    player["title"] = ""


def _end_season(room_jid: str, room: dict[str, Any], *, reset_players: bool | None = None) -> dict[str, Any]:
    now = _now()
    snapshot = _season_snapshot(room_jid, room, now)
    hof = room.setdefault("hall_of_fame", [])
    if not isinstance(hof, list):
        hof = []
        room["hall_of_fame"] = hof
    hof.append(snapshot)
    del hof[:-max(1, SEASON_HOF_SIZE * 5)]
    should_reset = reset_players if reset_players is not None else SEASON_RESET_ON_ROLLOVER
    if should_reset:
        for jid, player in room.get("players", {}).items():
            if isinstance(player, dict):
                _reset_player_for_new_season(_normalize_player(str(jid), player))
    room["season"] = _blank_season(now)
    _record_event(
        room,
        "season",
        f"Season {snapshot.get('id')} ended. Champion: {snapshot.get('champion') or 'no champion'}.",
        players=[str(snapshot.get("champion") or "")],
        data={"season_id": snapshot.get("id"), "champion": snapshot.get("champion") or ""},
    )
    return snapshot


def _maybe_rollover_season(room_jid: str, room: dict[str, Any], messages: list[str]) -> None:
    if not SEASON_ENABLED or _season_duration_seconds() <= 0:
        return
    season = room.get("season")
    if not isinstance(season, dict):
        room["season"] = _blank_season(_now())
        return
    ends_at = int(season.get("ends_at", 0) or 0)
    if ends_at <= 0 or _now() < ends_at:
        return
    snapshot = _end_season(room_jid, room)
    champion = snapshot.get("champion") or "no champion"
    messages.append(
        f"🏁 IdleRPG season {snapshot.get('id')} has ended. Champion: {champion}. "
        f"New season {room['season']['id']} has begun."
    )


def _season_end_summary(season: dict[str, Any]) -> str:
    ends_at = int(season.get("ends_at", 0) or 0)
    return _duration(ends_at - _now()) if ends_at else "manual"
