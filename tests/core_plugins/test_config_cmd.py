from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.config_cmd as config_cmd


REDACTION_SAMPLE = {
    "password": "secret",
    "nested": {"api_key": "token", "safe": "ok"},
    "items": [{"secret_token": "hidden"}, "plain"],
}
REDACTED_SAMPLE = {
    "password": "<redacted>",
    "nested": {"api_key": "<redacted>", "safe": "ok"},
    "items": [{"secret_token": "<redacted>"}, "plain"],
}


def _bot():
    bot = MagicMock()
    bot.prefix = ","
    bot.nick = "oldnick"
    bot.reply = MagicMock()
    bot.reply_ok = MagicMock()
    bot.reply_error = MagicMock()
    return bot


def test_config_diff_entries_reports_muc_banbot_style_and_skips_secrets(monkeypatch):
    monkeypatch.setattr(
        config_cmd,
        "get_config_diff_sections",
        lambda cfg: [
            (
                "XMPP Account",
                [
                    ("JID", "bot@example.org", "envsbot@domain.tld"),
                    ("PASSWORD", "secret", "yourpassword"),
                ],
            ),
            ("URL Check", [("URLCHECK_WAIT_SECONDS", 60, 120)]),
        ],
    )

    lines = config_cmd._config_diff_entries({})

    assert lines == [
        "• JID",
        "  current: 'bot@example.org'",
        "  default: 'envsbot@domain.tld'",
        "",
        "• URLCHECK_WAIT_SECONDS",
        "  current: 60",
        "  default: 120",
    ]



def test_config_diff_entries_shows_idlerpg_leaf_changes(monkeypatch):
    monkeypatch.setattr(
        config_cmd,
        "get_config_diff_sections",
        lambda cfg: [
            (
                "IdleRPG",
                [
                    (
                        "IDLERPG.topic_custom_text",
                        "Welcome to IdleRPG",
                        "",
                    ),
                    ("IDLERPG.export_top_limit", 100, 50),
                ],
            ),
        ],
    )

    lines = config_cmd._config_diff_entries({})

    assert "• IDLERPG.topic_custom_text" in lines
    assert "  current: 'Welcome to IdleRPG'" in lines
    assert "• IDLERPG.export_top_limit" in lines
    assert "current: {'tick_seconds'" not in "\n".join(lines)

def test_config_diff_entries_handles_no_changes(monkeypatch):
    monkeypatch.setattr(config_cmd, "get_config_diff_sections", lambda cfg: [])

    assert config_cmd._config_diff_entries({}) == []


@pytest.mark.asyncio
async def test_config_diff_uses_muc_banbot_style_default_full_output(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    monkeypatch.setattr(
        config_cmd,
        "_config_diff_entries",
        lambda cfg: [
            "• ONE",
            "  current: 1",
            "  default: 0",
            "",
            "• TWO",
            "  current: 2",
            "  default: 0",
        ],
    )

    await config_cmd.config_diff(
        bot, "admin@example.org", "admin", [], msg, False
    )

    bot.reply.assert_called_once()
    reply = bot.reply.call_args.args[1]
    assert reply.startswith("🧩 Config Diff (2 change(s)):")
    assert "• ONE" in reply
    assert "Use ,config diff all" not in reply


@pytest.mark.asyncio
async def test_config_diff_paginates_explicit_pages(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    monkeypatch.setattr(
        config_cmd,
        "_config_diff_entries",
        lambda cfg: [f"line {idx}" for idx in range(30)],
    )

    await config_cmd.config_diff(
        bot, "admin@example.org", "admin", ["2"], msg, False
    )

    reply = bot.reply.call_args.args[1]
    assert reply.startswith("🧩 Config Diff (0 change(s)) - Page 2/2:")
    assert "line 24" in reply
    assert "Use ,config diff all for the full output." in reply


def test_redact_sensitive_keys():
    assert config_cmd._redact(REDACTION_SAMPLE) == REDACTED_SAMPLE


def test_redact_named_value():
    assert config_cmd._redact_named("PASSWORD", "secret") == "<redacted>"


def test_render_value_string():
    assert config_cmd._render_value("x") == "'x'"


def test_format_config_lines_with_redaction(monkeypatch):
    monkeypatch.setattr(
        config_cmd,
        "get_config_display_sections",
        lambda cfg: [
            (
                "Runtime",
                [("PASSWORD", "<redacted>"), ("DUCKS", {"spawn": True})],
            )
        ],
    )

    assert config_cmd._format_config_lines({"PASSWORD": "secret"}) == [
        "Runtime:",
        "• PASSWORD = '<redacted>'",
        "• DUCKS:",
        "  • spawn = True",
    ]


@pytest.mark.asyncio
async def test_config_show_uses_formatted_lines(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    monkeypatch.setattr(
        config_cmd,
        "_format_config_lines",
        lambda cfg: ["one"],
    )

    await config_cmd.config_show(
        bot, "admin@example.org", "admin", [], msg, False
    )

    assert bot.reply.call_args.args[1][0] == "⚙️ Effective config"
    assert "one" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_config_validate_accepts_valid_config(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    valid_config = {"prefix": ";", "nick": "newnick"}
    load_config = MagicMock(return_value=valid_config)
    validate_config = MagicMock()
    monkeypatch.setattr(config_cmd, "load_config", load_config)
    monkeypatch.setattr(config_cmd, "validate_config", validate_config)

    await config_cmd.config_validate(
        bot, "admin@example.org", "admin", [], msg, False
    )

    load_config.assert_called_with(require_required_keys=True)
    validate_config.assert_called_with(
        valid_config,
        require_required_keys=True,
    )
    bot.reply_ok.assert_called_with(msg, "config.py is valid.")


@pytest.mark.asyncio
async def test_config_reload_applies_runtime_config(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    valid_config = {"prefix": ";", "nick": "newnick"}
    audit = AsyncMock()
    clear_room_feature_caches = MagicMock()
    monkeypatch.setattr(
        config_cmd,
        "config",
        {"prefix": ",", "nick": "oldnick"},
    )
    monkeypatch.setattr(
        config_cmd,
        "load_config",
        MagicMock(return_value=valid_config),
    )
    monkeypatch.setattr(config_cmd, "audit_event", audit)
    monkeypatch.setattr(
        config_cmd,
        "clear_room_feature_caches",
        clear_room_feature_caches,
    )

    await config_cmd.config_reload(
        bot, "admin@example.org", "admin", [], msg, False
    )

    assert config_cmd.config == valid_config
    clear_room_feature_caches.assert_called_once_with()
    assert bot.prefix == ";"
    assert bot.nick == "newnick"
    audit.assert_awaited_once_with(
        bot,
        "config_reloaded",
        actor="admin@example.org",
        target="config",
    )
    reply = bot.reply_ok.call_args.args[1]
    assert "config.py reloaded." in reply
    assert "Prefix changed from ',' to ';'." in reply
    assert "Changed:" in reply
    assert "COMMAND_PREFIX" in reply


@pytest.mark.asyncio
async def test_config_validate_reports_errors(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    error_message = "bad config"
    monkeypatch.setattr(
        config_cmd,
        "load_config",
        MagicMock(side_effect=config_cmd.ConfigError(error_message)),
    )

    await config_cmd.config_validate(
        bot, "admin@example.org", "admin", [], msg, False
    )

    assert (
        f"Invalid config.py:\n{error_message}"
        in bot.reply_error.call_args.args[1]
    )


@pytest.mark.asyncio
async def test_config_reload_reports_errors(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    error_message = "bad config"
    monkeypatch.setattr(
        config_cmd,
        "load_config",
        MagicMock(side_effect=config_cmd.ConfigError(error_message)),
    )

    await config_cmd.config_reload(
        bot, "admin@example.org", "admin", [], msg, False
    )

    assert (
        f"Config reload failed:\n{error_message}"
        in bot.reply_error.call_args.args[1]
    )


def test_config_key_mapping_and_runtime_writable_guards():
    assert config_cmd._display_key_to_normalized("LOG_LEVEL") == "loglevel"
    assert config_cmd._display_key_to_normalized("loglevel") == "loglevel"
    assert config_cmd._normalized_to_display_key("loglevel") == "LOG_LEVEL"
    assert config_cmd._is_runtime_writable_config_key("loglevel") is True
    assert config_cmd._is_runtime_writable_config_key("jid") is False
    assert config_cmd._is_runtime_writable_config_key("password") is False
    assert config_cmd._is_runtime_writable_config_key("youtube_api_key") is False


def test_parse_config_value_and_replace_multiline_assignment():
    assert config_cmd._parse_config_value("true") is True
    assert config_cmd._parse_config_value("None") is None
    assert config_cmd._parse_config_value("42") == 42
    assert config_cmd._parse_config_value("DEBUG") == "DEBUG"

    source = "A = 1\nROOM_PLUGIN_DEFAULTS = {\n    'dice': True,\n}\nB = 2\n"
    updated = config_cmd._replace_config_assignment(
        source,
        "ROOM_PLUGIN_DEFAULTS",
        {"dice": False, "rss": True},
    )
    assert "'dice': True" not in updated
    assert "'dice': False" in updated
    assert "'rss': True" in updated
    compile(updated, "config.py", "exec")


@pytest.mark.asyncio
async def test_config_search_and_find(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    monkeypatch.setattr(
        config_cmd,
        "get_config_display_sections",
        lambda cfg: [("Runtime", [("LOG_LEVEL", "INFO"), ("PASSWORD", "secret")])],
    )

    await config_cmd.config_search(
        bot, "admin@example.org", "admin", ["log"], msg, False
    )

    reply = bot.reply.call_args.args[1]
    assert "Config search for 'log': 1 match(es)" in reply
    assert "✏️ LOG_LEVEL = 'INFO'" in reply
    assert "PASSWORD" not in reply


@pytest.mark.asyncio
async def test_config_set_updates_file_and_applies_reload(tmp_path, monkeypatch):
    bot = _bot()
    msg = MagicMock()
    config_path = tmp_path / "config.py"
    config_path.write_text(
        "JID = 'bot@example.org'\n"
        "PASSWORD = 'secret'\n"
        "NICK = 'Bot'\n"
        "OWNER = 'owner@example.org'\n"
        "LOG_LEVEL = 'INFO'\n",
        encoding="utf-8",
    )
    live_config = config_cmd.load_config(require_required_keys=False).copy()
    live_config.update({
        "jid": "bot@example.org",
        "password": "secret",
        "nick": "Bot",
        "owner": "owner@example.org",
        "loglevel": "INFO",
    })
    audit = AsyncMock()
    monkeypatch.setenv("ENVSBOT_CONFIG", str(config_path))
    monkeypatch.setattr(config_cmd, "config", live_config)
    monkeypatch.setattr(config_cmd, "create_backup", AsyncMock(return_value=None))
    monkeypatch.setattr(config_cmd, "audit_event", audit)
    monkeypatch.setattr(config_cmd, "restart_reloadable_plugin_tasks", AsyncMock(return_value=[]))

    await config_cmd.config_set(
        bot, "admin@example.org", "admin", ["LOG_LEVEL", "DEBUG"], msg, False
    )

    text = config_path.read_text(encoding="utf-8")
    assert 'LOG_LEVEL = "DEBUG"' in text
    assert config_cmd.config["loglevel"] == "DEBUG"
    assert bot.reply_ok.called
    assert "LOG_LEVEL updated: 'INFO' → 'DEBUG'" in bot.reply_ok.call_args.args[1]
    assert audit.await_count == 2


@pytest.mark.asyncio
async def test_config_set_rejects_protected_and_invalid_values(monkeypatch):
    bot = _bot()
    msg = MagicMock()
    monkeypatch.setattr(config_cmd, "config", {"loglevel": "INFO"})

    await config_cmd.config_set(
        bot, "admin@example.org", "admin", ["PASSWORD", "new"], msg, False
    )
    assert "not a runtime-writable" in bot.reply_error.call_args.args[1]

    bot.reply_error.reset_mock()
    await config_cmd.config_set(
        bot, "admin@example.org", "admin", ["LOG_LEVEL", "NOPE"], msg, False
    )
    assert "Invalid value" in bot.reply_error.call_args.args[1]


@pytest.mark.asyncio
async def test_config_unset_resets_to_sample_default(tmp_path, monkeypatch):
    bot = _bot()
    msg = MagicMock()
    config_path = tmp_path / "config.py"
    config_path.write_text(
        "JID = 'bot@example.org'\n"
        "PASSWORD = 'secret'\n"
        "NICK = 'Bot'\n"
        "OWNER = 'owner@example.org'\n"
        "LOG_LEVEL = 'DEBUG'\n",
        encoding="utf-8",
    )
    live_config = config_cmd.load_config(require_required_keys=False).copy()
    live_config.update({
        "jid": "bot@example.org",
        "password": "secret",
        "nick": "Bot",
        "owner": "owner@example.org",
        "loglevel": "DEBUG",
    })
    monkeypatch.setenv("ENVSBOT_CONFIG", str(config_path))
    monkeypatch.setattr(config_cmd, "config", live_config)
    monkeypatch.setattr(config_cmd, "create_backup", AsyncMock(return_value=None))
    monkeypatch.setattr(config_cmd, "audit_event", AsyncMock())
    monkeypatch.setattr(config_cmd, "restart_reloadable_plugin_tasks", AsyncMock(return_value=[]))

    await config_cmd.config_unset(
        bot, "admin@example.org", "admin", ["LOG_LEVEL"], msg, False
    )

    text = config_path.read_text(encoding="utf-8")
    assert 'LOG_LEVEL = "INFO"' in text
    assert config_cmd.config["loglevel"] == "INFO"
    assert "LOG_LEVEL reset to default" in bot.reply_ok.call_args.args[1]


def test_format_config_assignment_uses_safe_double_quoted_strings():
    assignment = config_cmd._format_config_assignment(
        "TRANSLATE_TO",
        'de "quoted"\nnext',
    )

    assert assignment == 'TRANSLATE_TO = "de \\"quoted\\"\\nnext"'
    compile(assignment, "<config-assignment>", "exec")


def test_write_config_text_atomic_enforces_owner_only_mode(tmp_path):
    path = tmp_path / "config.py"
    path.write_text('JID = "bot@example.org"\n', encoding="utf-8")
    path.chmod(0o644)

    config_cmd._write_config_text_atomic(path, 'JID = "new@example.org"\n')

    assert path.read_text(encoding="utf-8") == 'JID = "new@example.org"\n'
    assert path.stat().st_mode & 0o777 == 0o600
