"""Focused tests for envsbot's shared release-state database adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from utils.release_state import EnvsBotReleaseStateSqlBackend


class _FakeDB:
    def __init__(self, rowcount: int | None) -> None:
        self.conn = object()
        self.rowcount = rowcount
        self.calls: list[tuple[str, tuple[object, ...], str]] = []

    async def write(self, query, params, *, label):
        self.calls.append((query, tuple(params), label))
        return SimpleNamespace(rowcount=self.rowcount)


@pytest.mark.asyncio
async def test_release_state_backend_execute_returns_database_rowcount() -> None:
    db = _FakeDB(rowcount=3)
    backend = EnvsBotReleaseStateSqlBackend(db)

    result = await backend.execute(
        "UPDATE release_state SET version = ?",
        ("2.2.0",),
        label="release-test",
    )

    assert result == 3
    assert db.calls == [
        (
            "UPDATE release_state SET version = ?",
            ("2.2.0",),
            "release-test",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [None, -1, 0])
async def test_release_state_backend_execute_normalizes_non_positive_metadata(
    rowcount: int | None,
) -> None:
    db = _FakeDB(rowcount=rowcount)
    backend = EnvsBotReleaseStateSqlBackend(db)

    assert await backend.execute("DELETE FROM release_state") == 0


@pytest.mark.asyncio
async def test_release_state_backend_execute_rejects_unavailable_database() -> None:
    db = _FakeDB(rowcount=1)
    db.conn = None
    backend = EnvsBotReleaseStateSqlBackend(db)

    with pytest.raises(RuntimeError, match="release state database is unavailable"):
        await backend.execute("UPDATE release_state SET version = ?", ("2.2.0",))

    assert db.calls == []
