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

        filtered = await audit.list(limit=0, actor="admin@example.org")
        assert len(filtered) == 1
        assert filtered[0]["event"] == "config_reloaded"
        assert filtered[0]["actor"] == "admin@example.org"
        assert filtered[0]["target"] == "config"
