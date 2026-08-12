from __future__ import annotations

from utils.plugin_metadata import validate_plugin_metadata


def test_validate_plugin_metadata_accepts_minimal_valid_meta():
    issues = validate_plugin_metadata(
        "rss",
        {
            "name": "rss",
            "description": "feeds",
            "category": "info",
            "requires": ["rooms"],
            "hidden": False,
        },
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


def test_validate_plugin_metadata_accepts_declarative_room_state():
    issues = validate_plugin_metadata(
        "demo",
        {
            "name": "demo",
            "description": "demo",
            "category": "utility",
            "room_state": "custom",
        },
    )
    assert issues == []


def test_validate_plugin_metadata_rejects_unknown_room_state():
    issues = validate_plugin_metadata(
        "demo",
        {
            "name": "demo",
            "description": "demo",
            "category": "utility",
            "room_state": "forever",
        },
    )
    assert any("room_state must be one of" in issue.message for issue in issues)


def test_custom_room_state_requires_cleanup_hook():
    from types import SimpleNamespace

    from utils.plugin_metadata import validate_plugin_lifecycle

    missing = validate_plugin_lifecycle(
        "demo",
        {"room_state": "custom"},
        SimpleNamespace(),
    )
    assert len(missing) == 1
    assert missing[0].severity == "error"

    modern = validate_plugin_lifecycle(
        "demo",
        {"room_state": "custom"},
        SimpleNamespace(cleanup_room_state=lambda bot, room: None),
    )
    legacy = validate_plugin_lifecycle(
        "demo",
        {"room_state": "custom"},
        SimpleNamespace(on_room_delete=lambda bot, room: None),
    )
    assert modern == []
    assert legacy == []
