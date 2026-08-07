"""Normalized SQLite persistence for IdleRPG state.

The game keeps a mutable in-memory representation for fast command and tick
handling.  This store persists that representation in separate room, player,
season and event tables so a growing season history no longer expands one
large ``users_runtime`` JSON blob on every write.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any, cast

from utils.performance import observe

log = logging.getLogger(__name__)

_EVENT_ID_KEY = "_storage_id"
_EVENT_SEASON_KEY = "_season_started_at"
_EVENT_ROWID_KEY = "_storage_rowid"
_ROOM_SEPARATE_KEYS = {
    "players",
    "events",
    "season_events",
    "_pending_events",
    "season",
    "hall_of_fame",
}


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_load(value: object, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return int(default)


def _event_signature(event: Mapping[str, Any]) -> str:
    public = {
        str(key): value
        for key, value in event.items()
        if str(key) not in {_EVENT_ID_KEY, _EVENT_SEASON_KEY, _EVENT_ROWID_KEY}
    }
    return _digest(_json_dump(public))


def _event_id(event: dict[str, Any]) -> str:
    value = str(event.get(_EVENT_ID_KEY) or "").strip()
    if not value:
        value = uuid.uuid4().hex
        event[_EVENT_ID_KEY] = value
    return value


def _season_row_id(season: Mapping[str, Any], *, fallback: str) -> str:
    value = str(season.get("id") or "").strip()
    if value:
        return value
    started_at = _integer(season.get("started_at"))
    return f"{fallback}-{started_at}"


class IdleRPGStateStore:
    """SQLite-backed normalized IdleRPG state repository."""

    def __init__(self, db):
        self.db = db
        self._lock = asyncio.Lock()
        self._cache_ready = False
        self._room_hashes: dict[str, str] = {}
        self._player_hashes: dict[tuple[str, str], str] = {}
        self._season_hashes: dict[tuple[str, str], str] = {}
        self._recent_event_ids: dict[str, set[str]] = {}

    async def init(self, *, commit: bool = True) -> None:
        """Create normalized state tables and lookup indexes."""
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idlerpg_rooms (
                room_jid TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idlerpg_players (
                room_jid TEXT NOT NULL,
                jid TEXT NOT NULL,
                data_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (room_jid, jid),
                FOREIGN KEY (room_jid)
                    REFERENCES idlerpg_rooms(room_jid)
                    ON DELETE CASCADE
            )
            """
        )
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idlerpg_seasons (
                room_jid TEXT NOT NULL,
                season_id TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                started_at INTEGER NOT NULL DEFAULT 0,
                data_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (room_jid, season_id),
                FOREIGN KEY (room_jid)
                    REFERENCES idlerpg_rooms(room_jid)
                    ON DELETE CASCADE
            )
            """
        )
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idlerpg_events (
                room_jid TEXT NOT NULL,
                event_id TEXT NOT NULL,
                ts INTEGER NOT NULL,
                season_started_at INTEGER NOT NULL DEFAULT 0,
                in_recent INTEGER NOT NULL DEFAULT 0,
                data_json TEXT NOT NULL,
                PRIMARY KEY (room_jid, event_id),
                FOREIGN KEY (room_jid)
                    REFERENCES idlerpg_rooms(room_jid)
                    ON DELETE CASCADE
            )
            """
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idlerpg_players_room "
            "ON idlerpg_players(room_jid)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idlerpg_seasons_room_active "
            "ON idlerpg_seasons(room_jid, active, position)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idlerpg_events_room_recent "
            "ON idlerpg_events(room_jid, in_recent, ts)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idlerpg_events_room_season "
            "ON idlerpg_events(room_jid, season_started_at, ts)"
        )
        if commit:
            await self.db.conn.commit()

    async def _load_state_locked(self) -> dict[str, Any]:
        room_rows = await self.db.fetch_all(
            "SELECT room_jid, state_json FROM idlerpg_rooms ORDER BY room_jid"
        )
        rooms: dict[str, dict[str, Any]] = {}
        room_hashes: dict[str, str] = {}
        for row in room_rows:
            room_jid = str(row["room_jid"])
            raw = str(row["state_json"])
            state = _json_load(raw, {})
            if not isinstance(state, dict):
                state = {}
            state["players"] = {}
            state["events"] = []
            state["hall_of_fame"] = []
            rooms[room_jid] = state
            room_hashes[room_jid] = _digest(raw)

        player_hashes: dict[tuple[str, str], str] = {}
        player_rows = await self.db.fetch_all(
            "SELECT room_jid, jid, data_json "
            "FROM idlerpg_players ORDER BY room_jid, jid"
        )
        for row in player_rows:
            room_jid = str(row["room_jid"])
            if room_jid not in rooms:
                continue
            jid = str(row["jid"])
            raw = str(row["data_json"])
            player = _json_load(raw, {})
            if isinstance(player, dict):
                rooms[room_jid]["players"][jid] = player
                player_hashes[(room_jid, jid)] = _digest(raw)

        season_hashes: dict[tuple[str, str], str] = {}
        season_rows = await self.db.fetch_all(
            "SELECT room_jid, season_id, active, position, data_json "
            "FROM idlerpg_seasons "
            "ORDER BY room_jid, active DESC, position ASC, started_at ASC"
        )
        for row in season_rows:
            room_jid = str(row["room_jid"])
            if room_jid not in rooms:
                continue
            season_id = str(row["season_id"])
            raw = str(row["data_json"])
            season = _json_load(raw, {})
            if not isinstance(season, dict):
                continue
            season_hashes[(room_jid, season_id)] = _digest(
                f"{int(bool(row['active']))}:{int(row['position'])}:{_digest(raw)}"
            )
            if bool(row["active"]):
                rooms[room_jid]["season"] = season
            else:
                rooms[room_jid]["hall_of_fame"].append(season)

        recent_ids: dict[str, set[str]] = defaultdict(set)
        event_rows = await self.db.fetch_all(
            "SELECT room_jid, event_id, season_started_at, data_json "
            "FROM idlerpg_events WHERE in_recent = 1 "
            "ORDER BY room_jid, ts ASC, event_id ASC"
        )
        for row in event_rows:
            room_jid = str(row["room_jid"])
            room = rooms.get(room_jid)
            if room is None:
                continue
            event_id = str(row["event_id"])
            event = _json_load(str(row["data_json"]), {})
            if not isinstance(event, dict):
                continue
            event[_EVENT_ID_KEY] = event_id
            event[_EVENT_SEASON_KEY] = _integer(row["season_started_at"])
            room["events"].append(dict(event))
            recent_ids[room_jid].add(event_id)

        self._room_hashes = room_hashes
        self._player_hashes = player_hashes
        self._season_hashes = season_hashes
        self._recent_event_ids = {
            room: set(ids) for room, ids in recent_ids.items()
        }
        self._cache_ready = True
        return {"rooms": rooms}

    async def load_state(self) -> dict[str, Any]:
        """Load and reconstruct the complete in-memory game state."""
        async with self._lock:
            return await self._load_state_locked()

    async def _ensure_cache_locked(self) -> None:
        if not self._cache_ready:
            await self._load_state_locked()

    @staticmethod
    def _prepare_events(
        room: dict[str, Any],
        current_started_at: int,
    ) -> tuple[dict[str, dict[str, Any]], set[str]]:
        recent = room.get("events")
        season = room.get("season_events")
        pending = room.get("_pending_events")
        if not isinstance(recent, list):
            recent = []
            room["events"] = recent
        if not isinstance(season, list):
            season = []
        if not isinstance(pending, list):
            pending = []

        signature_ids: dict[str, deque[str]] = defaultdict(deque)
        prepared: dict[str, dict[str, Any]] = {}
        recent_ids: set[str] = set()

        for raw in recent:
            if not isinstance(raw, dict):
                continue
            event_id = _event_id(raw)
            if _EVENT_SEASON_KEY not in raw:
                ts = _integer(raw.get("ts"))
                raw[_EVENT_SEASON_KEY] = (
                    current_started_at
                    if current_started_at > 0 and ts >= current_started_at
                    else 0
                )
            prepared[event_id] = raw
            recent_ids.add(event_id)
            signature_ids[_event_signature(raw)].append(event_id)

        for raw in [*season, *pending]:
            if not isinstance(raw, dict):
                continue
            event_id = str(raw.get(_EVENT_ID_KEY) or "").strip()
            if not event_id:
                signature = _event_signature(raw)
                if signature_ids[signature]:
                    event_id = signature_ids[signature].popleft()
                    raw[_EVENT_ID_KEY] = event_id
                else:
                    event_id = _event_id(raw)
            if _EVENT_SEASON_KEY not in raw:
                raw[_EVENT_SEASON_KEY] = current_started_at
            prepared[event_id] = raw

        return prepared, recent_ids

    async def season_event_revision(
        self,
        room_jid: str,
        season_started_at: int,
    ) -> tuple[int, int]:
        """Return ``(event_count, max_rowid)`` for an append-only season stream."""
        row = await self.db.fetch_one(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(MAX(rowid), 0) AS max_rowid
              FROM idlerpg_events
             WHERE room_jid = ? AND season_started_at = ?
            """,
            (str(room_jid), max(0, int(season_started_at))),
        )
        if row is None:
            return (0, 0)
        return (
            max(0, int(row["count"] or 0)),
            max(0, int(row["max_rowid"] or 0)),
        )

    async def load_season_events(
        self,
        room_jid: str,
        season_started_at: int,
        *,
        after_rowid: int = 0,
    ) -> list[dict[str, Any]]:
        """Load full or incremental season events in chronological order.

        ``rowid`` is private storage metadata.  It never appears in public event
        JSON but gives the exporter an efficient append cursor without loading
        the complete active season after every new event.
        """
        async with self._lock:
            rows = await self.db.fetch_all(
                "SELECT rowid AS storage_rowid, event_id, season_started_at, data_json "
                "FROM idlerpg_events "
                "WHERE room_jid = ? AND season_started_at = ? AND rowid > ? "
                "ORDER BY ts ASC, rowid ASC",
                (
                    str(room_jid),
                    max(0, int(season_started_at)),
                    max(0, int(after_rowid)),
                ),
            )
        result: list[dict[str, Any]] = []
        for row in rows:
            event = _json_load(str(row["data_json"]), {})
            if not isinstance(event, dict):
                continue
            event[_EVENT_ID_KEY] = str(row["event_id"])
            event[_EVENT_SEASON_KEY] = _integer(row["season_started_at"])
            event[_EVENT_ROWID_KEY] = _integer(row["storage_rowid"])
            result.append(event)
        return result

    async def save_state(
        self,
        data: Mapping[str, Any],
        *,
        room_jids: set[str] | None = None,
    ) -> None:
        """Persist state transactionally, optionally limited to selected rooms."""
        started_perf = time.perf_counter()
        async with self._lock:
            await self._ensure_cache_locked()
            rooms_value = data.get("rooms", {}) if isinstance(data, Mapping) else {}
            rooms = rooms_value if isinstance(rooms_value, Mapping) else {}
            current_room_jids = {
                str(room_jid)
                for room_jid, room in rooms.items()
                if isinstance(room, dict)
            }
            requested_room_jids = (
                None
                if room_jids is None
                else {str(room_jid) for room_jid in room_jids}
            )
            target_room_jids = (
                current_room_jids
                if requested_room_jids is None
                else current_room_jids & requested_room_jids
            )

            new_room_hashes = dict(self._room_hashes)
            new_player_hashes = dict(self._player_hashes)
            new_season_hashes = dict(self._season_hashes)
            new_recent_ids = {
                room: set(ids) for room, ids in self._recent_event_ids.items()
            }

            async with self.db.transaction(label="idlerpg_save_state") as conn:
                stale_rooms = (
                    set(self._room_hashes) - current_room_jids
                    if requested_room_jids is None
                    else (set(self._room_hashes) & requested_room_jids)
                    - current_room_jids
                )
                for room_jid in sorted(stale_rooms):
                    await conn.execute(
                        "DELETE FROM idlerpg_rooms WHERE room_jid = ?",
                        (room_jid,),
                    )
                    new_room_hashes.pop(room_jid, None)
                    new_recent_ids.pop(room_jid, None)
                    new_player_hashes = {
                        key: value
                        for key, value in new_player_hashes.items()
                        if key[0] != room_jid
                    }
                    new_season_hashes = {
                        key: value
                        for key, value in new_season_hashes.items()
                        if key[0] != room_jid
                    }

                for raw_room_jid, raw_room in sorted(
                    rooms.items(), key=lambda item: str(item[0])
                ):
                    room_jid = str(raw_room_jid)
                    if not isinstance(raw_room, dict) or room_jid not in target_room_jids:
                        continue
                    updated_at = _integer(raw_room.get("last_tick"))
                    room_state = {
                        str(key): value
                        for key, value in raw_room.items()
                        if str(key) not in _ROOM_SEPARATE_KEYS
                    }
                    room_payload = _json_dump(room_state)
                    room_hash = _digest(room_payload)
                    if self._room_hashes.get(room_jid) != room_hash:
                        await conn.execute(
                            """
                            INSERT INTO idlerpg_rooms (
                                room_jid, state_json, updated_at
                            ) VALUES (?, ?, ?)
                            ON CONFLICT(room_jid) DO UPDATE SET
                                state_json = excluded.state_json,
                                updated_at = excluded.updated_at
                            """,
                            (room_jid, room_payload, updated_at),
                        )
                    new_room_hashes[room_jid] = room_hash

                    players = raw_room.get("players")
                    players = players if isinstance(players, Mapping) else {}
                    player_keys = {
                        (room_jid, str(jid))
                        for jid, player in players.items()
                        if isinstance(player, dict)
                    }
                    old_player_keys = {
                        key for key in self._player_hashes if key[0] == room_jid
                    }
                    for key in sorted(old_player_keys - player_keys):
                        await conn.execute(
                            "DELETE FROM idlerpg_players "
                            "WHERE room_jid = ? AND jid = ?",
                            key,
                        )
                        new_player_hashes.pop(key, None)
                    for raw_jid, player in sorted(
                        players.items(), key=lambda item: str(item[0])
                    ):
                        if not isinstance(player, dict):
                            continue
                        jid = str(raw_jid)
                        payload = _json_dump(player)
                        payload_hash = _digest(payload)
                        key = (room_jid, jid)
                        if self._player_hashes.get(key) != payload_hash:
                            await conn.execute(
                                """
                                INSERT INTO idlerpg_players (
                                    room_jid, jid, data_json, updated_at
                                ) VALUES (?, ?, ?, ?)
                                ON CONFLICT(room_jid, jid) DO UPDATE SET
                                    data_json = excluded.data_json,
                                    updated_at = excluded.updated_at
                                """,
                                (room_jid, jid, payload, updated_at),
                            )
                        new_player_hashes[key] = payload_hash

                    current_season = raw_room.get("season")
                    current_season = (
                        current_season if isinstance(current_season, Mapping) else {}
                    )
                    current_started_at = _integer(current_season.get("started_at"))
                    seasons: list[tuple[str, bool, int, dict[str, Any]]] = []
                    current_dict = dict(current_season)
                    current_id = _season_row_id(
                        current_dict,
                        fallback="active",
                    )
                    seasons.append((current_id, True, 0, current_dict))
                    hall = raw_room.get("hall_of_fame")
                    hall = hall if isinstance(hall, list) else []
                    for position, raw_season in enumerate(hall):
                        if not isinstance(raw_season, Mapping):
                            continue
                        season_dict = dict(raw_season)
                        season_id = _season_row_id(
                            season_dict,
                            fallback=f"hof-{position}",
                        )
                        seasons.append((season_id, False, position, season_dict))

                    season_keys = {(room_jid, value[0]) for value in seasons}
                    old_season_keys = {
                        key for key in self._season_hashes if key[0] == room_jid
                    }
                    for key in sorted(old_season_keys - season_keys):
                        await conn.execute(
                            "DELETE FROM idlerpg_seasons "
                            "WHERE room_jid = ? AND season_id = ?",
                            key,
                        )
                        new_season_hashes.pop(key, None)
                    for season_id, active, position, season_dict in seasons:
                        payload = _json_dump(season_dict)
                        payload_hash = _digest(payload)
                        key = (room_jid, season_id)
                        composite_hash = _digest(
                            f"{int(active)}:{position}:{payload_hash}"
                        )
                        if self._season_hashes.get(key) != composite_hash:
                            await conn.execute(
                                """
                                INSERT INTO idlerpg_seasons (
                                    room_jid, season_id, active, position,
                                    started_at, data_json, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(room_jid, season_id) DO UPDATE SET
                                    active = excluded.active,
                                    position = excluded.position,
                                    started_at = excluded.started_at,
                                    data_json = excluded.data_json,
                                    updated_at = excluded.updated_at
                                """,
                                (
                                    room_jid,
                                    season_id,
                                    int(active),
                                    position,
                                    _integer(season_dict.get("started_at")),
                                    payload,
                                    updated_at,
                                ),
                            )
                        new_season_hashes[key] = composite_hash

                    prepared_events, recent_ids = self._prepare_events(
                        raw_room, current_started_at
                    )
                    old_recent_ids = self._recent_event_ids.get(room_jid, set())
                    for event_id, event in prepared_events.items():
                        public_event = {
                            str(key): value
                            for key, value in event.items()
                            if str(key) not in {_EVENT_ID_KEY, _EVENT_SEASON_KEY, _EVENT_ROWID_KEY}
                        }
                        await conn.execute(
                            """
                            INSERT OR IGNORE INTO idlerpg_events (
                                room_jid, event_id, ts, season_started_at,
                                in_recent, data_json
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                room_jid,
                                event_id,
                                _integer(event.get("ts")),
                                _integer(event.get(_EVENT_SEASON_KEY)),
                                int(event_id in recent_ids),
                                _json_dump(public_event),
                            ),
                        )
                    for event_id in sorted(old_recent_ids - recent_ids):
                        await conn.execute(
                            "UPDATE idlerpg_events SET in_recent = 0 "
                            "WHERE room_jid = ? AND event_id = ?",
                            (room_jid, event_id),
                        )
                    for event_id in sorted(recent_ids - old_recent_ids):
                        await conn.execute(
                            "UPDATE idlerpg_events SET in_recent = 1 "
                            "WHERE room_jid = ? AND event_id = ?",
                            (room_jid, event_id),
                        )
                    new_recent_ids[room_jid] = set(recent_ids)
                    raw_room.pop("_pending_events", None)

            self._room_hashes = new_room_hashes
            self._player_hashes = new_player_hashes
            self._season_hashes = new_season_hashes
            self._recent_event_ids = new_recent_ids
            self._cache_ready = True
        observe("idlerpg_save", time.perf_counter() - started_perf)

    async def prune_events(self, *, retention_days: int) -> int:
        """Prune old completed-season events while preserving live history.

        Active-season rows are never removed, even when an endless/manual
        season outlives the retention window.  Rows still referenced by the
        bounded recent-event cache are preserved as well.
        """
        days = max(0, int(retention_days))
        if days <= 0:
            return 0
        cutoff = int(time.time()) - days * 86400
        async with self._lock:
            async with self.db.transaction(label="idlerpg_event_retention") as conn:
                cursor = await conn.execute(
                    """
                    DELETE FROM idlerpg_events
                     WHERE ts < ?
                       AND in_recent = 0
                       AND NOT EXISTS (
                           SELECT 1
                             FROM idlerpg_seasons AS seasons
                            WHERE seasons.room_jid = idlerpg_events.room_jid
                              AND seasons.active = 1
                              AND seasons.started_at = idlerpg_events.season_started_at
                       )
                    """,
                    (cutoff,),
                )
                removed = max(0, int(cursor.rowcount or 0))
            if removed:
                # Event IDs are append-only and the recent cache is retained,
                # so no in-memory hash rebuild is required after pruning.
                log.info("[IDLERPG] Pruned %d retained event row(s)", removed)
            return removed

    async def clear(self) -> None:
        """Delete all normalized IdleRPG state."""
        async with self._lock:
            await self.db.write(
                "DELETE FROM idlerpg_rooms",
                label="idlerpg_clear",
            )
            self._room_hashes.clear()
            self._player_hashes.clear()
            self._season_hashes.clear()
            self._recent_event_ids.clear()
            self._cache_ready = True

    async def stats(self) -> dict[str, int]:
        """Return compact row counts for diagnostics."""
        result: dict[str, int] = {}
        for key, table in (
            ("rooms", "idlerpg_rooms"),
            ("players", "idlerpg_players"),
            ("seasons", "idlerpg_seasons"),
            ("events", "idlerpg_events"),
        ):
            row = await self.db.fetch_one(f"SELECT COUNT(*) AS count FROM {table}")
            result[key] = int(row["count"] if row else 0)
        return result
