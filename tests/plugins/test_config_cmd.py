from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import plugins.config_cmd as config_cmd


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
