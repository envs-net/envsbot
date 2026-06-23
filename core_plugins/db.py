"""SQLite database inspection and maintenance commands."""

from __future__ import annotations

from pathlib import Path

from utils.command import Role, command

PLUGIN_META = {
    "name": "db",
    "version": "0.1.0",
    "description": "SQLite status and integrity inspection helpers.",
    "category": "core",
}


def _format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


@command("db status", role=Role.ADMIN, aliases=["database status"])
async def db_status(bot, sender, nick, args, msg, is_room):
    """Show SQLite database status."""
    path = Path(bot.db.path)
    size = path.stat().st_size if path.exists() else 0

    try:
        row = await bot.db.fetch_one("PRAGMA integrity_check")
        integrity = row[0] if row else "unknown"
        page_count = (await bot.db.fetch_one("PRAGMA page_count"))[0]
        page_size = (await bot.db.fetch_one("PRAGMA page_size"))[0]
        freelist_count = (await bot.db.fetch_one("PRAGMA freelist_count"))[0]
    except Exception as exc:
        bot.reply_error(msg, f"Could not inspect database: {exc}")
        return

    lines = [
        "🗄️ Database status",
        f"Path: {path}",
        f"Size: {_format_bytes(size)}",
        f"Integrity: {integrity}",
        f"Page count: {page_count}",
        f"Page size: {page_size}",
        f"Freelist pages: {freelist_count}",
    ]
    bot.reply(msg, lines)
