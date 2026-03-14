"""
Plugin reload safety tests.

These tests verify that loading plugins multiple times does not
duplicate command registrations or corrupt the command registry.
"""

from plugin_manager import PluginManager


def test_plugin_reload_does_not_duplicate_commands(bot):
    """
    Ensure reloading plugins does not register duplicate commands.
    """

    initial_commands = set(bot.commands.keys())

    pm = PluginManager(bot)
    pm.load_all()

    reloaded_commands = set(bot.commands.keys())

    assert initial_commands == reloaded_commands, \
        "Plugin reload changed command registry"


def test_plugin_reload_command_count_stable(bot):
    """
    Ensure command count stays stable after plugin reload.
    """

    initial_count = len(bot.commands)

    pm = PluginManager(bot)
    pm.load_all()

    reloaded_count = len(bot.commands)

    assert initial_count == reloaded_count, \
        "Plugin reload caused duplicate or missing commands"
