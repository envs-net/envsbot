from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile
from types import SimpleNamespace

import pytest

import utils.backups as backups
import utils.config as config_mod
import utils.config.loader as config_loader
import utils.runtime_paths as runtime_paths


class FakeDB:
    def __init__(self, path):
        self.path = str(path)
        self.conn = None
        self.closed = False
        self.connected = False
        self.flushed = False

    async def flush(self):
        self.flushed = True

    async def close(self):
        self.closed = True

    async def connect(self):
        self.connected = True


class ReconnectOnceFailDB(FakeDB):
    def __init__(self, path):
        super().__init__(path)
        self.connect_attempts = 0

    async def connect(self):
        self.connect_attempts += 1
        if self.connect_attempts == 1:
            raise RuntimeError("reconnect failed")
        self.connected = True


def _write_runtime_files(root):
    db_path = root / "bot.db"
    db_path.write_bytes(b"sqlite-data")
    (root / "config.py").write_text('JID = "bot@example.org"\n', encoding="utf-8")
    (root / "vcard.py").write_text('FN = "EnvsBot"\n', encoding="utf-8")
    (root / "chat_slang.csv").write_text("brb,be right back\n", encoding="utf-8")
    return db_path


def _write_sqlite_value(path, value):
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE restore_test (value TEXT NOT NULL)")
        connection.execute("INSERT INTO restore_test VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _read_sqlite_value(path):
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT value FROM restore_test").fetchone()
        assert row is not None
        return str(row[0])
    finally:
        connection.close()


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    db_path = _write_runtime_files(tmp_path)
    backup_dir = tmp_path / "data" / "backups"
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backups, "BASE_DIR", tmp_path)
    monkeypatch.setattr(runtime_paths, "BASE_DIR", tmp_path)
    monkeypatch.delenv("ENVSBOT_CONFIG", raising=False)
    monkeypatch.setitem(backups.config, "db", str(db_path))
    monkeypatch.setitem(backups.config, "backup_dir", str(backup_dir))
    monkeypatch.setitem(backups.config, "backup_keep", 15)
    # Most legacy backup tests use a byte fixture rather than a real SQLite DB.
    # Dedicated tests below exercise the new restore smoke verification.
    monkeypatch.setitem(backups.config, "backup_smoke_test_on_create", False)
    return SimpleNamespace(root=tmp_path, db_path=db_path, backup_dir=backup_dir)


@pytest.mark.asyncio
async def test_create_backup_contains_runtime_files_and_manifest(backup_env):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))

    archive = await backups.create_backup(bot, reason="manual test")

    assert archive.parent == backup_env.backup_dir
    assert archive.name.startswith("envsbot-backup-")
    assert bot.db.flushed is True

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert {"bot.db", "config.py", "vcard.py", "chat_slang.csv", "manifest.json"} <= names
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["app"] == "envsbot"
    assert manifest["reason"] == "manual test"
    assert {item["name"] for item in manifest["files"]} >= {
        "bot.db",
        "config.py",
        "vcard.py",
        "chat_slang.csv",
    }


@pytest.mark.asyncio
async def test_create_backup_offloads_archive_work_and_pruning(backup_env, monkeypatch):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    calls: list[str] = []

    async def run_in_thread(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args, **kwargs)

    monkeypatch.setattr(backups.asyncio, "to_thread", run_in_thread)

    archive = await backups.create_backup(bot, reason="threaded")

    assert archive.exists()
    assert "_build_backup_archive" in calls
    assert "prune_old_backups" in calls
    assert "copy2" in calls


@pytest.mark.asyncio
async def test_restore_backup_restores_files_and_reconnects_database(backup_env):
    _write_sqlite_value(backup_env.db_path, "backup")
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="before change")

    _write_sqlite_value(backup_env.db_path, "current")
    (backup_env.root / "config.py").write_text("BROKEN = True\n", encoding="utf-8")
    (backup_env.root / "vcard.py").write_text("BROKEN = True\n", encoding="utf-8")
    (backup_env.root / "chat_slang.csv").write_text("changed\n", encoding="utf-8")

    result = await backups.restore_backup(bot, archive)

    assert bot.db.closed is True
    assert bot.db.connected is True
    assert _read_sqlite_value(backup_env.db_path) == "backup"
    assert (backup_env.root / "config.py").read_text(encoding="utf-8") == 'JID = "bot@example.org"\n'
    assert (backup_env.root / "vcard.py").read_text(encoding="utf-8") == "BROKEN = True\n"
    assert (backup_env.root / "chat_slang.csv").read_text(encoding="utf-8") == "changed\n"
    assert result["archive"] == archive.name
    assert result["restored"] == ["bot.db", "config.py"]
    assert result["manual_restore"] == ["vcard.py", "chat_slang.csv"]
    assert result["safety_backup"].endswith("restore-safety.zip")


def test_resolve_backup_rejects_path_traversal(backup_env):
    with pytest.raises(backups.BackupError):
        backups.resolve_backup("../secret.zip")


def test_backup_helpers_invalid_keep_and_path_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, "BASE_DIR", tmp_path)
    monkeypatch.setitem(backups.config, "backup_keep", "bad")
    assert backups.backup_keep() == 15
    monkeypatch.setitem(backups.config, "backup_dir", "relative/backups")
    assert backups.backup_dir() == tmp_path / "relative" / "backups"
    assert backups._safe_reason(" manual backup! with spaces ") == "manual-backup-with-spaces"
    assert backups._safe_reason("!@#") == "manual"


def test_list_resolve_prune_and_manifest_error_paths(backup_env):
    backup_env.backup_dir.mkdir(parents=True)
    empty = backup_env.backup_dir / "envsbot-backup-20260101-000000-bad.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("not-manifest.txt", "x")

    listed = backups.list_backups(directory=backup_env.backup_dir)
    assert len(listed) == 1
    assert listed[0].reason == "unreadable"
    assert listed[0].files == []

    with pytest.raises(backups.BackupError, match="no manifest"):
        backups.backup_details(empty)

    with pytest.raises(backups.BackupError, match="Missing"):
        backups.resolve_backup("")

    empty.unlink()
    with pytest.raises(backups.BackupError, match="No backups found"):
        backups.resolve_backup("last")


def test_backup_resolve_details_prune_and_safe_members(backup_env, monkeypatch):
    backup_env.backup_dir.mkdir(parents=True)
    archives = []
    for idx in range(3):
        path = backup_env.backup_dir / f"envsbot-backup-20260101-00000{idx}-manual.zip"
        manifest = {
            "app": "envsbot",
            "created_at": f"2026-01-01T00:00:0{idx}+00:00",
            "reason": f"manual-{idx}",
            "files": [{"name": "bot.db"}],
        }
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        archives.append(path)

    assert backups.resolve_backup("last").name == archives[-1].name
    assert backups.resolve_backup(archives[1].name).name == archives[1].name
    assert backups.resolve_backup(archives[0].stem).name == archives[0].name
    details = backups.backup_details(archives[2])
    assert details["manifest"]["reason"] == "manual-2"

    removed = backups.prune_old_backups(directory=backup_env.backup_dir, keep=1)
    assert {path.name for path in removed} == {archives[1].name, archives[0].name}

    unsafe = backup_env.backup_dir / "envsbot-backup-20260101-unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as zf:
        zf.writestr("../evil", "x")
    with zipfile.ZipFile(unsafe) as zf:
        with pytest.raises(backups.BackupError, match="Unsafe"):
            backups._safe_members(zf)


@pytest.mark.asyncio
async def test_backup_restore_reconnects_after_restore_error(backup_env, monkeypatch):
    _write_sqlite_value(backup_env.db_path, "backup")
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="restore failure")
    _write_sqlite_value(backup_env.db_path, "current")
    (backup_env.root / "config.py").write_text("CURRENT = True\n", encoding="utf-8")

    replace = backups._replace_from_stage
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("copy failed")
        replace(source, target)

    monkeypatch.setattr(backups, "_replace_from_stage", fail_second_replace)

    with pytest.raises(backups.BackupError, match="rolled back"):
        await backups.restore_backup(bot, archive)

    assert bot.db.closed is True
    assert bot.db.connected is True
    assert _read_sqlite_value(backup_env.db_path) == "current"
    assert (backup_env.root / "config.py").read_text(encoding="utf-8") == "CURRENT = True\n"


@pytest.mark.asyncio
async def test_restore_rejects_invalid_database_before_live_changes(backup_env):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="invalid target", verify=False)
    current_config = (backup_env.root / "config.py").read_text(encoding="utf-8")

    with pytest.raises(backups.BackupError, match="not safe to restore"):
        await backups.restore_backup(bot, archive)

    assert bot.db.closed is False
    assert bot.db.connected is False
    assert backup_env.db_path.read_bytes() == b"sqlite-data"
    assert (backup_env.root / "config.py").read_text(encoding="utf-8") == current_config
    assert len(list(backup_env.backup_dir.glob("*restore-safety.zip"))) == 0


@pytest.mark.asyncio
async def test_restore_rolls_back_when_database_reconnect_fails(backup_env):
    _write_sqlite_value(backup_env.db_path, "backup")
    bot = SimpleNamespace(db=ReconnectOnceFailDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="before reconnect failure")
    _write_sqlite_value(backup_env.db_path, "current")
    (backup_env.root / "config.py").write_text("CURRENT = True\n", encoding="utf-8")

    with pytest.raises(backups.BackupError, match="rolled back"):
        await backups.restore_backup(bot, archive)

    assert bot.db.connect_attempts == 2
    assert bot.db.connected is True
    assert _read_sqlite_value(backup_env.db_path) == "current"
    assert (backup_env.root / "config.py").read_text(encoding="utf-8") == "CURRENT = True\n"


def test_plan_backup_prune_supports_dry_run_and_age(backup_env):
    backup_env.backup_dir.mkdir(parents=True)
    old = backup_env.backup_dir / "envsbot-backup-20250101-000000-old.zip"
    new = backup_env.backup_dir / "envsbot-backup-20260101-000000-new.zip"
    for path, created_at in (
        (old, "2025-01-01T00:00:00+00:00"),
        (new, "2026-01-01T00:00:00+00:00"),
    ):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps({"app": "envsbot", "created_at": created_at, "files": []}),
            )

    planned = backups.plan_backup_prune(directory=backup_env.backup_dir, keep=1)
    assert [archive.name for archive in planned] == [old.name]
    dry_run = backups.prune_old_backups(
        directory=backup_env.backup_dir,
        keep=1,
        dry_run=True,
    )
    assert [path.name for path in dry_run] == [old.name]
    assert old.exists()

def test_parse_archive_created_at_handles_timezone_and_invalid_values():
    aware = backups._parse_archive_created_at("2026-01-02T03:04:05+02:00")
    assert aware is not None
    assert aware.tzinfo is not None
    assert aware.hour == 1

    naive = backups._parse_archive_created_at("2026-01-02T03:04:05")
    assert naive is not None
    assert naive.tzinfo is not None
    assert naive.hour == 3

    assert backups._parse_archive_created_at("not-a-date") is None


def test_verify_backup_and_restore_plan(backup_env):
    backup_env.backup_dir.mkdir(parents=True)
    archive = backup_env.backup_dir / "envsbot-backup-20260101-000000-manual.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("bot.db", b"sqlite-data")
        manifest = {
            "app": "envsbot",
            "created_at": "2026-01-01T00:00:00+00:00",
            "reason": "manual",
            "files": [
                {
                    "name": "bot.db",
                    "size": len(b"sqlite-data"),
                    "sha256": "8e40a0e8a5568b4c6ef4fb51f81a2ca2b7a8c4e4c4b733be3b8f2da4e6f8b19a",
                }
            ],
            "missing": [],
        }
        # Keep checksum matching the actual bytes generated at runtime.
        import hashlib
        manifest["files"][0]["sha256"] = hashlib.sha256(b"sqlite-data").hexdigest()
        zf.writestr("manifest.json", json.dumps(manifest))

    result = backups.verify_backup(archive)
    assert result["ok"] is True
    assert result["files"] == ["bot.db"]

    plan = backups.restore_plan(archive)
    assert plan["entries"] == ["bot.db"]
    assert plan["targets"]["bot.db"] == str(backup_env.db_path)


def test_restore_plan_never_writes_legacy_json_into_python_config(backup_env):
    backup_env.backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_env.backup_dir / "envsbot-backup-20260101-legacy-json.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("bot.db", b"sqlite-data")
        zf.writestr("config.json", b'{"jid": "bot@example.org"}')
        zf.writestr(
            "manifest.json",
            json.dumps({"app": "envsbot", "created_at": "2026-01-01T00:00:00Z", "files": []}),
        )

    plan = backups.restore_plan(archive)

    assert plan["entries"] == ["bot.db"]
    assert plan["manual_restore"] == ["config.json"]


@pytest.mark.asyncio
async def test_backup_permissions_names_and_no_partial_archive(backup_env, monkeypatch):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    first = await backups.create_backup(bot, reason="same")
    second = await backups.create_backup(bot, reason="same")

    assert first != second
    assert first.stat().st_mode & 0o777 == 0o600
    assert second.stat().st_mode & 0o777 == 0o600
    assert backup_env.backup_dir.stat().st_mode & 0o777 == 0o700
    assert not list(backup_env.backup_dir.glob("*.tmp"))


@pytest.mark.asyncio
async def test_create_backup_removes_temporary_archive_after_write_failure(
    backup_env, monkeypatch
):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("archive write failed")

    monkeypatch.setattr(backups, "_write_file", fail_write)
    with pytest.raises(RuntimeError, match="archive write failed"):
        await backups.create_backup(bot, reason="failure", prune=False)

    assert not list(backup_env.backup_dir.glob("*.tmp"))
    assert not list(backup_env.backup_dir.glob("*.zip"))

@pytest.mark.asyncio
async def test_create_backup_returns_verified_archive_when_prune_fails(
    backup_env, monkeypatch
):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))

    def fail_prune(**_kwargs):
        raise OSError("prune failed")

    monkeypatch.setattr(backups, "prune_old_backups", fail_prune)
    archive = await backups.create_backup(bot, reason="manual", prune=True)

    assert archive.exists()
    with zipfile.ZipFile(archive) as handle:
        assert handle.testzip() is None
        assert backups.MANIFEST_NAME in handle.namelist()


def test_parse_archive_created_at_normalizes_z_and_cross_day_offsets():
    zulu = backups._parse_archive_created_at(" 2026-01-02T03:04:05Z ")
    assert zulu is not None
    assert zulu.isoformat() == "2026-01-02T03:04:05+00:00"

    crossing = backups._parse_archive_created_at("2026-01-02T00:30:00+02:00")
    assert crossing is not None
    assert crossing.isoformat() == "2026-01-01T22:30:00+00:00"

    naive = backups._parse_archive_created_at("2026-01-02T03:04:05")
    assert naive is not None
    assert naive.isoformat() == "2026-01-02T03:04:05+00:00"

    assert backups._parse_archive_created_at(None) is None
    assert backups._parse_archive_created_at("") is None
    assert backups._parse_archive_created_at("   ") is None
    assert backups._parse_archive_created_at("2026-01-02ZT03:04:05") is None

@pytest.mark.asyncio
async def test_create_backup_smoke_verifies_real_sqlite_snapshot(backup_env, monkeypatch):
    backup_env.db_path.unlink()
    connection = sqlite3.connect(backup_env.db_path)
    try:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('ok')")
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setitem(backups.config, "backup_smoke_test_on_create", True)
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))

    archive = await backups.create_backup(bot, reason="verified", prune=False)

    smoke = backups.smoke_test_backup(archive)
    assert smoke["ok"] is True
    assert smoke["database_integrity"] == ["ok"]


@pytest.mark.asyncio
async def test_create_backup_rejects_invalid_sqlite_when_smoke_required(
    backup_env, monkeypatch
):
    monkeypatch.setitem(backups.config, "backup_smoke_test_on_create", True)
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))

    with pytest.raises(backups.BackupError, match="restore smoke test"):
        await backups.create_backup(bot, reason="invalid", prune=False)

    assert not list(backup_env.backup_dir.glob("*.zip"))


def test_migration_snapshot_retention_supports_count_age_and_dry_run(
    backup_env, monkeypatch
):
    backup_env.backup_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    snapshots = []
    for index, age_days in enumerate((1, 2, 120)):
        path = backup_env.backup_dir / (
            f"{backups.MIGRATION_BACKUP_PREFIX}-2026010{index + 1}-000000.sqlite3"
        )
        path.write_bytes(b"snapshot")
        stamp = now - age_days * 86400
        os.utime(path, (stamp, stamp))
        snapshots.append(path)

    planned = backups.plan_migration_snapshot_prune(
        directory=backup_env.backup_dir,
        keep=2,
        days=90,
    )
    assert planned == [snapshots[2]]
    dry_run = backups.prune_migration_snapshots(
        directory=backup_env.backup_dir,
        keep=2,
        days=90,
        dry_run=True,
    )
    assert dry_run == [snapshots[2]]
    assert snapshots[2].exists()

    removed = backups.prune_migration_snapshots(
        directory=backup_env.backup_dir,
        keep=2,
        days=90,
    )
    assert removed == [snapshots[2]]
    assert not snapshots[2].exists()


def test_verify_sqlite_snapshot_checks_integrity_and_foreign_keys(tmp_path):
    path = tmp_path / "snapshot.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
        )
        connection.commit()
    finally:
        connection.close()

    result = backups.verify_sqlite_snapshot(path)
    assert result["ok"] is True
    assert result["database_integrity"] == ["ok"]
    assert result["foreign_key_violations"] == 0


@pytest.mark.asyncio
async def test_restore_support_files_online_when_runtime_dir_is_outside_app_tree(
    backup_env, tmp_path, monkeypatch
):
    project_root = tmp_path / "app"
    project_root.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setattr(backups, "BASE_DIR", project_root)
    (runtime_dir / "vcard.py").write_text('VCARD = "backup"\n', encoding="utf-8")
    (runtime_dir / "chat_slang.csv").write_text("brb,backup\n", encoding="utf-8")
    monkeypatch.setitem(backups.config, "runtime_data_dir", str(runtime_dir))

    _write_sqlite_value(backup_env.db_path, "backup")
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="runtime support")

    _write_sqlite_value(backup_env.db_path, "current")
    (runtime_dir / "vcard.py").write_text('VCARD = "current"\n', encoding="utf-8")
    (runtime_dir / "chat_slang.csv").write_text("brb,current\n", encoding="utf-8")

    result = await backups.restore_backup(bot, archive)

    assert (runtime_dir / "vcard.py").read_text(encoding="utf-8") == 'VCARD = "backup"\n'
    assert (runtime_dir / "chat_slang.csv").read_text(encoding="utf-8") == "brb,backup\n"
    assert result["restored"] == [
        "bot.db",
        "config.py",
        "vcard.py",
        "chat_slang.csv",
    ]
    assert result["manual_restore"] == []
