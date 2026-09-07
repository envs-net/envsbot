"""Adapters for shared persistent release-state storage."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from envs_xmpp_core.release.state import ReleaseState, ReleaseStateSqlRepository


class EnvsBotReleaseStateSqlBackend:
    """Adapt envsbot's DatabaseManager to the shared release-state repository."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def available(self) -> bool:
        return self.db is not None and getattr(self.db, "conn", None) is not None

    async def execute(
        self,
        query: str,
        params: Sequence[Any] = (),
        *,
        label: str = "release_state",
    ) -> int:
        if not self.available():
            raise RuntimeError("release state database is unavailable")
        cursor = await self.db.write(query, params, label=label)
        rowcount = cursor.rowcount
        return rowcount if rowcount is not None and rowcount >= 0 else 0

    async def fetch_one(self, query: str, params: Sequence[Any] = ()):
        if not self.available():
            return None
        return await self.db.fetch_one(query, tuple(params))


def release_state_repository(bot: Any) -> ReleaseStateSqlRepository:
    """Return the shared release-state repository for one bot instance."""
    return ReleaseStateSqlRepository(EnvsBotReleaseStateSqlBackend(getattr(bot, "db", None)))


def read_legacy_version_state(path: str | Path) -> ReleaseState:
    """Read the pre-0.8.1 JSON release state for one-time migration."""
    state_path = Path(path)
    try:
        with state_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return ReleaseState()
    if not isinstance(payload, dict):
        raise ValueError("version state must be a JSON object")
    return ReleaseState.from_mapping(payload)
