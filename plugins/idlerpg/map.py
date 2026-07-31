"""Split module for plugins/idlerpg.py: map."""

from __future__ import annotations
import random
from typing import Any


def _map_region_name(x: int | float, y: int | float) -> str:
    try:
        px = float(x)
        py = float(y)
    except (TypeError, ValueError):
        return "the wilderness"
    for region in _dep_constants.MAP_REGIONS:
        if (
            float(region["x1"]) <= px <= float(region["x2"])
            and float(region["y1"]) <= py <= float(region["y2"])
        ):
            return str(region["name"])
    return "the wilderness"


def _player_region(player: dict[str, Any]) -> str:
    return _map_region_name(int(player.get("x", 0) or 0), int(player.get("y", 0) or 0))


def _clamp_grid_coord(value: Any, maximum: int) -> int:
    try:
        coord = int(value or 0)
    except (TypeError, ValueError):
        coord = 0
    return max(0, min(max(0, int(maximum or 0)), coord))


def _quest_route_points(quest: dict[str, Any] | None) -> list[tuple[int, int]]:
    if not isinstance(quest, dict) or not quest.get("active"):
        return []
    route = quest.get("route")
    if not isinstance(route, list):
        return []
    points: list[tuple[int, int]] = []
    for point in route:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        points.append((_clamp_grid_coord(point[0], _dep_config.MAP_X), _clamp_grid_coord(point[1], _dep_config.MAP_Y)))
    return points


def _quest_time_target(quest: dict[str, Any] | None) -> tuple[int, int] | None:
    if not isinstance(quest, dict) or not quest.get("active"):
        return None
    target = quest.get("target")
    if not isinstance(target, list | tuple) or len(target) < 2:
        return None
    return (
        _clamp_grid_coord(target[0], _dep_config.MAP_X),
        _clamp_grid_coord(target[1], _dep_config.MAP_Y),
    )


def _active_quest_target(quest: dict[str, Any] | None) -> tuple[int, int] | None:
    points = _quest_route_points(quest)
    if not points:
        return None
    try:
        route_index = int(quest.get("route_index", 0) or 0) if isinstance(quest, dict) else 0
    except (TypeError, ValueError):
        route_index = 0
    route_index = max(0, min(len(points) - 1, route_index))
    return points[route_index]


def _questers_at_target(
    players: dict[str, Any],
    quest: dict[str, Any] | None,
    *,
    room_jid: str | None = None,
) -> bool:
    target = _active_quest_target(quest)
    if target is None or not isinstance(quest, dict):
        return False
    questers = [str(jid) for jid in quest.get("questers", [])]
    if not questers:
        return False
    for jid in questers:
        player = players.get(jid)
        if not isinstance(player, dict):
            return False
        if room_jid is not None and not _dep_state._is_player_online(room_jid, jid, player):
            return False
        x = _clamp_grid_coord(player.get("x", 0), _dep_config.MAP_X)
        y = _clamp_grid_coord(player.get("y", 0), _dep_config.MAP_Y)
        if (x, y) != target:
            return False
    return True


def _step_toward(current: int, target: int, step_size: int) -> int:
    if current < target:
        return min(target, current + step_size)
    if current > target:
        return max(target, current - step_size)
    return current


def _move_random_grid_step(player: dict[str, Any], step_size: int) -> None:
    player["x"] = _clamp_grid_coord(
        int(player.get("x", 0) or 0) + random.choice((-step_size, 0, step_size)),
        _dep_config.MAP_X,
    )
    player["y"] = _clamp_grid_coord(
        int(player.get("y", 0) or 0) + random.choice((-step_size, 0, step_size)),
        _dep_config.MAP_Y,
    )


def _move_toward_quest_target(player: dict[str, Any], target: tuple[int, int], step_size: int) -> None:
    current_x = _clamp_grid_coord(player.get("x", 0), _dep_config.MAP_X)
    current_y = _clamp_grid_coord(player.get("y", 0), _dep_config.MAP_Y)
    player["x"] = _step_toward(current_x, target[0], step_size)
    player["y"] = _step_toward(current_y, target[1], step_size)


def _move_player(
    player: dict[str, Any],
    seconds: int = 1,
    *,
    quest: dict[str, Any] | None = None,
    jid: str | None = None,
) -> None:
    """Move one online player using original-style grid walking.

    Classic IdleRPG moves each player once per second on a 500x500 grid, with
    equal chances to step left/right/neither and up/down/neither.  Since this
    bot ticks less frequently, one tick simulates the elapsed seconds.

    Active grid questers move toward the current quest point instead.  That
    directed movement is intentionally slower than random walking, mirroring the
    original game's grid quest behaviour.
    """
    step_size = max(0, int(_dep_config.MAP_STEP_PER_SECOND or 0))
    if step_size <= 0:
        return
    try:
        elapsed = int(seconds or 0)
    except (TypeError, ValueError):
        elapsed = 0
    elapsed = max(0, min(24 * 3600, elapsed))
    if elapsed <= 0:
        return

    target = _active_quest_target(quest)
    questers = {str(value) for value in quest.get("questers", [])} if isinstance(quest, dict) else set()
    if target is not None and jid is not None and str(jid) in questers:
        directed_steps = elapsed // max(1, int(_dep_config.QUEST_GRID_STEP_SECONDS or 1))
        for _ in range(directed_steps):
            _move_toward_quest_target(player, target, step_size)
            if (
                _clamp_grid_coord(player.get("x", 0), _dep_config.MAP_X),
                _clamp_grid_coord(player.get("y", 0), _dep_config.MAP_Y),
            ) == target:
                break
        return

    for _ in range(elapsed):
        _move_random_grid_step(player, step_size)


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
    map_width = max(1, int(_dep_config.MAP_X) or 1)
    map_height = max(1, int(_dep_config.MAP_Y) or 1)
    grid = [["." for _ in range(width)] for _ in range(height)]
    legend: list[str] = []

    route_points = _quest_route_points(quest)
    for x, y in route_points:
        col = max(0, min(width - 1, int((x / map_width) * (width - 1))))
        row = max(0, min(height - 1, int((y / map_height) * (height - 1))))
        grid[row][col] = "Q"

    time_target = _quest_time_target(quest) if not route_points else None
    if time_target is not None:
        col = max(0, min(width - 1, int((time_target[0] / map_width) * (width - 1))))
        row = max(0, min(height - 1, int((time_target[1] / map_height) * (height - 1))))
        grid[row][col] = "T"

    for index, (jid, player) in enumerate(players[:35]):
        marker = _map_marker(index)
        x = max(0, min(map_width, int(player.get("x", 0) or 0)))
        y = max(0, min(map_height, int(player.get("y", 0) or 0)))
        col = max(0, min(width - 1, int((x / map_width) * (width - 1))))
        row = max(0, min(height - 1, int((y / map_height) * (height - 1))))
        grid[row][col] = marker if grid[row][col] == "." else "*"
        status = "online" if _dep_state._is_player_online(room_jid, jid, player) else "offline"
        legend.append(
            f"{marker} {_dep_formatting._display_player(player)} [{x},{y}] lv.{player.get('level', 0)} {status}"
        )

    lines = [
        f"🗺️ IdleRPG map for {room_jid}: "
        f"{_dep_config.MAP_X}x{_dep_config.MAP_Y}"
    ]
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
    if route_points:
        lines.append("Q = active grid-quest route point")
    elif time_target is not None:
        lines.append("T = time-quest map objective")
    return lines

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import state as _dep_state  # noqa: E402
