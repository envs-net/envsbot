from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.health import backup_age_seconds, collect_health_snapshot


def test_backup_age_prefers_manifest_timestamp_over_file_mtime(tmp_path):
    path = tmp_path / "old.zip"
    path.write_bytes(b"x")
    # A copied archive can have a fresh filesystem mtime while its manifest is old.
    now = datetime.now(timezone.utc)
    archive = SimpleNamespace(
        path=path,
        created_at=(now - timedelta(hours=5)).isoformat(),
    )

    age = backup_age_seconds(archive, now=now)

    assert age is not None
    assert 17999 <= age <= 18001


def _fake_backups_module(monkeypatch, *, created_at: str, valid: bool = True):
    module = ModuleType("utils.backups")
    path = Path("/tmp/health-backup.zip")
    latest = SimpleNamespace(
        path=path,
        name=path.name,
        created_at=created_at,
    )
    module.list_backups = MagicMock(return_value=[latest])
    module.verify_backup = MagicMock(return_value={"ok": valid})
    module.smoke_test_backup = MagicMock(return_value={"ok": valid})
    monkeypatch.setitem(sys.modules, "utils.backups", module)
    return module


@pytest.mark.asyncio
async def test_health_snapshot_uses_manifest_backup_age_and_message_cache_health(monkeypatch):
    now = datetime.now(timezone.utc)
    backups = _fake_backups_module(
        monkeypatch,
        created_at=(now - timedelta(hours=4)).isoformat(),
    )
    bot = SimpleNamespace(
        config={"admin_alert_backup_max_age_hours": 3},
        presence=SimpleNamespace(joined_rooms={"room@conf": {}}),
        db=SimpleNamespace(
            rooms=SimpleNamespace(
                list=AsyncMock(return_value=[{"room_jid": "room@conf", "autojoin": 1}])
            ),
            maintenance_state={},
        ),
        tasks=None,
        outbox=None,
        message_cache=SimpleNamespace(
            stats=lambda: {
                "messages": 8,
                "pending_writes": 1,
                "retry_backlog": 2,
                "dropped_persistence_entries": 3,
                "persistent": True,
                "degraded": True,
                "last_persistence_error": "disk busy",
            }
        ),
        watchdog=None,
        bot_plugins=SimpleNamespace(failed_plugins={}),
        alerts=None,
    )

    snapshot = await collect_health_snapshot(bot, verify_backup=True)

    backup = snapshot.check("backup")
    assert backup.status == "warning"
    assert backup.data["too_old"] is True
    assert 3 * 3600 < int(backup.data["age_seconds"]) < 5 * 3600
    assert backup.data["status"] == "verified"
    backups.verify_backup.assert_called_once()

    cache = snapshot.check("message_cache")
    assert cache.status == "warning"
    assert cache.error == "disk busy"
    assert snapshot.needs_attention is True
    assert "message_cache" in snapshot.problem_keys


@pytest.mark.asyncio
async def test_health_snapshot_isolates_one_failed_collector(monkeypatch):
    async def broken_rooms():
        raise RuntimeError("rooms boom")

    bot = SimpleNamespace(
        config={},
        presence=SimpleNamespace(joined_rooms={}),
        db=SimpleNamespace(
            rooms=SimpleNamespace(list=broken_rooms),
            maintenance_state={},
        ),
        tasks=None,
        outbox=None,
        message_cache=SimpleNamespace(stats=lambda: {"messages": 0, "degraded": False}),
        watchdog=None,
        bot_plugins=SimpleNamespace(failed_plugins={}),
        alerts=None,
    )
    _fake_backups_module(
        monkeypatch,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    snapshot = await collect_health_snapshot(bot)

    assert snapshot.check("rooms").status == "error"
    assert "rooms boom" in str(snapshot.check("rooms").error)
    assert snapshot.check("message_cache").status == "ok"
    assert snapshot.check("backup").status == "ok"
