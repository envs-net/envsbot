"""Room persistence backed by the central :class:`DatabaseManager` API."""

from __future__ import annotations

import json
from typing import Any


class Rooms:
    """Manage joined-room metadata without touching the raw SQLite connection."""

    def __init__(self, db: Any):
        self.db = db

    async def init(self, *, commit: bool = True) -> None:
        # ``commit`` is retained for migration-call compatibility. ``write`` is
        # nested-savepoint safe, so calling it inside a migration does not
        # commit the migration's outer savepoint.
        del commit
        await self.db.write(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_jid TEXT PRIMARY KEY,
                nick TEXT,
                autojoin INTEGER DEFAULT 0,
                status TEXT DEFAULT '{}'
            )
            """,
            label="rooms_init",
        )

    async def add(self, room_jid: str, nick: str, autojoin: bool = False) -> None:
        await self.db.write(
            "INSERT OR REPLACE INTO rooms (room_jid, nick, autojoin, status) "
            "VALUES (?, ?, ?, ?)",
            (room_jid, nick, int(autojoin), json.dumps({})),
            label="rooms_add",
        )

    async def delete(self, room_jid: str) -> None:
        await self.db.write(
            "DELETE FROM rooms WHERE room_jid = ?",
            (room_jid,),
            label="rooms_delete",
        )

    async def update(self, room_jid: str, **fields: Any) -> None:
        allowed_fields = {"nick", "autojoin", "status"}
        safe_fields = {key: value for key, value in fields.items() if key in allowed_fields}
        if not safe_fields:
            return
        keys = ", ".join(f"{key}=?" for key in safe_fields)
        values = [*safe_fields.values(), room_jid]
        await self.db.write(
            f"UPDATE rooms SET {keys} WHERE room_jid=?",
            tuple(values),
            label="rooms_update",
        )

    async def list(self):
        return await self.db.fetch_all(
            "SELECT room_jid, nick, autojoin, status FROM rooms"
        )

    async def get(self, room_jid: str):
        return await self.db.fetch_one(
            "SELECT room_jid, nick, autojoin, status FROM rooms WHERE room_jid=?",
            (room_jid,),
        )

    @staticmethod
    def _get_nested(data: dict[str, Any], path: str):
        current: Any = data
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    @staticmethod
    def _set_nested(data: dict[str, Any], path: str, value: Any) -> None:
        keys = path.split(".")
        current = data
        for key in keys[:-1]:
            nested = current.get(key)
            if not isinstance(nested, dict):
                nested = {}
                current[key] = nested
            current = nested
        current[keys[-1]] = value

    async def status_get(self, room_jid: str, path: str | None = None):
        row = await self.get(room_jid)
        if not row:
            return None
        data = json.loads(row[3] or "{}")
        return data if path is None else self._get_nested(data, path)

    async def status_set(self, room_jid: str, path: str, value: Any) -> None:
        row = await self.get(room_jid)
        if not row:
            return
        data = json.loads(row[3] or "{}")
        self._set_nested(data, path, value)
        await self.db.write(
            "UPDATE rooms SET status=? WHERE room_jid=?",
            (json.dumps(data), room_jid),
            label="rooms_status_set",
        )

    async def status_delete(self, room_jid: str, path: str) -> None:
        row = await self.get(room_jid)
        if not row:
            return
        data = json.loads(row[3] or "{}")
        keys = path.split(".")
        current: Any = data
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return
            current = current[key]
        if not isinstance(current, dict):
            return
        current.pop(keys[-1], None)
        await self.db.write(
            "UPDATE rooms SET status=? WHERE room_jid=?",
            (json.dumps(data), room_jid),
            label="rooms_status_delete",
        )
