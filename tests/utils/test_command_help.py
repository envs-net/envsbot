from __future__ import annotations

import pytest

import utils.command_help as command_help


def test_metadata_for_reads_from_registry():
    metadata = command_help.metadata_for("help")

    assert metadata is not None
    assert metadata["short"]
    assert metadata["usage"].startswith("{prefix}help")
    assert metadata["examples"]
    assert metadata["context"] in {"any", "private", "room", "room-admin"}


def test_command_help_compat_view_is_lazy_mapping():
    view = command_help.__getattr__("COMMAND_HELP")

    assert "help" in view
    assert view.get("help") == command_help.metadata_for("help")
    assert view.get("missing", {"short": "fallback"}) == {"short": "fallback"}
    assert len(view) >= 1
    assert "help" in list(view.keys())
    assert any(item[0] == "help" for item in view.items())
    assert command_help.metadata_for("HELP") == command_help.metadata_for("help")


def test_command_help_unknown_attribute_raises():
    with pytest.raises(AttributeError):
        command_help.__getattr__("UNKNOWN")


def test_command_help_view_iteration_uses_registry_keys():
    view = command_help.__getattr__("COMMAND_HELP")

    assert "help" in list(iter(view))
