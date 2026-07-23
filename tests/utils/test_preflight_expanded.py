from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

import utils.preflight as preflight


class FakeMigration:
    def __init__(self, version: str):
        self.version = version


def test_check_imports_success_and_failure(monkeypatch):
    assert preflight._check_imports() == (True, "imports: ok")

    real_import = importlib.import_module

    def failing_import(name):
        if name == "plugins":
            raise RuntimeError("secret-token=abc")
        return real_import(name)

    monkeypatch.setattr(preflight.importlib, "import_module", failing_import)

    ok, message = preflight._check_imports()
    assert ok is False
    assert "imports: RuntimeError" in message
    assert "abc" not in message


def test_check_plugin_imports_and_metadata_reports_issues(monkeypatch):
    modules = [
        ("good", SimpleNamespace(PLUGIN_META={"name": "good", "category": "utility", "description": "ok"}), "plugins"),
        ("bad", SimpleNamespace(PLUGIN_META={"name": "other"}), "plugins"),
    ]

    monkeypatch.setattr(
        "utils.command_registry.discover_command_modules",
        lambda: modules,
    )

    ok, message = preflight._check_plugin_imports_and_metadata()
    assert ok is False
    assert "metadata issues" in message
    assert "bad" in message


def test_check_plugin_imports_and_metadata_success(monkeypatch):
    modules = [
        (
            "good",
            SimpleNamespace(PLUGIN_META={"name": "good", "category": "utility", "description": "ok"}),
            "plugins",
        )
    ]
    monkeypatch.setattr("utils.command_registry.discover_command_modules", lambda: modules)

    ok, message = preflight._check_plugin_imports_and_metadata()
    assert ok is True
    assert message == "plugins: 1 importable, metadata ok"


def test_check_command_registry_empty_missing_and_success(monkeypatch):
    monkeypatch.setattr("utils.command_registry.decorated_command_records", lambda: [])
    assert preflight._check_command_registry() == (False, "command registry: no decorated commands found")

    incomplete = SimpleNamespace(name="broken", short="", usage="{prefix}broken")
    monkeypatch.setattr("utils.command_registry.decorated_command_records", lambda: [("plug", {}, incomplete)])
    ok, message = preflight._check_command_registry()
    assert ok is False
    assert "missing metadata for broken" in message

    complete = SimpleNamespace(name="ok", short="Short", usage="{prefix}ok")
    monkeypatch.setattr("utils.command_registry.decorated_command_records", lambda: [("plug", {}, complete)])
    assert preflight._check_command_registry() == (True, "command registry: 1 decorated commands")


def test_check_config_sample_warnings_missing_and_success(monkeypatch):
    monkeypatch.setattr(preflight, "load_default_config_for_diff", lambda: {"a": 1, "b": 2})
    monkeypatch.setattr(preflight, "collect_config_warnings", lambda _config: ["bad config"])
    assert preflight._check_config_sample({"a": 1}) == (False, "config warnings: bad config")

    monkeypatch.setattr(preflight, "collect_config_warnings", lambda _config: [])
    ok, message = preflight._check_config_sample({"a": 1})
    assert ok is False
    assert "sample key(s) absent" in message

    assert preflight._check_config_sample({"a": 1, "b": 2}) == (True, "config sample: ok (2 keys)")


def test_check_backup_dir_success_and_failure(tmp_path):
    backup_dir = tmp_path / "backups"
    assert preflight._check_backup_dir({"backup_dir": str(backup_dir)}) == (
        True,
        f"backup dir: writable ({backup_dir})",
    )

    blocking_file = tmp_path / "file"
    blocking_file.write_text("not a directory", encoding="utf-8")
    ok, message = preflight._check_backup_dir({"backup_dir": str(blocking_file / "child")})
    assert ok is False
    assert "backup dir:" in message


def test_check_runtime_files_avatar_and_vcard(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_PROJECT_ROOT", tmp_path)
    assert preflight._check_runtime_files({}) == (True, "runtime files: ok")

    avatar = tmp_path / "avatar.jpg"
    avatar.write_bytes(b"jpg")
    (tmp_path / "vcard_sample.py").write_text("VCARD = {}", encoding="utf-8")
    assert preflight._check_runtime_files({"avatar": str(avatar)}) == (
        True,
        "runtime files: avatar=ok, vcard_sample=ok",
    )
    assert preflight._check_runtime_files({"avatar": "avatar.jpg"}) == (
        True,
        "runtime files: avatar=ok, vcard_sample=ok",
    )

    ok, message = preflight._check_runtime_files({"avatar": str(tmp_path / "missing.jpg")})
    assert ok is False
    assert "avatar=missing" in message


def test_check_config_path_success_and_missing(tmp_path, monkeypatch):
    cfg = tmp_path / "config.py"
    cfg.write_text("JID='bot@example.org'", encoding="utf-8")
    monkeypatch.setattr(preflight, "get_runtime_config_path", lambda: cfg)
    assert preflight._check_config_path() == (True, f"config path: {cfg}")

    missing = tmp_path / "missing.py"
    monkeypatch.setattr(preflight, "get_runtime_config_path", lambda: missing)
    assert preflight._check_config_path() == (False, f"config path: missing {missing}")


def test_check_migration_catalog_success_duplicate_and_unsorted(monkeypatch):
    monkeypatch.setattr(preflight, "available_migrations", lambda: [FakeMigration("0001"), FakeMigration("0002")])
    assert preflight._check_migration_catalog() == (True, "migrations: 2 known")

    monkeypatch.setattr(preflight, "available_migrations", lambda: [FakeMigration("0001"), FakeMigration("0001")])
    assert preflight._check_migration_catalog() == (False, "migrations: duplicate version identifiers")

    monkeypatch.setattr(preflight, "available_migrations", lambda: [FakeMigration("0002"), FakeMigration("0001")])
    assert preflight._check_migration_catalog() == (False, "migrations: versions are not sorted")


@pytest.mark.asyncio
async def test_check_database_success_pending_and_failure(monkeypatch, tmp_path):
    instances = []

    class FakeDB:
        def __init__(self, path):
            self.path = path
            self.closed = False
            instances.append(self)

        async def connect(self):
            self.connected = True

        async def integrity_check(self):
            return ["ok"]

        async def migration_status(self):
            return {"pending": []}

        async def verify_read_write(self):
            self.verified = True

        async def close(self):
            self.closed = True

    monkeypatch.setattr(preflight, "DatabaseManager", FakeDB)
    ok, message = await preflight._check_database({"db": tmp_path / "bot.db"})
    assert ok is True
    assert message == "database: integrity=ok"
    assert instances[-1].closed is True

    class PendingDB(FakeDB):
        async def migration_status(self):
            return {"pending": ["0002", "0003"]}

    monkeypatch.setattr(preflight, "DatabaseManager", PendingDB)
    ok, message = await preflight._check_database({"db": tmp_path / "bot.db"})
    assert ok is False
    assert "pending_migrations=0002,0003" in message

    class BrokenDB(FakeDB):
        async def connect(self):
            raise RuntimeError("password=secret")

    monkeypatch.setattr(preflight, "DatabaseManager", BrokenDB)
    ok, message = await preflight._check_database({"db": tmp_path / "bot.db"})
    assert ok is False
    assert "RuntimeError" in message
    assert "password=<redacted>" in message
    assert "password=secret" not in message


@pytest.mark.asyncio
async def test_collect_preflight_checks_and_run_preflight(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "validate_startup_config", lambda _config: None)
    monkeypatch.setattr(preflight, "_check_config_path", lambda: (True, "config path: ok"))
    monkeypatch.setattr(preflight, "_check_config_sample", lambda _config: (True, "sample ok"))
    monkeypatch.setattr(preflight, "_check_imports", lambda: (True, "imports ok"))
    monkeypatch.setattr(preflight, "_check_plugin_imports_and_metadata", lambda: (True, "plugins ok"))
    monkeypatch.setattr(preflight, "_check_command_registry", lambda: (True, "registry ok"))
    monkeypatch.setattr(preflight, "_check_command_docs", lambda: (True, "docs ok"))
    monkeypatch.setattr(preflight, "_check_migration_catalog", lambda: (True, "migrations ok"))
    monkeypatch.setattr(preflight, "_check_backup_dir", lambda _config: (True, "backup ok"))
    monkeypatch.setattr(preflight, "_check_runtime_files", lambda _config: (True, "files ok"))

    async def fake_db(_config):
        return True, "db ok"

    monkeypatch.setattr(preflight, "_check_database", fake_db)

    checks = await preflight.collect_preflight_checks({"jid": "bot@example.org"})
    assert checks[0] == (True, "config: ok")
    assert checks[-1] == (True, "db ok")

    status = await preflight.run_preflight({"jid": "bot@example.org"})
    out = capsys.readouterr().out
    assert status == 0
    assert "Overall: ✅ ok" in out

@pytest.mark.asyncio
async def test_check_database_keeps_bare_key_names_in_error_text(monkeypatch, tmp_path):
    class BareSecretDB:
        async def connect(self):
            raise RuntimeError("secret")

        async def close(self):
            pass

    monkeypatch.setattr(preflight, "DatabaseManager", lambda _path: BareSecretDB())
    ok, message = await preflight._check_database({"db": tmp_path / "bot.db"})

    assert ok is False
    assert "RuntimeError: secret" in message


@pytest.mark.asyncio
async def test_collect_preflight_checks_has_stable_order_and_failure_path(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "validate_startup_config", lambda _config: None)
    monkeypatch.setattr(preflight, "_check_config_path", lambda: (True, "config path: ok"))
    monkeypatch.setattr(
        preflight,
        "_check_sensitive_permissions",
        lambda _config: (True, "permissions ok"),
    )
    monkeypatch.setattr(preflight, "_check_config_sample", lambda _config: (True, "sample ok"))
    monkeypatch.setattr(preflight, "_check_imports", lambda: (True, "imports ok"))
    monkeypatch.setattr(preflight, "_check_plugin_imports_and_metadata", lambda: (True, "plugins ok"))
    monkeypatch.setattr(preflight, "_check_command_registry", lambda: (True, "registry ok"))
    monkeypatch.setattr(preflight, "_check_command_docs", lambda: (True, "docs ok"))
    monkeypatch.setattr(preflight, "_check_migration_catalog", lambda: (True, "migrations ok"))
    monkeypatch.setattr(preflight, "_check_backup_dir", lambda _config: (True, "backup ok"))
    monkeypatch.setattr(preflight, "_check_runtime_files", lambda _config: (True, "files ok"))

    async def fake_db(_config):
        return True, "db ok"

    monkeypatch.setattr(preflight, "_check_database", fake_db)

    checks = await preflight.collect_preflight_checks({"jid": "bot@example.org"})
    assert checks == [
        (True, "config: ok"),
        (True, "config path: ok"),
        (True, "permissions ok"),
        (True, "sample ok"),
        (True, "imports ok"),
        (True, "plugins ok"),
        (True, "registry ok"),
        (True, "docs ok"),
        (True, "migrations ok"),
        (True, "backup ok"),
        (True, "files ok"),
        (True, "db ok"),
    ]

    monkeypatch.setattr(preflight, "_check_imports", lambda: (False, "imports failed"))
    status = await preflight.run_preflight({"jid": "bot@example.org"})
    out = capsys.readouterr().out
    assert status == 1
    assert "Overall: ❌ failed" in out
    assert "imports failed" in out


def test_sensitive_permission_check_includes_database_sidecars_and_archives(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "config.py"
    database_path = tmp_path / "bot.db"
    wal_path = tmp_path / "bot.db-wal"
    backup_dir = tmp_path / "backups"
    archive_path = backup_dir / "envsbot-backup-test.zip"

    backup_dir.mkdir(mode=0o700)
    for path in (config_path, database_path, wal_path, archive_path):
        path.write_text("secret", encoding="utf-8")
        path.chmod(0o600)
    monkeypatch.setattr(preflight, "get_runtime_config_path", lambda: config_path)

    ok, message = preflight._check_sensitive_permissions(
        {"db": str(database_path), "backup_dir": str(backup_dir)}
    )
    assert ok is True
    assert message == "file permissions: owner-only"

    wal_path.chmod(0o644)
    archive_path.chmod(0o640)
    ok, message = preflight._check_sensitive_permissions(
        {"db": str(database_path), "backup_dir": str(backup_dir)}
    )
    assert ok is False
    assert "database WAL=0644" in message
    assert "backup envsbot-backup-test.zip=0640" in message


def test_check_command_registry_handles_import_failure_and_all_metadata_fields(monkeypatch):
    def fail_records():
        raise RuntimeError("secret-token=abc")

    monkeypatch.setattr("utils.command_registry.decorated_command_records", fail_records)
    ok, message = preflight._check_command_registry()
    assert ok is False
    assert message.startswith("command registry: RuntimeError:")
    assert "abc" not in message

    commands = [
        SimpleNamespace(name="missing-short", short="", usage="{prefix}one"),
        SimpleNamespace(name="missing-usage", short="Two", usage=""),
        SimpleNamespace(name="missing-both", short="", usage=""),
        SimpleNamespace(name="missing-four", short="", usage="x"),
        SimpleNamespace(name="missing-five", short="x", usage=""),
        SimpleNamespace(name="missing-six", short="", usage="x"),
    ]
    monkeypatch.setattr(
        "utils.command_registry.decorated_command_records",
        lambda: [("plug", {}, command) for command in commands],
    )
    assert preflight._check_command_registry() == (
        False,
        "command registry: missing metadata for missing-short, missing-usage, "
        "missing-both, missing-four, missing-five",
    )


def test_check_config_sample_handles_loader_failure_warning_preview_and_empty_sample(monkeypatch):
    def fail_load():
        raise RuntimeError("password=super-secret")

    monkeypatch.setattr(preflight, "load_default_config_for_diff", fail_load)
    ok, message = preflight._check_config_sample({})
    assert ok is False
    assert message.startswith("config sample: RuntimeError:")
    assert "super-secret" not in message

    monkeypatch.setattr(
        preflight,
        "load_default_config_for_diff",
        lambda: {"a": 1, "b": 2, "c": 3},
    )
    monkeypatch.setattr(
        preflight,
        "collect_config_warnings",
        lambda _config: ["one", "two", "three", "four"],
    )
    assert preflight._check_config_sample({}) == (
        False,
        "config warnings: one; two; three",
    )

    monkeypatch.setattr(preflight, "collect_config_warnings", lambda _config: [])
    assert preflight._check_config_sample({"a": 1, "extra": 9}) == (
        False,
        "config sample: 2 sample key(s) absent from runtime defaults",
    )

    monkeypatch.setattr(preflight, "load_default_config_for_diff", lambda: {})
    assert preflight._check_config_sample({"extra": 9}) == (
        True,
        "config sample: ok (0 keys)",
    )


def test_preflight_registry_and_config_checks_contain_malformed_inputs(monkeypatch):
    monkeypatch.setattr(
        "utils.command_registry.decorated_command_records",
        lambda: [("broken",)],
    )
    ok, message = preflight._check_command_registry()
    assert ok is False
    assert message.startswith("command registry: ValueError:")

    unnamed = SimpleNamespace(name=None, short=" ", usage="x")
    monkeypatch.setattr(
        "utils.command_registry.decorated_command_records",
        lambda: [("plug", {}, unnamed)],
    )
    assert preflight._check_command_registry() == (
        False,
        "command registry: missing metadata for <unnamed>",
    )

    monkeypatch.setattr(preflight, "load_default_config_for_diff", lambda: {"a": 1})

    def broken_warnings(_config):
        raise RuntimeError("token=secret")

    monkeypatch.setattr(preflight, "collect_config_warnings", broken_warnings)
    ok, message = preflight._check_config_sample({"a": 1})
    assert ok is False
    assert message.startswith("config sample: RuntimeError:")
    assert "secret" not in message
