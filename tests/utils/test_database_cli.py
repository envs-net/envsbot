import pytest

from database.manager import DatabaseManager
from utils import database_cli as database_cli_module
from utils.database_cli import (
    database_check,
    database_migrate,
    database_schema,
    database_status,
)


@pytest.mark.asyncio
async def test_database_schema_reports_matching_fingerprints(tmp_path):
    path = tmp_path / "bot.db"
    db = DatabaseManager(str(path), flush_interval=999)
    await db.connect(start_background=False)
    await db.close()

    code, output = await database_schema({"db": str(path)})

    assert code == 0
    assert "Migration catalog:" in output
    assert "Schema actual:" in output
    assert "Schema expected:" in output
    assert "Schema match:      yes" in output
    assert "Migration checksums: ok" in output


@pytest.mark.asyncio
async def test_database_schema_and_check_detect_schema_drift(tmp_path):
    path = tmp_path / "bot.db"
    db = DatabaseManager(str(path), flush_interval=999)
    await db.connect(start_background=False)
    await db.write(
        "CREATE TABLE operator_schema_drift (id INTEGER PRIMARY KEY)",
        label="test_operator_schema_drift",
    )
    await db.close()

    schema_code, schema_output = await database_schema({"db": str(path)})
    check_code, check_output = await database_check({"db": str(path)})

    assert schema_code == 1
    assert "Schema match:      NO" in schema_output
    assert check_code == 1
    assert "Schema fingerprint: MISMATCH" in check_output


@pytest.mark.asyncio
async def test_database_status_reports_changed_migration_checksum(tmp_path):
    path = tmp_path / "bot.db"
    db = DatabaseManager(str(path), flush_interval=999)
    await db.connect(start_background=False)
    rows = await db.list_migrations()
    version = str(rows[0]["version"])
    await db.write(
        "UPDATE schema_migrations SET checksum=? WHERE version=?",
        ("0" * 64, version),
        label="test_changed_migration_checksum",
    )
    await db.close()

    code, output = await database_status({"db": str(path)})

    assert code == 1
    assert f"Changed migrations: {version}" in output
    assert "Migration catalog:" in output
    assert "Schema fingerprint:" in output


class _FakeMigrationDatabase:
    instances = []
    versions = ["0009_outbox_origin_id", "0010_reminders"]
    run_error = None

    def __init__(self, path):
        self.path = path
        self.connect_kwargs = None
        self.dry_run = None
        self.closed = False
        type(self).instances.append(self)

    async def connect(self, **kwargs):
        self.connect_kwargs = kwargs

    async def run_migrations(self, *, dry_run):
        self.dry_run = dry_run
        if type(self).run_error is not None:
            raise type(self).run_error
        return list(type(self).versions)

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_migration_database(monkeypatch):
    _FakeMigrationDatabase.instances = []
    _FakeMigrationDatabase.versions = ["0009_outbox_origin_id", "0010_reminders"]
    _FakeMigrationDatabase.run_error = None
    monkeypatch.setattr(database_cli_module, "DatabaseManager", _FakeMigrationDatabase)
    return _FakeMigrationDatabase


@pytest.mark.asyncio
async def test_database_migrate_applies_pending_migrations_by_default(
    fake_migration_database,
):
    code, output = await database_migrate({"db": "/tmp/envsbot-test.db"})

    assert code == 0
    assert output == "Applied 2 migration(s): 0009_outbox_origin_id, 0010_reminders"
    assert len(fake_migration_database.instances) == 1
    db = fake_migration_database.instances[0]
    assert db.path == "/tmp/envsbot-test.db"
    assert db.connect_kwargs == {
        "run_migrations": False,
        "start_background": False,
        "enforce_schema_compatibility": True,
    }
    assert db.dry_run is False
    assert db.closed is True


@pytest.mark.asyncio
async def test_database_migrate_dry_run_previews_pending_migrations(
    fake_migration_database,
):
    code, output = await database_migrate({"db": "preview.db"}, dry_run=True)

    assert code == 0
    assert output == "Would apply 2 migration(s): 0009_outbox_origin_id, 0010_reminders"
    db = fake_migration_database.instances[0]
    assert db.dry_run is True
    assert db.closed is True


@pytest.mark.asyncio
async def test_database_migrate_reports_when_schema_is_current(fake_migration_database):
    fake_migration_database.versions = []

    code, output = await database_migrate({})

    assert code == 0
    assert output == "Database schema is already up to date."
    db = fake_migration_database.instances[0]
    assert db.path == "bot.db"
    assert db.dry_run is False
    assert db.closed is True


@pytest.mark.asyncio
async def test_database_migrate_closes_database_when_migration_fails(
    fake_migration_database,
):
    fake_migration_database.run_error = RuntimeError("migration failed")

    with pytest.raises(RuntimeError, match="migration failed"):
        await database_migrate({"db": "broken.db"})

    db = fake_migration_database.instances[0]
    assert db.dry_run is False
    assert db.closed is True
