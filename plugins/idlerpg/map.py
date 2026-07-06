"""Split module for plugins/idlerpg.py: map."""

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


def _map_region_name(x: int | float, y: int | float) -> str:
    try:
        px = float(x)
        py = float(y)
    except (TypeError, ValueError):
        return "the wilderness"
    for region in MAP_REGIONS:
        if (
            float(region["x1"]) <= px <= float(region["x2"])
            and float(region["y1"]) <= py <= float(region["y2"])
        ):
            return str(region["name"])
    return "the wilderness"


def _player_region(player: dict[str, Any]) -> str:
    return _map_region_name(int(player.get("x", 0) or 0), int(player.get("y", 0) or 0))


def _move_player(player: dict[str, Any], steps: int = 1) -> None:
    if MAP_STEP_PER_TICK <= 0:
        return
    steps = max(1, min(24, int(steps or 1)))
    for _ in range(steps):
        player["x"] = (int(player.get("x", 0) or 0) + random.randint(-MAP_STEP_PER_TICK, MAP_STEP_PER_TICK)) % max(1, MAP_X + 1)
        player["y"] = (int(player.get("y", 0) or 0) + random.randint(-MAP_STEP_PER_TICK, MAP_STEP_PER_TICK)) % max(1, MAP_Y + 1)


def _map_marker(index: int) -> str:
    alphabet = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(alphabet):
        return alphabet[index]
    return "+"


def _render_ascii_map(
    room_jid: str,
    players: list[tuple[str, dict[str, Any]]],
    quest: dict[str, Any] | None,
    *,
    width: int = 24,
    height: int = 10,
) -> list[str]:
    width = max(8, min(40, int(width or 24)))
    height = max(4, min(16, int(height or 10)))
    map_width = max(1, int(MAP_X) or 1)
    map_height = max(1, int(MAP_Y) or 1)
    grid = [["." for _ in range(width)] for _ in range(height)]
    legend: list[str] = []

    if isinstance(quest, dict) and quest.get("active") and isinstance(quest.get("route"), list):
        for point in quest.get("route", [])[:2]:
            if not isinstance(point, list | tuple) or len(point) < 2:
                continue
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            col = max(0, min(width - 1, int((x / map_width) * (width - 1))))
            row = max(0, min(height - 1, int((y / map_height) * (height - 1))))
            grid[row][col] = "Q"

    for index, (jid, player) in enumerate(players[:35]):
        marker = _map_marker(index)
        x = max(0, min(map_width, int(player.get("x", 0) or 0)))
        y = max(0, min(map_height, int(player.get("y", 0) or 0)))
        col = max(0, min(width - 1, int((x / map_width) * (width - 1))))
        row = max(0, min(height - 1, int((y / map_height) * (height - 1))))
        grid[row][col] = marker if grid[row][col] == "." else "*"
        status = "online" if _is_player_online(room_jid, jid, player) else "offline"
        legend.append(
            f"{marker} {_display_player(player)} [{x},{y}] lv.{player.get('level', 0)} {status}"
        )

    lines = [f"🗺️ IdleRPG map for {room_jid}: {MAP_X}x{MAP_Y}"]
    lines.append("+" + "-" * width + "+")
    lines.extend("|" + "".join(row) + "|" for row in grid)
    lines.append("+" + "-" * width + "+")
    if legend:
        lines.append("Legend:")
        lines.extend(legend[:12])
        if len(legend) > 12:
            lines.append(f"… and {len(legend) - 12} more players")
    else:
        lines.append("No players on the map yet.")
    if isinstance(quest, dict) and quest.get("active") and quest.get("route"):
        lines.append("Q = active quest route point")
    return lines
