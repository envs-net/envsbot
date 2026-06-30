from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.config_cmd as config_cmd


def test_format_diff_lines_reports_grouped_changes_and_redacts(monkeypatch):
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

    lines = config_cmd._format_diff_lines({})

    assert lines[0] == "XMPP Account:"
    assert "• JID = 'bot@example.org' (default: 'envsbot@domain.tld')" in lines
    assert "• PASSWORD = '<redacted>' (default: '<redacted>')" in lines
    assert "URL Check:" in lines
    assert "• URLCHECK_WAIT_SECONDS = 60 (default: 120)" in lines


def test_format_diff_lines_handles_no_changes(monkeypatch):
    monkeypatch.setattr(config_cmd, "get_config_diff_sections", lambda cfg: [])

    assert config_cmd._format_diff_lines({}) == [
        "No config differences from config_sample.py defaults."
    ]


@pytest.mark.asyncio
async def test_config_diff_uses_pagination(monkeypatch):
    bot = MagicMock()
    bot.prefix = ","
    msg = MagicMock()
    monkeypatch.setattr(config_cmd, "_format_diff_lines", lambda cfg: ["one", "two"])

    await config_cmd.config_diff(bot, "admin@example.org", "admin", [], msg, False)

    bot.reply.assert_called_once()
    reply = bot.reply.call_args.args[1]
    assert reply[0] == "⚙️ Config differences"
    assert "one" in reply


def test_redaction_and_format_config_lines(monkeypatch):
    value = {
        "password": "secret",
        "nested": {"api_key": "token", "safe": "ok"},
        "items": [{"secret_token": "hidden"}, "plain"],
    }
    assert config_cmd._redact(value) == {
        "password": "<redacted>",
        "nested": {"api_key": "<redacted>", "safe": "ok"},
        "items": [{"secret_token": "<redacted>"}, "plain"],
    }
    assert config_cmd._redact_named("PASSWORD", "secret") == "<redacted>"
    assert config_cmd._render_value("x") == "'x'"

    monkeypatch.setattr(
        config_cmd,
        "get_config_display_sections",
        lambda cfg: [("Runtime", [("PASSWORD", "<redacted>"), ("DUCKS", {"spawn": True})])],
    )

    assert config_cmd._format_config_lines({"PASSWORD": "secret"}) == [
        "Runtime:",
        "• PASSWORD = '<redacted>'",
        "• DUCKS:",
        "  • spawn = True",
    ]


@pytest.mark.asyncio
async def test_config_show_validate_and_reload(monkeypatch):
    bot = MagicMock()
    bot.prefix = ","
    bot.nick = "oldnick"
    bot.reply = MagicMock()
    bot.reply_ok = MagicMock()
    bot.reply_error = MagicMock()
    msg = MagicMock()

    monkeypatch.setattr(config_cmd, "_format_config_lines", lambda cfg: ["one"])
    await config_cmd.config_show(bot, "admin@example.org", "admin", [], msg, False)
    assert bot.reply.call_args.args[1][0] == "⚙️ Effective config"
    assert "one" in bot.reply.call_args.args[1]

    valid_config = {"prefix": ";", "nick": "newnick"}
    load_config = MagicMock(return_value=valid_config)
    validate_config = MagicMock()
    audit = AsyncMock()
    clear_room_feature_caches = MagicMock()
    monkeypatch.setattr(config_cmd, "load_config", load_config)
    monkeypatch.setattr(config_cmd, "validate_config", validate_config)
    monkeypatch.setattr(config_cmd, "audit_event", audit)
    monkeypatch.setattr(
        config_cmd, "clear_room_feature_caches", clear_room_feature_caches
    )

    await config_cmd.config_validate(bot, "admin@example.org", "admin", [], msg, False)
    load_config.assert_called_with(require_required_keys=True)
    validate_config.assert_called_with(valid_config, require_required_keys=True)
    bot.reply_ok.assert_called_with(msg, "config.py is valid.")

    original_config = dict(config_cmd.config)
    try:
        config_cmd.config.clear()
        config_cmd.config.update({"prefix": ",", "nick": "oldnick"})
        await config_cmd.config_reload(bot, "admin@example.org", "admin", [], msg, False)
        assert config_cmd.config == valid_config
        clear_room_feature_caches.assert_called_once_with()
        assert bot.prefix == ";"
        assert bot.nick == "newnick"
        audit.assert_awaited_once_with(bot, "config_reloaded", actor="admin@example.org", target="config")
        reply = bot.reply_ok.call_args.args[1]
        assert "config.py reloaded." in reply
        assert "Prefix changed from ',' to ';'." in reply
        assert "require a bot restart" in reply
    finally:
        config_cmd.config.clear()
        config_cmd.config.update(original_config)


@pytest.mark.asyncio
async def test_config_validate_and_reload_report_errors(monkeypatch):
    bot = MagicMock()
    bot.prefix = ","
    bot.nick = "oldnick"
    bot.reply_error = MagicMock()
    msg = MagicMock()

    monkeypatch.setattr(config_cmd, "load_config", MagicMock(side_effect=config_cmd.ConfigError("bad config")))
    await config_cmd.config_validate(bot, "admin@example.org", "admin", [], msg, False)
    assert "Invalid config.py:\nbad config" in bot.reply_error.call_args.args[1]

    await config_cmd.config_reload(bot, "admin@example.org", "admin", [], msg, False)
    assert "Config reload failed:\nbad config" in bot.reply_error.call_args.args[1]
