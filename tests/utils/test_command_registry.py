from __future__ import annotations

from types import SimpleNamespace

import utils.command_registry as registry
from utils.command import Role


class FakeCommands(dict):
    def __init__(self):
        super().__init__()
        self.by_plugin = {}

    def __eq__(self, other):
        if not isinstance(other, FakeCommands):
            return dict.__eq__(self, other)
        return dict.__eq__(self, other) and self.by_plugin == other.by_plugin


def test_command_records_normalize_live_registry_metadata(monkeypatch):
    commands = FakeCommands()
    handler = lambda: None
    primary_cmd = SimpleNamespace(
        name="alpha",
        role=Role.ADMIN,
        handler=handler,
        short="Alpha command",
        usage="{prefix}alpha",
        examples=("{prefix}alpha",),
        category="admin",
        context="private chat / MUC PM",
    )
    alias_cmd = SimpleNamespace(
        name="alpha",
        role=Role.ADMIN,
        handler=handler,
        short="Alias should point to alpha",
        usage="{prefix}a",
        examples=[],
        category="admin",
        context="private chat / MUC PM",
    )
    fallback_cmd = SimpleNamespace(name="fallback", role=Role.NONE)

    commands[("alpha",)] = primary_cmd
    commands[("a",)] = alias_cmd
    commands[("fallback",)] = fallback_cmd
    commands.by_plugin = {
        "_admin": {("alpha",), ("a",)},
        "tools": {("fallback",)},
    }
    monkeypatch.setattr(registry, "COMMANDS", commands)

    records = registry.command_records()

    assert records == [
        {
            "registered_name": "a",
            "primary_name": "alpha",
            "plugin": "_admin",
            "source": "core",
            "is_alias": True,
            "role": Role.ADMIN,
            "handler": "<lambda>",
            "short": "Alias should point to alpha",
            "usage": "{prefix}a",
            "examples": [],
            "category": "admin",
            "context": "private chat / MUC PM",
        },
        {
            "registered_name": "alpha",
            "primary_name": "alpha",
            "plugin": "_admin",
            "source": "core",
            "is_alias": False,
            "role": Role.ADMIN,
            "handler": "<lambda>",
            "short": "Alpha command",
            "usage": "{prefix}alpha",
            "examples": ["{prefix}alpha"],
            "category": "admin",
            "context": "private chat / MUC PM",
        },
        {
            "registered_name": "fallback",
            "primary_name": "fallback",
            "plugin": "tools",
            "source": "plugins",
            "is_alias": False,
            "role": Role.NONE,
            "handler": "unknown",
            "short": "",
            "usage": "",
            "examples": [],
            "category": "other",
            "context": "any",
        },
    ]


def test_primary_command_records_filters_aliases(monkeypatch):
    monkeypatch.setattr(
        registry,
        "command_records",
        lambda: [
            {"registered_name": "alias", "is_alias": True},
            {"registered_name": "primary", "is_alias": False},
        ],
    )

    assert registry.primary_command_records() == [{"registered_name": "primary", "is_alias": False}]


def test_command_records_preserve_multiword_fallbacks_and_first_plugin_owner(monkeypatch):
    commands = FakeCommands()

    def custom_handler():
        return None

    fallback = SimpleNamespace(
        role=Role.USER,
        handler=custom_handler,
        examples=None,
        category=None,
        context="",
        short="Fallback command",
        usage="{prefix}two words",
    )
    commands[("two", "words")] = fallback
    commands.by_plugin = {
        "_first": {("two", "words")},
        "second": {("two", "words")},
    }
    monkeypatch.setattr(registry, "COMMANDS", commands)

    assert registry.command_records() == [
        {
            "registered_name": "two words",
            "primary_name": "two words",
            "plugin": "_first",
            "source": "core",
            "is_alias": False,
            "role": Role.USER,
            "handler": "custom_handler",
            "short": "Fallback command",
            "usage": "{prefix}two words",
            "examples": [],
            "category": "other",
            "context": "any",
        }
    ]


def test_command_records_without_plugin_remain_plugin_source(monkeypatch):
    commands = FakeCommands()
    commands[("orphan",)] = SimpleNamespace(name="primary")
    monkeypatch.setattr(registry, "COMMANDS", commands)

    record = registry.command_records()[0]
    assert record["registered_name"] == "orphan"
    assert record["primary_name"] == "primary"
    assert record["plugin"] == ""
    assert record["source"] == "plugins"
    assert record["is_alias"] is True
