from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
    bot.boundjid = SimpleNamespace(bare="bot@example.org")
    bot.client_roster = {
        "bot@example.org": {"subscription": "both"},
        "room@example.org": {"subscription": "both"},
        "alice@example.org": {"subscription": "both", "resources": {"phone": {}}},
        "removed@example.org": {"subscription": "remove"},
    }
    return bot


@pytest.mark.asyncio
async def test_doctor_command_reports_runtime_health(bot):
    message = MagicMock()

    await doctor.doctor_command(bot, "admin@example.org", "admin", ["full", "all"], message, False)

    reply = bot.reply.call_args.args[1]
    assert reply[0].startswith("🩺 EnvsBot doctor")
    assert any("Database: connected" in line for line in reply)
    assert any("Background tasks: 2 running" in line for line in reply)
    assert any("Backup retention: keep=5, days=30" in line for line in reply)
    assert any("1:1 DM contacts: 1" in line for line in reply)


class MigrationRow:
    def __getitem__(self, key):
        if key == "version":
            return "0002_row_version"
        if key == 0:
            return "0002_tuple_version"
        raise KeyError(key)


@pytest.mark.asyncio
async def test_room_lines_reports_direct_contact_count_failure_without_aborting(bot):
    class BrokenRoster:
        def keys(self):
            raise RuntimeError("roster unavailable")

    bot.client_roster = BrokenRoster()

    lines = await doctor._room_lines(bot, full=False)

    assert any("Rooms in DB: 1" in line for line in lines)
    assert any(
        "1:1 DM contacts: count failed: roster unavailable" in line
        for line in lines
    )


@pytest.mark.asyncio
async def test_doctor_migrations_accept_sqlite_rows(bot):
    async def list_migrations():
        return [MigrationRow()]

    bot.db.list_migrations = list_migrations

    lines = await doctor._db_lines(bot)

    assert any("Migrations: 0002_row_version" in line for line in lines)


@pytest.mark.asyncio
async def test_doctor_all_disables_paging_and_keeps_full_details(bot):
    message = MagicMock()

    await doctor.doctor_command(bot, "admin@example.org", "admin", ["all"], message, False)

    reply = bot.reply.call_args.args[1]
    assert reply[0] == "🩺 EnvsBot doctor"
    assert not any("Use ,doctor" in line for line in reply)
    assert any("Room room@example.org" in line for line in reply)
    assert any("1:1 DM contacts: 1" in line for line in reply)


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


@pytest.mark.asyncio
async def test_doctor_warning_and_failed_filters(bot):
    async def plugin_doctor(name, room_jid=None):
        if name == "rss":
            return ["⚠️ rss: retry backoff active"]
        if name == "weather":
            return ["🔴 weather: API failed"]
        return [f"✅ {name}: ok"]

    bot.bot_plugins.plugin_doctor = plugin_doctor
    message = MagicMock()

    await doctor.doctor_command(bot, "admin@example.org", "admin", ["warnings"], message, False)
    warning_reply = "\n".join(bot.reply.call_args.args[1])
    assert "doctor — warnings" in bot.reply.call_args.args[1][0]
    assert "rss: retry backoff active" in warning_reply
    assert "weather: API failed" not in warning_reply

    await doctor.doctor_failed(bot, "admin@example.org", "admin", [], message, False)
    failed_reply = "\n".join(bot.reply.call_args.args[1])
    assert "doctor — failed" in bot.reply.call_args.args[1][0]
    assert "weather: API failed" in failed_reply
    assert "rss: retry backoff active" not in failed_reply


def test_problem_lines_empty_messages():
    assert doctor._problem_lines(["🩺 EnvsBot doctor", "Overall: ✅ healthy"], mode="warnings") == [
        "✅ No doctor warnings found."
    ]
    assert doctor._problem_lines(["🩺 EnvsBot doctor", "Overall: ✅ healthy"], mode="failed") == [
        "✅ No failed doctor checks found."
    ]


@pytest.mark.asyncio
async def test_doctor_release_section_reports_release_readiness(bot, monkeypatch):
    monkeypatch.setattr(
        doctor,
        "check_for_updates_once",
        AsyncMock(return_value=(False, "1.5.0", None)),
    )
    monkeypatch.setattr(doctor, "_command_docs_line", lambda: "✅ Command docs: ok (126 commands)")
    monkeypatch.setattr(doctor, "_config_sample_line", lambda: "✅ Config sample: ok")
    monkeypatch.setattr(doctor, "_release_backup_line", lambda: "✅ Latest backup: backup.zip · now")

    async def metadata_issues():
        return []

    bot.bot_plugins.all_metadata_issues = metadata_issues

    lines = await doctor.build_doctor_lines(bot, sections=("release",))

    assert any("[Release readiness]" in line for line in lines)
    assert any("Local version" in line for line in lines)
    assert any("Latest release: v1.5.0 (current)" in line for line in lines)
    assert any("Command docs: ok" in line for line in lines)
    assert any("Migrations: ok" in line for line in lines)
    assert any("Plugin metadata: ok" in line for line in lines)


@pytest.mark.asyncio
async def test_doctor_release_command_selects_release_section(bot, monkeypatch):
    monkeypatch.setattr(
        doctor,
        "build_doctor_lines",
        AsyncMock(return_value=["🩺 EnvsBot doctor", "Overall: ✅ healthy", "", "[Release readiness]"]),
    )
    message = MagicMock()

    await doctor.doctor_release(bot, "admin@example.org", "admin", [], message, False)

    reply_text = "\n".join(bot.reply.call_args.args[1])

    assert "🩺 EnvsBot doctor" in reply_text
    assert "Release readiness" in reply_text


def test_parse_doctor_sections_supports_release_aliases():
    assert doctor._parse_doctor_sections(["release"])[1] == ("release",)
    assert doctor._parse_doctor_sections(["preflight"])[1] == ("release",)


def test_translate_is_in_full_plugin_health_and_has_focused_aliases():
    assert "translate" in doctor._PLUGIN_HEALTH_PLUGINS
    assert doctor._parse_doctor_sections(["translate"])[1] == (
        "plugin:translate",
    )
    assert doctor._parse_doctor_sections(["tr"])[1] == (
        "plugin:translate",
    )


@pytest.mark.asyncio
async def test_full_plugin_health_calls_translate_doctor():
    checked = []

    async def plugin_doctor(name, room_jid=None):
        checked.append((name, room_jid))
        return [f"✅ {name}: healthy"]

    bot = SimpleNamespace(
        bot_plugins=SimpleNamespace(plugin_doctor=plugin_doctor),
    )

    lines = await doctor._section_lines(bot, "plugin-health", full=True)

    assert ("translate", None) in checked
    assert "✅ translate: healthy" in lines


def test_parse_doctor_sections_full_selects_every_section():
    full, sections, page_args = doctor._parse_doctor_sections(["full"])

    assert full is True
    assert sections == doctor._ALL_SECTIONS
    assert "network" in sections
    assert "release" in sections
    assert page_args == []

    full, sections, page_args = doctor._parse_doctor_sections(["tasks", "full"])

    assert full is True
    assert sections == ("tasks",)
    assert page_args == []


def test_network_lines_warn_when_private_fetch_urls_are_allowed(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "config",
        {
            "http_timeout_seconds": 8,
            "http_user_agent": "agent",
            "allow_private_fetch_urls": True,
        },
    )

    lines = doctor._network_lines()

    assert "⚠️ Private fetch URLs: allowed" in lines
    assert doctor._overall_status(lines) == "Overall: ⚠️ 1 warning(s)"

    monkeypatch.setattr(
        doctor,
        "config",
        {
            "http_timeout_seconds": 8,
            "http_user_agent": "agent",
            "allow_private_fetch_urls": False,
        },
    )

    assert "✅ Private fetch URLs: blocked" in doctor._network_lines()


def test_repo_root_handles_mutmut_module_paths(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mutant_module = tmp_path / "mutants" / "core_plugins" / "doctor.py"
    mutant_module.parent.mkdir(parents=True)
    mutant_module.write_text("# mutant copy\n", encoding="utf-8")

    assert doctor._repo_root(mutant_module) == tmp_path
    assert doctor._repo_root(mutant_module.parent) == tmp_path


def test_repo_root_falls_back_to_explicit_fallback_for_non_checkout_paths(tmp_path):
    orphan_module = tmp_path / "outside" / "doctor.py"
    orphan_module.parent.mkdir()
    orphan_module.write_text("# no checkout markers nearby\n", encoding="utf-8")

    assert doctor._repo_root(orphan_module, fallback=tmp_path) == tmp_path


def test_release_command_docs_line_reports_missing_script(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)

    assert doctor._command_docs_line() == "🔴 Command docs: check script missing"


def test_release_command_docs_line_handles_ok_errors_and_exceptions(monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check_command_docs.py").write_text("# test checker\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)

    def fake_ok(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="Command docs check passed (127 decorated commands).\n",
            stderr="",
        )

    monkeypatch.setattr(doctor.subprocess, "run", fake_ok)
    assert doctor._command_docs_line() == "✅ Command docs: ok (127 commands)"

    def fake_errors(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="Command docs check failed:\n- docs/commands.md is out of date\n",
            stderr="",
        )

    monkeypatch.setattr(doctor.subprocess, "run", fake_errors)
    assert doctor._command_docs_line() == (
        "🔴 Command docs: 1 issue(s); run scripts/generate_commands_md.py"
    )

    def fake_exception(*args, **kwargs):
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(doctor.subprocess, "run", fake_exception)
    assert doctor._command_docs_line() == "🔴 Command docs: check failed: validator unavailable"


def test_release_config_sample_line_handles_ok_warnings_missing_and_errors(monkeypatch):
    monkeypatch.setattr(doctor, "config", {"prefix": ",", "jid": "bot@example.org"})
    monkeypatch.setattr(doctor, "load_default_config_for_diff", lambda: {"prefix": ","})
    monkeypatch.setattr(doctor, "collect_config_warnings", lambda cfg: [])
    assert doctor._config_sample_line() == "✅ Config sample: ok"

    monkeypatch.setattr(
        doctor,
        "collect_config_warnings",
        lambda cfg: ["first warning", "second warning", "third warning", "fourth warning"],
    )
    warning_line = doctor._config_sample_line()
    assert warning_line.startswith("ℹ️ Config warnings: first warning; second warning; third warning")
    assert warning_line.endswith("…")

    monkeypatch.setattr(doctor, "load_default_config_for_diff", lambda: {"prefix": ",", "owner": "admin@example.org"})
    monkeypatch.setattr(doctor, "collect_config_warnings", lambda cfg: [])
    assert doctor._config_sample_line() == "🔴 Config sample: missing runtime key(s): owner"

    def broken_defaults():
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "load_default_config_for_diff", broken_defaults)
    assert doctor._config_sample_line() == "🔴 Config sample: check failed: boom"


def test_release_backup_line_reports_empty_latest_and_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "backup_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(doctor, "list_backups", lambda directory: [])
    assert doctor._release_backup_line() == "ℹ️ Latest backup: no managed backup found"

    backup = SimpleNamespace(name="envsbot-backup.zip", created_at="2026-07-10 10:00")
    monkeypatch.setattr(doctor, "list_backups", lambda directory: [backup])
    assert doctor._release_backup_line() == "✅ Latest backup: envsbot-backup.zip · 2026-07-10 10:00"

    def broken_backups(directory):
        raise RuntimeError("backup store failed")

    monkeypatch.setattr(doctor, "list_backups", broken_backups)
    assert doctor._release_backup_line() == "🔴 Latest backup: backup store failed"


def test_release_permissions_line_reports_insecure_backup(bot, tmp_path, monkeypatch):
    doctor.get_runtime_config_path().chmod(0o600)
    database = tmp_path / "bot.db"
    database.write_text("db", encoding="utf-8")
    database.chmod(0o600)
    bot.db.path = str(database)

    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    archive = backups / "envsbot-backup-test.zip"
    archive.write_text("archive", encoding="utf-8")
    archive.chmod(0o644)
    monkeypatch.setattr(doctor, "backup_dir", lambda: backups)

    line = doctor._release_permissions_line(bot)
    assert "🔴 File permissions" in line
    assert "backup envsbot-backup-test.zip=0644" in line

    archive.chmod(0o600)
    assert "✅ File permissions: owner-only" in doctor._release_permissions_line(bot)
