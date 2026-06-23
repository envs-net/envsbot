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
