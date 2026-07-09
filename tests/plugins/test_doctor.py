from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import core_plugins.doctor as doctor


class Cursor:
    async def fetchone(self):
        return (1,)


class Conn:
    async def execute(self, sql):
        assert sql == "SELECT 1"
        return Cursor()


class Rooms:
    async def list(self):
        return [("room@example.org", "Bot", True, "active")]


class DB:
    def __init__(self):
        self.conn = Conn()
        self.rooms = Rooms()

    async def list_migrations(self):
        return ["0001_initial_runtime_tables"]


class Tasks:
    def summary(self):
        return (2, 0, 1)


class Plugins:
    core_plugins = {"doctor", "rooms"}

    def list(self):
        return ["doctor", "rooms"]

    def discover(self):
        return ["doctor", "rooms", "rss"]


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "backup_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(doctor, "backup_keep", lambda: 5)
    monkeypatch.setattr(doctor, "backup_retention_days", lambda: 30)
    cfg = tmp_path / "config.py"
    cfg.write_text("JID = 'bot@example.org'\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "get_runtime_config_path", lambda: cfg)

    bot = MagicMock()
    bot.prefix = ","
    bot.reply = MagicMock()
    bot.db = DB()
    bot.tasks = Tasks()
    bot.bot_plugins = Plugins()
    bot.presence = SimpleNamespace(joined_rooms={"room@example.org": "Bot"})
    return bot


@pytest.mark.asyncio
async def test_doctor_command_reports_runtime_health(bot, msg=None):
    message = MagicMock()

    await doctor.doctor_command(bot, "admin@example.org", "admin", ["full", "all"], message, False)

    reply = bot.reply.call_args.args[1]
    assert reply[0].startswith("🩺 EnvsBot doctor")
    assert any("Database: connected" in line for line in reply)
    assert any("Background tasks: 2 running" in line for line in reply)
    assert any("Backup retention: keep=5, days=30" in line for line in reply)

class MigrationRow:
    def __getitem__(self, key):
        if key == "version":
            return "0002_row_version"
        if key == 0:
            return "0002_tuple_version"
        raise KeyError(key)


@pytest.mark.asyncio
async def test_doctor_migrations_accept_sqlite_rows(bot):
    async def list_migrations():
        return [MigrationRow()]

    bot.db.list_migrations = list_migrations

    lines = await doctor._db_lines(bot)

    assert any("Migrations: 0002_row_version" in line for line in lines)


def test_parse_doctor_args_supports_full_and_all_paging():
    assert doctor._parse_doctor_args([]) == (False, [])
    assert doctor._parse_doctor_args(["2"]) == (False, ["2"])
    assert doctor._parse_doctor_args(["full"]) == (True, [])
    assert doctor._parse_doctor_args(["details", "last"]) == (True, ["last"])
    assert doctor._parse_doctor_args(["all"]) == (True, ["all"])
    assert doctor._parse_doctor_args(["full", "all"]) == (True, ["all"])


@pytest.mark.asyncio
async def test_doctor_all_disables_paging_and_keeps_full_details(bot):
    message = MagicMock()

    await doctor.doctor_command(bot, "admin@example.org", "admin", ["all"], message, False)

    reply = bot.reply.call_args.args[1]
    assert reply[0] == "🩺 EnvsBot doctor"
    assert not any("Use ,doctor" in line for line in reply)
    assert any("Room room@example.org" in line for line in reply)


@pytest.mark.asyncio
async def test_doctor_plugin_section_uses_plugin_doctor(bot):
    async def plugin_doctor(name, room_jid=None):
        return [f"✅ {name}: healthy"]

    bot.bot_plugins.plugin_doctor = plugin_doctor

    lines = await doctor.build_doctor_lines(bot, sections=("plugin:rss",))

    assert lines[0] == "🩺 EnvsBot doctor"
    assert lines[1] == "Overall: ✅ healthy"
    assert any("[Plugin: rss]" in line for line in lines)
    assert any("rss: healthy" in line for line in lines)
