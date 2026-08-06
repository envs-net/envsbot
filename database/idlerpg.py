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
import uuid
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

_EVENT_ID_KEY = "_storage_id"
_EVENT_SEASON_KEY = "_season_started_at"
_ROOM_SEPARATE_KEYS = {
    "players",
    "events",
    "season_events",
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
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default)


def _event_signature(event: Mapping[str, Any]) -> str:
    public = {
        str(key): value
        for key, value in event.items()
        if str(key) not in {_EVENT_ID_KEY, _EVENT_SEASON_KEY}
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
        self._event_ids: dict[str, set[str]] = {}
        self._recent_event_ids: dict[str, set[str]] = {}

    async def init(self) -> None:
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

    async def _load_state_locked(self) -> dict[str, Any]:
        room_rows = await (
            await self.db.conn.execute(
                "SELECT room_jid, state_json FROM idlerpg_rooms ORDER BY room_jid"
            )
        ).fetchall()
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
            state["season_events"] = []
            state["hall_of_fame"] = []
            rooms[room_jid] = state
            room_hashes[room_jid] = _digest(raw)

        player_hashes: dict[tuple[str, str], str] = {}
        player_rows = await (
            await self.db.conn.execute(
                "SELECT room_jid, jid, data_json "
                "FROM idlerpg_players ORDER BY room_jid, jid"
            )
        ).fetchall()
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
        season_rows = await (
            await self.db.conn.execute(
                "SELECT room_jid, season_id, active, position, data_json "
                "FROM idlerpg_seasons "
                "ORDER BY room_jid, active DESC, position ASC, started_at ASC"
            )
        ).fetchall()
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

        event_ids: dict[str, set[str]] = defaultdict(set)
        recent_ids: dict[str, set[str]] = defaultdict(set)
        event_rows = await (
            await self.db.conn.execute(
                "SELECT room_jid, event_id, season_started_at, in_recent, data_json "
                "FROM idlerpg_events ORDER BY room_jid, ts ASC, event_id ASC"
            )
        ).fetchall()
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
            season_started_at = _integer(row["season_started_at"])
            event[_EVENT_SEASON_KEY] = season_started_at
            event_ids[room_jid].add(event_id)
            if bool(row["in_recent"]):
                room["events"].append(dict(event))
                recent_ids[room_jid].add(event_id)
            active_started_at = _integer(
                room.get("season", {}).get("started_at")
                if isinstance(room.get("season"), dict)
                else 0
            )
            if season_started_at == active_started_at:
                room["season_events"].append(dict(event))

        for room in rooms.values():
            season = room.get("season")
            started_at = _integer(season.get("started_at")) if isinstance(season, dict) else 0
            room["season_events_started_at"] = started_at

        self._room_hashes = room_hashes
        self._player_hashes = player_hashes
        self._season_hashes = season_hashes
        self._event_ids = {room: set(ids) for room, ids in event_ids.items()}
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
        if not isinstance(recent, list):
            recent = []
            room["events"] = recent
        if not isinstance(season, list):
            season = []
            room["season_events"] = season

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

        for raw in season:
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
            raw[_EVENT_SEASON_KEY] = current_started_at
            prepared[event_id] = raw

        return prepared, recent_ids

    async def save_state(self, data: Mapping[str, Any]) -> None:
        """Persist a state snapshot transactionally with incremental row writes."""
        async with self._lock, self.db.transaction_lock:
            await self._ensure_cache_locked()
            rooms_value = data.get("rooms", {}) if isinstance(data, Mapping) else {}
            rooms = rooms_value if isinstance(rooms_value, Mapping) else {}
            current_room_jids = {
                str(room_jid)
                for room_jid, room in rooms.items()
                if isinstance(room, dict)
            }

            new_room_hashes = dict(self._room_hashes)
            new_player_hashes = dict(self._player_hashes)
            new_season_hashes = dict(self._season_hashes)
            new_event_ids = {
                room: set(ids) for room, ids in self._event_ids.items()
            }
            new_recent_ids = {
                room: set(ids) for room, ids in self._recent_event_ids.items()
            }

            try:
                await self.db.conn.execute("BEGIN IMMEDIATE")
                stale_rooms = set(self._room_hashes) - current_room_jids
                for room_jid in sorted(stale_rooms):
                    await self.db.conn.execute(
                        "DELETE FROM idlerpg_rooms WHERE room_jid = ?",
                        (room_jid,),
                    )
                    new_room_hashes.pop(room_jid, None)
                    new_event_ids.pop(room_jid, None)
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
                    if not isinstance(raw_room, dict):
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
                        await self.db.conn.execute(
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
                        await self.db.conn.execute(
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
                            await self.db.conn.execute(
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
                        await self.db.conn.execute(
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
                            await self.db.conn.execute(
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
                        raw_room,
                        current_started_at,
                    )
                    old_ids = self._event_ids.get(room_jid, set())
                    for event_id in sorted(set(prepared_events) - old_ids):
                        event = prepared_events[event_id]
                        await self.db.conn.execute(
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
                                _json_dump(event),
                            ),
                        )

                    old_recent = self._recent_event_ids.get(room_jid, set())
                    for event_id in sorted(recent_ids - old_recent):
                        await self.db.conn.execute(
                            "UPDATE idlerpg_events SET in_recent = 1 "
                            "WHERE room_jid = ? AND event_id = ?",
                            (room_jid, event_id),
                        )
                    for event_id in sorted(old_recent - recent_ids):
                        await self.db.conn.execute(
                            "UPDATE idlerpg_events SET in_recent = 0 "
                            "WHERE room_jid = ? AND event_id = ?",
                            (room_jid, event_id),
                        )

                    keep_ids = set(prepared_events)
                    for event_id in sorted(old_ids - keep_ids):
                        await self.db.conn.execute(
                            "DELETE FROM idlerpg_events "
                            "WHERE room_jid = ? AND event_id = ?",
                            (room_jid, event_id),
                        )
                    new_event_ids[room_jid] = keep_ids
                    new_recent_ids[room_jid] = set(recent_ids)

                await self.db.conn.commit()
            except Exception:
                await self.db.conn.rollback()
                raise

            self._room_hashes = new_room_hashes
            self._player_hashes = new_player_hashes
            self._season_hashes = new_season_hashes
            self._event_ids = new_event_ids
            self._recent_event_ids = new_recent_ids
            self._cache_ready = True

    async def clear(self) -> None:
        """Delete all normalized IdleRPG state."""
        async with self._lock, self.db.transaction_lock:
            await self.db.conn.execute("DELETE FROM idlerpg_rooms")
            await self.db.conn.commit()
            self._room_hashes.clear()
            self._player_hashes.clear()
            self._season_hashes.clear()
            self._event_ids.clear()
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
            row = await (
                await self.db.conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
            ).fetchone()
            result[key] = int(row["count"] if row else 0)
        return result
