from __future__ import annotations

from utils.plugin_metadata import validate_plugin_metadata


def test_validate_plugin_metadata_accepts_minimal_valid_meta():
    issues = validate_plugin_metadata(
        "rss",
        {"name": "rss", "description": "feeds", "category": "info", "requires": ["rooms"]},
    )
    assert issues == []


def test_validate_plugin_metadata_reports_errors_and_warnings():
    issues = validate_plugin_metadata(
        "rss",
        {"name": "wrong", "description": "", "category": "info", "requires": "rooms", "extra": True},
    )
    messages = [issue.format() for issue in issues]
    assert any("missing non-empty 'description'" in message for message in messages)
    assert any("name is 'wrong'" in message for message in messages)
    assert any("requires must be a list" in message for message in messages)
    assert any("unknown metadata keys" in message for message in messages)
