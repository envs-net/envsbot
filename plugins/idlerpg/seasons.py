"""Split module for plugins/idlerpg.py: seasons."""

from __future__ import annotations
import time
from typing import Any


def _season_id(ts: int | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(int(ts or _dep_formatting._now())))


def _season_duration_seconds() -> int:
    return max(0, int(_dep_config.SEASON_DURATION_DAYS) * 86400)


def _season_age_days(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    season = room.get("season")
    if not isinstance(season, dict):
        return 0
    started_at = int(season.get("started_at", _dep_formatting._now()) or _dep_formatting._now())
    return max(0, int((_dep_formatting._now() - started_at) // 86400))


def _blank_season(now: int | None = None) -> dict[str, Any]:
    now = int(now or _dep_formatting._now())
    duration = _season_duration_seconds()
    return {
        "id": _season_id(now),
        "started_at": now,
        "ends_at": now + duration if duration else 0,
    }


def _season_snapshot(room_jid: str, room: dict[str, Any], ended_at: int | None = None) -> dict[str, Any]:
    ended_at = int(ended_at or _dep_formatting._now())
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(ended_at)
    ranked = _dep_state._ranked_players(room)[:_dep_config.SEASON_HOF_SIZE]
    return {
        "id": season.get("id") or _season_id(ended_at),
        "room": room_jid,
        "started_at": int(season.get("started_at", 0) or 0),
        "ended_at": ended_at,
        "champion": _dep_formatting._display_player(ranked[0][1]) if ranked else "",
        "top": [
            _dep_export._player_public_record(room_jid, jid, player, rank=rank)
            for rank, (jid, player) in enumerate(ranked, start=1)
        ],
    }


def _reset_player_for_new_season(player: dict[str, Any]) -> None:
    player["level"] = 0
    player["next"] = _dep_leveling._ttl_for_level(0)
    player["idled"] = 0
    player["items"] = {item: 0 for item in _dep_constants.ITEMS}
    player["unique_items"] = {}
    player["penalties"] = {}
    player["pending_logout_penalty"] = {}
    player["logged_out_at"] = 0
    player["stats"] = {}
    player["achievements"] = []
    player["title"] = ""


def _end_season(room_jid: str, room: dict[str, Any], *, reset_players: bool | None = None) -> dict[str, Any]:
    now = _dep_formatting._now()
    snapshot = _season_snapshot(room_jid, room, now)
    hof = room.setdefault("hall_of_fame", [])
    if not isinstance(hof, list):
        hof = []
        room["hall_of_fame"] = hof
    hof.append(snapshot)
    del hof[:-max(1, _dep_config.SEASON_HOF_SIZE * 5)]
    should_reset = reset_players if reset_players is not None else _dep_config.SEASON_RESET_ON_ROLLOVER
    if should_reset:
        for jid, player in room.get("players", {}).items():
            if isinstance(player, dict):
                _reset_player_for_new_season(_dep_state._normalize_player(str(jid), player))
    room["season"] = _blank_season(now)
    _dep_export._record_event(
        room,
        "season",
        f"Season {snapshot.get('id')} ended. Champion: {snapshot.get('champion') or 'no champion'}.",
        players=[str(snapshot.get("champion") or "")],
        data={"season_id": snapshot.get("id"), "champion": snapshot.get("champion") or ""},
    )
    return snapshot


def _maybe_rollover_season(room_jid: str, room: dict[str, Any], messages: list[str]) -> None:
    if not _dep_config.SEASON_ENABLED or _season_duration_seconds() <= 0:
        return
    season = room.get("season")
    if not isinstance(season, dict):
        room["season"] = _blank_season(_dep_formatting._now())
        return
    ends_at = int(season.get("ends_at", 0) or 0)
    if ends_at <= 0 or _dep_formatting._now() < ends_at:
        return
    snapshot = _end_season(room_jid, room)
    champion = snapshot.get("champion") or "no champion"
    messages.append(
        f"🏁 IdleRPG season {snapshot.get('id')} has ended. Champion: {champion}. "
        f"New season {room['season']['id']} has begun."
    )


def _season_end_summary(season: dict[str, Any]) -> str:
    ends_at = int(season.get("ends_at", 0) or 0)
    return _dep_formatting._duration(ends_at - _dep_formatting._now()) if ends_at else "manual"

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import export as _dep_export  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import state as _dep_state  # noqa: E402
