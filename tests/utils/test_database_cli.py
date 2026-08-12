import pytest

from database.manager import DatabaseManager
from utils.database_cli import database_check, database_schema, database_status


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
