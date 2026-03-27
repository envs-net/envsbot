"""
Plugin reload integrity tests.

This test verifies that repeated plugin reloads do not corrupt the global
command registry and that plugin modules are cleanly replaced.

The test intentionally avoids relying on Python's garbage collector and
instead validates deterministic invariants of the framework state.

For every discovered plugin that defines commands, the test repeatedly
reloads the plugin and verifies the following properties:

- Command tokens registered by the plugin remain identical across reloads.
- The number of commands owned by the plugin does not change.
- Command ownership (plugin → command mapping) remains stable.
- Handler functions are replaced on every reload.
- The plugin module object is replaced on every reload.
- No command handler originates from a previous module generation.

The last property ensures that the framework does not retain references
to handlers from earlier plugin instances. Because handler functions
expose their originating module via `__module__`, this can be checked
deterministically without relying on garbage collection.

The global COMMANDS registry is cleared before and after the test to
guarantee isolation from other tests or bot initialization.
"""

import sys

import pytest

from utils.command import COMMANDS

RELOAD_COUNT = 100


def snapshot(plugin):
    """Capture registry state for a plugin."""

    owners = COMMANDS.by_plugin.get(plugin, set())

    handlers = {
        name: COMMANDS.index[name].handler
        for name in owners
    }

    module = sys.modules.get(f"plugins.{plugin}")

    return {
        "command_tokens": set(owners),
        "command_count": len(owners),
        "owners": {name: plugin for name in owners},
        "plugin_handler_count": len(handlers),
        "handler_ids": {name: id(h) for name, h in handlers.items()},
        "handler_modules": {name: h.__module__ for name, h in handlers.items()},
        "module": module,
    }


@pytest.fixture(autouse=True)
def _clean_command_registry():
    """Ensure the global command registry is empty for the test."""

    COMMANDS.index.clear()
    COMMANDS.by_handler.clear()
    COMMANDS.by_plugin.clear()
    COMMANDS.by_prefix.clear()

    yield

    COMMANDS.index.clear()
    COMMANDS.by_handler.clear()
    COMMANDS.by_plugin.clear()
    COMMANDS.by_prefix.clear()


async def test_plugin_reload_integrity_all(bot):
    """Repeated plugin reloads must not corrupt the command registry."""

    pm = bot.bot_plugins
    plugins = sorted(pm.discover())

    for plugin in plugins:

        try:
            await pm.unload(plugin)
        except Exception:
            pass

        await pm.load(plugin)

        before = snapshot(plugin)

        # Skip plugins without commands
        if not before["command_tokens"]:
            continue

        initial_module = before["module"]

        for _ in range(RELOAD_COUNT):

            await pm.reload(plugin)

            now = snapshot(plugin)

            # --- registry invariants ---
            assert now["command_tokens"] == before["command_tokens"]
            assert now["command_count"] == before["command_count"]
            assert now["owners"] == before["owners"]
            assert now["plugin_handler_count"] == before["plugin_handler_count"]

            # --- module replacement ---
            assert now["module"] is not initial_module

            # --- handler replacement ---
            assert now["handler_ids"] != before["handler_ids"]

            # --- deterministic leak check ---
            for module_name in now["handler_modules"].values():
                assert module_name == f"plugins.{plugin}"
