"""
Reload integrity test for all plugins.

This verifies that repeated reloads do not corrupt:

- command registry
- command ownership
- alias index
- module replacement
"""

import sys

from utils.command import COMMAND_INDEX


RELOAD_COUNT = 100


def snapshot(bot, plugin):

    pm = bot.plugins

    commands = dict(bot.commands)
    owners = dict(pm.command_owner)

    index_keys = set(COMMAND_INDEX.keys())

    module = sys.modules.get(f"plugins.{plugin}")

    plugin_handlers = {
        commands[name]
        for name, owner in owners.items()
        if owner == plugin
    }

    return {
        "command_names": set(commands.keys()),
        "owners": owners,
        "index_keys": index_keys,
        "plugin_handler_count": len(plugin_handlers),
        "module": module,
    }


def test_plugin_reload_integrity_all(bot):

    pm = bot.plugins

    # discover all available plugins
    plugins = sorted(pm.discover())

    for plugin in plugins:

        pm.load(plugin)

        before = snapshot(bot, plugin)

        for _ in range(RELOAD_COUNT):

            pm.reload(plugin)

            now = snapshot(bot, plugin)

            # command names must remain identical
            assert now["command_names"] == before["command_names"]

            # command ownership must remain identical
            assert now["owners"] == before["owners"]

            # alias index must remain identical
            assert now["index_keys"] == before["index_keys"]

            # handler count for the plugin must remain stable
            assert now["plugin_handler_count"] == before["plugin_handler_count"]

            # module must actually be replaced
            assert now["module"] is not before["module"]

            before = now

        pm.unload(plugin)
