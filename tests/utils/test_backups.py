from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest

import utils.backups as backups
import utils.config as config_mod


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


def _write_runtime_files(root):
    db_path = root / "bot.db"
    db_path.write_bytes(b"sqlite-data")
    (root / "config.py").write_text('JID = "bot@example.org"\n', encoding="utf-8")
    (root / "vcard.py").write_text('FN = "EnvsBot"\n', encoding="utf-8")
    (root / "chat_slang.csv").write_text("brb,be right back\n", encoding="utf-8")
    return db_path


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    db_path = _write_runtime_files(tmp_path)
    backup_dir = tmp_path / "data" / "backups"
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backups, "BASE_DIR", tmp_path)
    monkeypatch.delenv("ENVSBOT_CONFIG", raising=False)
    monkeypatch.setitem(backups.config, "db", str(db_path))
    monkeypatch.setitem(backups.config, "backup_dir", str(backup_dir))
    monkeypatch.setitem(backups.config, "backup_keep", 15)
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
async def test_restore_backup_restores_files_and_reconnects_database(backup_env):
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="before change")

    backup_env.db_path.write_bytes(b"changed-db")
    (backup_env.root / "config.py").write_text("BROKEN = True\n", encoding="utf-8")
    (backup_env.root / "vcard.py").write_text("BROKEN = True\n", encoding="utf-8")
    (backup_env.root / "chat_slang.csv").write_text("changed\n", encoding="utf-8")

    result = await backups.restore_backup(bot, archive)

    assert bot.db.closed is True
    assert bot.db.connected is True
    assert backup_env.db_path.read_bytes() == b"sqlite-data"
    assert (backup_env.root / "config.py").read_text(encoding="utf-8") == 'JID = "bot@example.org"\n'
    assert (backup_env.root / "vcard.py").read_text(encoding="utf-8") == 'FN = "EnvsBot"\n'
    assert (backup_env.root / "chat_slang.csv").read_text(encoding="utf-8") == "brb,be right back\n"
    assert result["archive"] == archive.name
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
    bot = SimpleNamespace(db=FakeDB(backup_env.db_path))
    archive = await backups.create_backup(bot, reason="restore failure")
    monkeypatch.setattr(backups, "_restore_entry", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("copy failed")))

    with pytest.raises(RuntimeError, match="copy failed"):
        await backups.restore_backup(bot, archive)

    assert bot.db.closed is True
    assert bot.db.connected is True


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

