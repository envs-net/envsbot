from __future__ import annotations

import json

import aiosqlite
import pytest

from database.audit import AuditLog


@pytest.mark.asyncio
async def test_audit_log_init_append_and_list_filters(tmp_path):
    db_path = tmp_path / "audit.sqlite"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        audit = AuditLog(conn)
        await audit.init()

        await audit.append(
            "config_reloaded",
            actor="admin@example.org",
            target="config",
            details={"b": 2, "a": 1},
        )
        await audit.append("backup_created", actor="owner@example.org")

        all_rows = await audit.list(limit=500)
        assert [row["event"] for row in all_rows] == ["backup_created", "config_reloaded"]
        assert all_rows[0]["details"] == "{}"
        assert json.loads(all_rows[1]["details"]) == {"a": 1, "b": 2}
        assert await audit.count() == 2

        second_page = await audit.list(limit=1, offset=1)
        assert [row["event"] for row in second_page] == ["config_reloaded"]

        filtered = await audit.list(limit=0, actor="admin@example.org")
        assert len(filtered) == 1
        assert await audit.count(actor="admin@example.org") == 1
        assert filtered[0]["event"] == "config_reloaded"
        assert filtered[0]["actor"] == "admin@example.org"
        assert filtered[0]["target"] == "config"


@pytest.mark.asyncio
async def test_audit_log_list_filters_by_target_and_event(tmp_path):
    import aiosqlite

    db_path = tmp_path / "audit.db"
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        audit = AuditLog(conn)
        await audit.init()
        await audit.append("room_added", actor="admin@example.org", target="room@example.org")
        await audit.append("plugin_loaded", actor="admin@example.org", target="rss")

        rows = await audit.list(target="room@example.org")
        assert len(rows) == 1
        assert rows[0]["event"] == "room_added"

        rows = await audit.list(event="plugin_loaded")
        assert len(rows) == 1
        assert rows[0]["target"] == "rss"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_audit_export_jsonl_and_prune(tmp_path):
    db_path = tmp_path / "audit-export.sqlite"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        audit = AuditLog(conn)
        await audit.init()
        await audit.append("old", actor="admin@example.org", details={"x": 1})
        await conn.execute(
            "UPDATE audit_log SET created_at = datetime('now', '-120 days') WHERE event = 'old'"
        )
        await conn.commit()
        await audit.append("new", actor="admin@example.org", details={"y": 2})

        payload = await audit.export_jsonl(limit=10)
        assert '"event": "old"' in payload
        assert '"event": "new"' in payload

        assert await audit.prune_older_than(90, dry_run=True) == 1
        assert await audit.prune_older_than(90) == 1
        rows = await audit.list(limit=10)
        assert [row["event"] for row in rows] == ["new"]
