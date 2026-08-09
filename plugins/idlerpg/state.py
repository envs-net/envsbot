"""Split module for plugins/idlerpg.py: state."""

from __future__ import annotations

import asyncio
import copy
import inspect
import random
import time
from typing import Any

from bot.room_state import JOINED_ROOMS
from core_plugins import _core
from utils.command import Role
from utils.performance import observe


def _blank_room() -> dict[str, Any]:
    now = _dep_formatting._now()
    return {
        "players": {},
        "name_index": {},
        "quest": {"active": False, "next_at": now + _dep_config.QUEST_INTERVAL},
        "season": _dep_seasons._blank_season(now),
        "hall_of_fame": [],
        "events": [],
        "last_tick": now,
        "next_top_announce_at": now + _dep_config.ANNOUNCE_TOP_INTERVAL if _dep_config.ANNOUNCE_TOP_INTERVAL > 0 else 0,
        "next_topic_update_at": now + _dep_config.TOPIC_UPDATE_INTERVAL if _dep_config.TOPIC_UPDATE_INTERVAL > 0 else 0,
        "created_at": now,
    }


async def _legacy_store(bot):
    return await _dep_formatting.get_idlerpg_store(bot)


def _normalized_store(bot):
    db = getattr(bot, "db", None)
    store = getattr(db, "idlerpg", None)
    if callable(getattr(store, "load_state", None)) and callable(
        getattr(store, "save_state", None)
    ):
        return store
    return None


def _cached_data(bot) -> dict[str, Any] | None:
    value = getattr(bot, "_idlerpg_state_cache", None)
    return value if isinstance(value, dict) else None


def _strip_legacy_season_event_cache(data: dict[str, Any]) -> None:
    """Drop legacy full-season event lists from normalized in-memory state."""
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if not isinstance(rooms, dict):
        return
    for room in rooms.values():
        if not isinstance(room, dict):
            continue
        room.pop("season_events", None)
        room.pop("season_events_started_at", None)


async def _get_data(bot) -> dict[str, Any]:
    normalized = _normalized_store(bot)
    if normalized is None:
        store = await _legacy_store(bot)
        data = await store.get_global(_dep_constants.IDLERPG_DATA_KEY, default={})
        return data if isinstance(data, dict) else {}

    cached = _cached_data(bot)
    if cached is not None:
        return cached

    data = await normalized.load_state()
    if isinstance(data, dict):
        _strip_legacy_season_event_cache(data)
    rooms = data.get("rooms", {}) if isinstance(data, dict) else {}
    if not isinstance(rooms, dict) or not rooms:
        legacy = await _legacy_store(bot)
        legacy_data = await legacy.get_global(
            _dep_constants.IDLERPG_DATA_KEY,
            default={},
        )
        if isinstance(legacy_data, dict) and isinstance(
            legacy_data.get("rooms"), dict
        ) and legacy_data["rooms"]:
            data = legacy_data
            await normalized.save_state(data)
            _strip_legacy_season_event_cache(data)
            delete_global = getattr(legacy, "delete_global", None)
            if callable(delete_global):
                await delete_global(_dep_constants.IDLERPG_DATA_KEY)
                flush = getattr(getattr(bot, "db", None), "flush", None)
                if callable(flush):
                    result = flush()
                    if inspect.isawaitable(result):
                        _ = await result
        elif not isinstance(data, dict):
            data = {}

    bot._idlerpg_state_cache = data
    return data


_PUBLIC_EXPORT_SCHEDULE: dict[str, int] = {"next_at": 0}
_PUBLIC_EXPORT_RUNTIME: dict[str, Any] = {
    "running": False,
    "last_started_at": 0,
    "last_finished_at": 0,
    "last_duration_ms": 0,
    "successes": 0,
    "failures": 0,
    "consecutive_failures": 0,
    "last_error": "",
    "rooms": 0,
    "players": 0,
    "events": 0,
    "files": 0,
    "bytes": 0,
    "files_changed": 0,
    "files_skipped": 0,
    "files_deleted": 0,
}
_PUBLIC_EXPORT_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
_PUBLIC_EXPORT_SEASON_REVISIONS: dict[str, tuple[int, tuple[int, int]]] = {}


def _public_export_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _PUBLIC_EXPORT_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _PUBLIC_EXPORT_LOCKS[loop] = lock
    return lock


def _reset_public_export_schedule() -> None:
    """Reset automatic scheduling and export diagnostics for tests/reloads."""
    _PUBLIC_EXPORT_SCHEDULE["next_at"] = 0
    _PUBLIC_EXPORT_RUNTIME.update({
        "running": False,
        "last_started_at": 0,
        "last_finished_at": 0,
        "last_duration_ms": 0,
        "successes": 0,
        "failures": 0,
        "consecutive_failures": 0,
        "last_error": "",
        "rooms": 0,
        "players": 0,
        "events": 0,
        "files": 0,
        "bytes": 0,
        "files_changed": 0,
        "files_skipped": 0,
        "files_deleted": 0,
    })
    _PUBLIC_EXPORT_LOCKS.clear()
    _PUBLIC_EXPORT_SEASON_REVISIONS.clear()


def _public_export_runtime() -> dict[str, Any]:
    return dict(_PUBLIC_EXPORT_RUNTIME)


async def _set_data(
    bot,
    data: dict[str, Any],
    *,
    room_jid: str | None = None,
    force_export: bool = False,
) -> None:
    normalized = _normalized_store(bot)
    if normalized is not None:
        await normalized.save_state(
            data,
            room_jids={str(room_jid)} if room_jid else None,
        )
        _strip_legacy_season_event_cache(data)
        bot._idlerpg_state_cache = data
    else:
        store = await _legacy_store(bot)
        await store.set_global(_dep_constants.IDLERPG_DATA_KEY, data)
    await _refresh_public_export(bot, data, force=force_export)


_SeasonRevision = tuple[int, tuple[int, int]]
_SeasonEventsByRoom = dict[str, list[dict[str, Any]] | None]
_PublicExportInputs = tuple[
    dict[str, Any],
    dict[str, bool],
    _SeasonEventsByRoom | None,
    dict[str, int] | None,
    dict[str, bool] | None,
    dict[str, _SeasonRevision],
]


async def _prepare_public_export_season_events(
    bot,
    rooms: dict[str, Any],
    enabled_rooms: dict[str, bool],
    *,
    force: bool,
) -> tuple[
    _SeasonEventsByRoom | None,
    dict[str, int] | None,
    dict[str, bool] | None,
    dict[str, _SeasonRevision],
]:
    """Resolve full/incremental active-season history for one public export."""
    pending: dict[str, _SeasonRevision] = {}
    normalized = _normalized_store(bot)
    if not _dep_config.EXPORT_FULL_SEASON_EVENTS or normalized is None:
        return None, None, None, pending

    loader = getattr(normalized, "load_season_events", None)
    revision_getter = getattr(normalized, "season_event_revision", None)
    if not callable(loader) or not callable(revision_getter):
        return None, None, None, pending

    events_by_room: _SeasonEventsByRoom = {}
    counts_by_room: dict[str, int] = {}
    append_by_room: dict[str, bool] = {}
    for room_jid, enabled in enabled_rooms.items():
        if not enabled:
            continue
        room = rooms.get(room_jid)
        if not isinstance(room, dict):
            continue
        season = room.get("season")
        started_at = (
            int(season.get("started_at", 0) or 0)
            if isinstance(season, dict)
            else 0
        )
        revision = tuple(await revision_getter(str(room_jid), started_at))
        revision_key = (started_at, revision)
        key = str(room_jid)
        previous = _PUBLIC_EXPORT_SEASON_REVISIONS.get(key)
        pending[key] = revision_key
        counts_by_room[key] = int(revision[0])

        can_append = (
            not force
            and previous is not None
            and previous[0] == started_at
            and int(revision[0]) >= int(previous[1][0])
            and int(revision[1]) >= int(previous[1][1])
        )
        if previous == revision_key and not force:
            # No database read at all for an unchanged season stream.
            events_by_room[key] = None
            append_by_room[key] = False
        elif can_append and previous is not None:
            # Fetch only rows inserted after the last successfully exported
            # rowid. The chunk writer appends idempotently.
            events_by_room[key] = await loader(
                key,
                started_at,
                after_rowid=int(previous[1][1]),
            )
            append_by_room[key] = True
        else:
            # First export, forced export, season rollover or a non-monotonic
            # revision rebuilds from SQLite once.
            events_by_room[key] = await loader(key, started_at, after_rowid=0)
            append_by_room[key] = False

    return events_by_room, counts_by_room, append_by_room, pending


async def _run_public_export_worker(
    snapshot: dict[str, Any],
    enabled_rooms: dict[str, bool],
    season_events_by_room: _SeasonEventsByRoom | None,
    season_event_counts_by_room: dict[str, int] | None,
    season_events_append_by_room: dict[str, bool] | None,
) -> dict[str, Any]:
    """Run public JSON serialization/filesystem work outside the event loop."""
    try:
        if season_events_by_room is None:
            result = await asyncio.to_thread(
                _dep_export._export_public_state,
                snapshot,
                dict(enabled_rooms),
            )
        else:
            result = await asyncio.to_thread(
                _dep_export._export_public_state,
                snapshot,
                dict(enabled_rooms),
                season_events_by_room,
                season_event_counts_by_room,
                season_events_append_by_room,
            )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"ok": True}


def _record_public_export_result(
    result: dict[str, Any],
    *,
    elapsed: float,
    interval: int,
    enabled_rooms: dict[str, bool],
    pending_season_revisions: dict[str, _SeasonRevision],
) -> bool:
    """Update diagnostics/cursors/schedule after one worker result."""
    finished_at = _dep_formatting._now()
    duration_ms = max(0, int(elapsed * 1000))
    observe("idlerpg_export", elapsed)
    ok = bool(result.get("ok", True))
    _PUBLIC_EXPORT_RUNTIME.update({
        "running": False,
        "last_finished_at": finished_at,
        "last_duration_ms": duration_ms,
        "last_error": str(result.get("error") or "")[:300],
        "rooms": max(0, int(result.get("rooms", 0) or 0)),
        "players": max(0, int(result.get("players", 0) or 0)),
        "events": max(0, int(result.get("events", 0) or 0)),
        "files": max(0, int(result.get("files", 0) or 0)),
        "bytes": max(0, int(result.get("bytes", 0) or 0)),
        "files_changed": max(0, int(result.get("files_changed", 0) or 0)),
        "files_skipped": max(0, int(result.get("files_skipped", 0) or 0)),
        "files_deleted": max(0, int(result.get("files_deleted", 0) or 0)),
    })
    counter = "successes" if ok else "failures"
    _PUBLIC_EXPORT_RUNTIME[counter] = int(
        _PUBLIC_EXPORT_RUNTIME.get(counter, 0) or 0
    ) + 1
    if ok:
        _PUBLIC_EXPORT_RUNTIME["consecutive_failures"] = 0
        if pending_season_revisions:
            _PUBLIC_EXPORT_SEASON_REVISIONS.update(pending_season_revisions)
            for room_jid in tuple(_PUBLIC_EXPORT_SEASON_REVISIONS):
                if room_jid not in enabled_rooms or not enabled_rooms.get(room_jid):
                    _PUBLIC_EXPORT_SEASON_REVISIONS.pop(room_jid, None)
        elif not _dep_config.EXPORT_FULL_SEASON_EVENTS:
            _PUBLIC_EXPORT_SEASON_REVISIONS.clear()
        _PUBLIC_EXPORT_SCHEDULE["next_at"] = (
            finished_at + interval if interval > 0 else finished_at
        )
        return True

    _PUBLIC_EXPORT_RUNTIME["consecutive_failures"] = int(
        _PUBLIC_EXPORT_RUNTIME.get("consecutive_failures", 0) or 0
    ) + 1
    # A worker failure may have happened after atomically publishing only part
    # of a delta. Forget cursors so the next attempt performs a full chunk
    # reconciliation instead of assuming the partial export is complete.
    for room_jid in pending_season_revisions:
        _PUBLIC_EXPORT_SEASON_REVISIONS.pop(room_jid, None)
    _PUBLIC_EXPORT_SCHEDULE["next_at"] = 0
    _dep_config.log.warning(
        "[IDLERPG] Public export failed: %s",
        _PUBLIC_EXPORT_RUNTIME["last_error"] or "unknown error",
    )
    return False


async def _prepare_public_export_inputs(
    bot,
    data: dict[str, Any] | None,
    *,
    force: bool,
) -> _PublicExportInputs | None:
    """Build one stable state/event input set for the public export worker."""
    normalized = _normalized_store(bot)
    snapshot_loader = getattr(normalized, "load_export_snapshot", None)
    snapshot: dict[str, Any]
    season_events_by_room: _SeasonEventsByRoom | None
    season_event_counts_by_room: dict[str, int] | None
    season_events_append_by_room: dict[str, bool] | None
    pending_season_revisions: dict[str, _SeasonRevision]
    uses_db_snapshot: bool
    if callable(snapshot_loader):
        try:
            (
                snapshot,
                season_events_by_room,
                season_event_counts_by_room,
                season_events_append_by_room,
                pending_season_revisions,
            ) = await snapshot_loader(
                previous_revisions=dict(_PUBLIC_EXPORT_SEASON_REVISIONS),
                force=force,
                include_full_season_events=bool(
                    _dep_config.EXPORT_FULL_SEASON_EVENTS
                ),
            )
        except Exception:
            _dep_config.log.exception(
                "[IDLERPG] Could not build DB-consistent public export snapshot"
            )
            return None
        uses_db_snapshot = True
    else:
        if data is None:
            data = await _get_data(bot)
        # Copy before any later await so a legacy/fallback store still hands the
        # worker one stable in-memory generation.
        snapshot = copy.deepcopy(data)
        season_events_by_room = None
        season_event_counts_by_room = None
        season_events_append_by_room = None
        pending_season_revisions = {}
        uses_db_snapshot = False

    rooms_value = snapshot.get("rooms", {}) if isinstance(snapshot, dict) else {}
    rooms = rooms_value if isinstance(rooms_value, dict) else {}
    try:
        enabled_rooms = await _enabled_rooms(bot, rooms.keys())
    except Exception:
        _dep_config.log.debug(
            "[IDLERPG] Could not resolve enabled rooms for public export",
            exc_info=True,
        )
        return None

    if not uses_db_snapshot:
        (
            season_events_by_room,
            season_event_counts_by_room,
            season_events_append_by_room,
            pending_season_revisions,
        ) = await _prepare_public_export_season_events(
            bot,
            rooms,
            enabled_rooms,
            force=force,
        )
    return (
        snapshot,
        enabled_rooms,
        season_events_by_room,
        season_event_counts_by_room,
        season_events_append_by_room,
        pending_season_revisions,
    )


async def _refresh_public_export(
    bot,
    data: dict[str, Any] | None = None,
    *,
    force: bool = True,
) -> bool:
    """Refresh public JSON from a stable state snapshot off the XMPP event loop."""
    if not _dep_config.EXPORT_ENABLED:
        return False

    interval = max(0, int(_dep_config.EXPORT_INTERVAL_SECONDS))
    async with _public_export_lock():
        now = _dep_formatting._now()
        if not force and interval > 0 and now < _PUBLIC_EXPORT_SCHEDULE["next_at"]:
            return False

        prepared = await _prepare_public_export_inputs(bot, data, force=force)
        if prepared is None:
            return False
        (
            snapshot,
            enabled_rooms,
            season_events_by_room,
            season_event_counts_by_room,
            season_events_append_by_room,
            pending_season_revisions,
        ) = prepared

        started_at = _dep_formatting._now()
        started_perf = time.perf_counter()
        _PUBLIC_EXPORT_RUNTIME.update({
            "running": True,
            "last_started_at": started_at,
            "last_error": "",
        })
        result = await _run_public_export_worker(
            snapshot,
            enabled_rooms,
            season_events_by_room,
            season_event_counts_by_room,
            season_events_append_by_room,
        )
        return _record_public_export_result(
            result,
            elapsed=time.perf_counter() - started_perf,
            interval=interval,
            enabled_rooms=enabled_rooms,
            pending_season_revisions=pending_season_revisions,
        )


async def _flush_idlerpg_store(bot) -> None:
    """Best-effort flush for restart-sensitive IdleRPG checkpoints."""
    db = getattr(bot, "db", None)
    flush = getattr(db, "flush", None)
    if callable(flush):
        result = flush()
        if inspect.isawaitable(result):
            result = await result
        if result is not None:
            return
        return

    users = getattr(db, "users", None)
    flush_all = getattr(users, "flush_all", None)
    if callable(flush_all):
        result = flush_all()
        if inspect.isawaitable(result):
            result = await result
        if result is not None:
            return


async def _checkpoint_room_clock(bot, room_jid: str, *, flush: bool = False) -> int:
    """Persist a room clock boundary before starting/stopping a runtime task.

    Room tasks are intentionally in-memory.  When a task is recreated after a
    bot restart, plugin reload, or room toggle, the persisted ``last_tick`` may
    be old.  If we let the next tick consume that whole gap, currently online
    players would receive idle credit for time where the bot could not observe
    room presence.  Store a fresh boundary instead and return the skipped gap
    for diagnostics/tests.
    """
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    now = _dep_formatting._now()
    try:
        previous = int(room.get("last_tick", now) or now)
    except (TypeError, ValueError):
        previous = now
    room["last_tick"] = now
    room["last_task_checkpoint_at"] = now
    await _set_data(bot, data, room_jid=room_jid)
    if flush:
        await _flush_idlerpg_store(bot)
    return max(0, now - previous)


def _ensure_founder_achievements(room: dict[str, Any]) -> int:
    """Backfill the permanent Founder achievement for registered characters."""
    players = room.get("players", {})
    if not isinstance(players, dict):
        return 0

    awarded = 0
    for jid, player in players.items():
        if not isinstance(player, dict):
            continue
        normalized = _normalize_player(str(jid), player)
        if _dep_leveling._award(normalized, "founder"):
            awarded += 1
    return awarded


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
    _ensure_founder_achievements(room)
    room.setdefault("name_index", {})
    room.setdefault("quest", {"active": False, "next_at": _dep_formatting._now() + _dep_config.QUEST_INTERVAL})
    room.setdefault("season", _dep_seasons._blank_season(_dep_formatting._now()))
    room.setdefault("hall_of_fame", [])
    room.setdefault("events", [])
    _dep_export._prune_events(room)
    room.setdefault("last_tick", _dep_formatting._now())
    room.setdefault("next_top_announce_at", _dep_formatting._now() + _dep_config.ANNOUNCE_TOP_INTERVAL if _dep_config.ANNOUNCE_TOP_INTERVAL > 0 else 0)
    room.setdefault("next_topic_update_at", _dep_formatting._now() + _dep_config.TOPIC_UPDATE_INTERVAL if _dep_config.TOPIC_UPDATE_INTERVAL > 0 else 0)
    return room


def _player_coordinate(player: dict[str, Any], key: str, max_value: int) -> int:
    if key not in player:
        return random.randint(0, max_value)
    try:
        return int(player.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_player(jid: str, player: dict[str, Any]) -> dict[str, Any]:
    now = _dep_formatting._now()
    items = player.get("items")
    if not isinstance(items, dict):
        items = {}
    for item in _dep_constants.ITEMS:
        try:
            items[item] = int(items.get(item, 0) or 0)
        except (TypeError, ValueError):
            items[item] = 0

    unique_items = player.get("unique_items")
    if not isinstance(unique_items, dict):
        unique_items = {}
    unique_items = {str(k): str(v) for k, v in unique_items.items() if str(k) in _dep_constants.ITEMS and str(v).strip()}

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
        ttl = int(player.get("next", _dep_leveling._ttl_for_level(level)) or 0)
    except (TypeError, ValueError):
        ttl = _dep_leveling._ttl_for_level(level)

    achievements = player.get("achievements")
    if not isinstance(achievements, list):
        achievements = []
    achievements = sorted({str(value) for value in achievements if str(value) in _dep_constants.ACHIEVEMENTS})
    title = str(player.get("title") or "")
    if title not in achievements:
        title = ""

    player.update({
        "jid": str(player.get("jid") or jid),
        "name": _dep_formatting._safe_name(str(player.get("name") or jid.split("@", 1)[0])) or "player",
        "class": _dep_formatting._safe_class(str(player.get("class") or "idler")) or "idler",
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
        "x": _player_coordinate(player, "x", _dep_config.MAP_X),
        "y": _player_coordinate(player, "y", _dep_config.MAP_Y),
        "logged_out": bool(player.get("logged_out", False)),
    })
    if player["alignment"] not in {"g", "n", "e"}:
        player["alignment"] = "n"
    player["x"] %= max(1, _dep_config.MAP_X + 1)
    player["y"] %= max(1, _dep_config.MAP_Y + 1)
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
    title = _dep_formatting._display_title(player)
    title_part = f" [{title}]" if title else ""
    return (
        f"{_dep_formatting._display_player(player)}{title_part}, the level {player.get('level', 0)} "
        f"{player.get('class', 'idler')} ({_dep_formatting._alignment_name(player.get('alignment'))}); "
        f"Status: {online}; TTL: {_dep_formatting._duration(player.get('next', 0))}; "
        f"Playing: {_dep_formatting._played_for(player)}; Idled: {_dep_formatting._duration(player.get('idled', 0))}; "
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
        _dep_config.log.debug("[IDLERPG] Could not resolve sender role", exc_info=True)
        return False


async def _enabled_rooms(bot, room_jids=()) -> dict[str, bool]:
    return await _core._get_enabled_rooms(
        bot,
        _dep_constants.IDLERPG_ENABLED_KEY,
        _dep_constants.PLUGIN_NAME,
        room_jids,
    )

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import export as _dep_export  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import seasons as _dep_seasons  # noqa: E402
