from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.db as db_plugin


def test_format_bytes_boundaries():
    assert db_plugin._format_bytes(0) == "0.0 B"
    assert db_plugin._format_bytes(512) == "512.0 B"
    assert db_plugin._format_bytes(1024) == "1.0 KiB"
    assert db_plugin._format_bytes(1024 * 1024) == "1.0 MiB"
    assert db_plugin._format_bytes(1024 * 1024 * 1024) == "1.0 GiB"


@pytest.mark.asyncio
async def test_db_status_reports_sqlite_pragmas(tmp_path):
    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"x" * 2048)

    bot = MagicMock()
    bot.db.path = str(db_file)
    bot.db.fetch_one = AsyncMock(
        side_effect=[
            ("ok",),
            (11,),
            (4096,),
            (2,),
        ]
    )
    bot.reply = MagicMock()
    msg = MagicMock()

    await db_plugin.db_status(bot, "admin@example.org", "admin", [], msg, False)

    bot.db.fetch_one.assert_any_await("PRAGMA integrity_check")
    bot.db.fetch_one.assert_any_await("PRAGMA page_count")
    bot.db.fetch_one.assert_any_await("PRAGMA page_size")
    bot.db.fetch_one.assert_any_await("PRAGMA freelist_count")
    lines = bot.reply.call_args.args[1]
    assert lines == [
        "🗄️ Database status",
        f"Path: {Path(db_file)}",
        "Size: 2.0 KiB",
        "Integrity: ok",
        "Page count: 11",
        "Page size: 4096",
        "Freelist pages: 2",
    ]


@pytest.mark.asyncio
async def test_db_status_handles_missing_file_empty_integrity_and_errors(tmp_path):
    missing = tmp_path / "missing.db"
    bot = MagicMock()
    bot.db.path = str(missing)
    bot.db.fetch_one = AsyncMock(side_effect=[None, (0,), (4096,), (0,)])
    bot.reply = MagicMock()
    msg = MagicMock()

    await db_plugin.db_status(bot, "admin@example.org", "admin", [], msg, False)

    lines = bot.reply.call_args.args[1]
    assert f"Path: {Path(missing)}" in lines
    assert "Size: 0.0 B" in lines
    assert "Integrity: unknown" in lines

    failing_bot = MagicMock()
    failing_bot.db.path = str(missing)
    failing_bot.db.fetch_one = AsyncMock(side_effect=RuntimeError("boom"))
    failing_bot.reply_error = MagicMock()

    await db_plugin.db_status(failing_bot, "admin@example.org", "admin", [], msg, False)

    failing_bot.reply_error.assert_called_once()
    assert "Could not inspect database: boom" in failing_bot.reply_error.call_args.args[1]
